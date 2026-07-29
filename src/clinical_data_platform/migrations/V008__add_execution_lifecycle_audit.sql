ALTER TABLE audit.pipeline_runs
    DROP CONSTRAINT IF EXISTS pipeline_runs_status_check;

ALTER TABLE audit.pipeline_runs
    ADD COLUMN current_stage TEXT,
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN started_at TIMESTAMPTZ,
    ADD COLUMN validated_at TIMESTAMPTZ,
    ADD COLUMN loading_started_at TIMESTAMPTZ,
    ADD COLUMN completed_at TIMESTAMPTZ,
    ADD COLUMN failed_at TIMESTAMPTZ,
    ADD COLUMN failure_stage TEXT,
    ADD COLUMN failure_type TEXT,
    ADD COLUMN failure_message TEXT,
    ADD COLUMN failure_code TEXT,
    ADD COLUMN failure_details JSONB,
    ADD COLUMN journal_event_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN journal_head_sha256 CHAR(64),
    ADD COLUMN audit_gap_reason TEXT,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE audit.pipeline_runs
SET
    current_stage = CASE
        WHEN status = 'completed' THEN 'completed'
        ELSE 'legacy_failure'
    END,
    attempt_count = 1,
    started_at = generated_at,
    validated_at = generated_at,
    loading_started_at = loaded_at,
    completed_at = CASE WHEN status = 'completed' THEN loaded_at ELSE NULL END,
    failed_at = CASE WHEN status = 'failed' THEN loaded_at ELSE NULL END,
    failure_stage = CASE WHEN status = 'failed' THEN 'legacy_unknown' ELSE NULL END,
    failure_type = CASE WHEN status = 'failed' THEN 'legacy.failure' ELSE NULL END,
    failure_message = CASE
        WHEN status = 'failed' THEN 'Failure occurred before V008; details unavailable.'
        ELSE NULL
    END,
    audit_gap_reason = 'pre_v008_execution_history_unavailable';

ALTER TABLE audit.pipeline_runs
    ALTER COLUMN current_stage SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL,
    ADD CONSTRAINT pipeline_runs_status_check CHECK (
        status IN (
            'created',
            'raw_captured',
            'validating',
            'validated',
            'loading',
            'completed',
            'failed'
        )
    ),
    ADD CONSTRAINT pipeline_runs_current_stage_not_blank CHECK (
        btrim(current_stage) <> ''
    ),
    ADD CONSTRAINT pipeline_runs_attempt_count_nonnegative CHECK (
        attempt_count >= 0
    ),
    ADD CONSTRAINT pipeline_runs_journal_event_count_nonnegative CHECK (
        journal_event_count >= 0
    ),
    ADD CONSTRAINT pipeline_runs_journal_head_shape CHECK (
        journal_head_sha256 IS NULL OR length(btrim(journal_head_sha256)) = 64
    ),
    ADD CONSTRAINT pipeline_runs_failure_fields_consistent CHECK (
        (
            status = 'failed'
            AND failed_at IS NOT NULL
            AND failure_stage IS NOT NULL
            AND btrim(failure_stage) <> ''
            AND failure_type IS NOT NULL
            AND btrim(failure_type) <> ''
            AND failure_message IS NOT NULL
            AND btrim(failure_message) <> ''
        )
        OR
        (
            status <> 'failed'
            AND failed_at IS NULL
            AND failure_stage IS NULL
            AND failure_type IS NULL
            AND failure_message IS NULL
            AND failure_code IS NULL
            AND failure_details IS NULL
        )
    ),
    ADD CONSTRAINT pipeline_runs_validation_timestamp_consistent CHECK (
        status IN ('created', 'raw_captured', 'validating')
        OR validated_at IS NOT NULL
    ),
    ADD CONSTRAINT pipeline_runs_loading_timestamp_consistent CHECK (
        status NOT IN ('loading', 'completed')
        OR loading_started_at IS NOT NULL
    ),
    ADD CONSTRAINT pipeline_runs_completion_timestamp_consistent CHECK (
        (status = 'completed' AND completed_at IS NOT NULL)
        OR (status <> 'completed' AND completed_at IS NULL)
    ),
    ADD CONSTRAINT pipeline_runs_timestamp_order CHECK (
        (validated_at IS NULL OR validated_at >= started_at)
        AND (loading_started_at IS NULL OR loading_started_at >= started_at)
        AND (completed_at IS NULL OR completed_at >= started_at)
        AND (failed_at IS NULL OR failed_at >= started_at)
    );

CREATE TABLE audit.pipeline_run_events (
    event_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1),
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 0),
    from_status TEXT,
    to_status TEXT NOT NULL,
    stage TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    previous_event_sha256 CHAR(64),
    event_sha256 CHAR(64) NOT NULL,
    error_type TEXT,
    error_message TEXT,
    error_code TEXT,
    details JSONB NOT NULL DEFAULT '{}'::JSONB,
    event_source TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, sequence_number),
    UNIQUE (run_id, event_sha256),
    CHECK (
        from_status IS NULL
        OR from_status IN (
            'created',
            'raw_captured',
            'validating',
            'validated',
            'loading',
            'completed',
            'failed'
        )
    ),
    CHECK (
        to_status IN (
            'created',
            'raw_captured',
            'validating',
            'validated',
            'loading',
            'completed',
            'failed'
        )
    ),
    CHECK (btrim(stage) <> ''),
    CHECK (length(btrim(event_sha256)) = 64),
    CHECK (
        previous_event_sha256 IS NULL
        OR length(btrim(previous_event_sha256)) = 64
    ),
    CHECK (event_source IN ('local_journal', 'database', 'migration_backfill')),
    CHECK (
        (
            to_status = 'failed'
            AND error_type IS NOT NULL
            AND btrim(error_type) <> ''
            AND error_message IS NOT NULL
            AND btrim(error_message) <> ''
        )
        OR
        (
            to_status <> 'failed'
            AND error_type IS NULL
            AND error_message IS NULL
            AND error_code IS NULL
        )
    )
);

CREATE INDEX idx_pipeline_runs_status_dataset
    ON audit.pipeline_runs (status, dataset_name, updated_at DESC);
CREATE INDEX idx_pipeline_run_events_run_sequence
    ON audit.pipeline_run_events (run_id, sequence_number);
CREATE INDEX idx_pipeline_run_events_failed
    ON audit.pipeline_run_events (occurred_at DESC)
    WHERE to_status = 'failed';

CREATE FUNCTION audit.enforce_pipeline_run_status_transition()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.status = 'created' AND NEW.status IN ('raw_captured', 'failed'))
        OR (OLD.status = 'raw_captured' AND NEW.status IN ('validating', 'failed'))
        OR (OLD.status = 'validating' AND NEW.status IN ('validated', 'failed'))
        OR (OLD.status = 'validated' AND NEW.status IN ('loading', 'failed'))
        OR (OLD.status = 'loading' AND NEW.status IN ('completed', 'failed'))
        OR (OLD.status = 'failed' AND NEW.status = 'loading')
    ) THEN
        RAISE EXCEPTION 'Unsupported pipeline status transition: % -> %',
            OLD.status,
            NEW.status
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;

CREATE TRIGGER trg_pipeline_runs_status_transition
BEFORE UPDATE OF status ON audit.pipeline_runs
FOR EACH ROW
EXECUTE FUNCTION audit.enforce_pipeline_run_status_transition();

CREATE FUNCTION audit.touch_pipeline_run_updated_at()
RETURNS TRIGGER
LANGUAGE PLPGSQL
AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END
$$;

CREATE TRIGGER trg_pipeline_runs_updated_at
BEFORE UPDATE ON audit.pipeline_runs
FOR EACH ROW
EXECUTE FUNCTION audit.touch_pipeline_run_updated_at();

CREATE VIEW audit.pipeline_run_timeline AS
SELECT
    run_row.run_id,
    run_row.dataset_name,
    run_row.status AS current_status,
    run_row.current_stage,
    run_row.attempt_count,
    event.sequence_number,
    event.attempt_number,
    event.from_status,
    event.to_status,
    event.stage,
    event.occurred_at,
    event.error_type,
    event.error_message,
    event.error_code,
    event.details,
    event.event_source,
    event.event_sha256,
    event.previous_event_sha256
FROM audit.pipeline_runs AS run_row
LEFT JOIN audit.pipeline_run_events AS event
    ON event.run_id = run_row.run_id;

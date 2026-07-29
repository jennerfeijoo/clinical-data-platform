ALTER TABLE audit.pipeline_runs
    ADD COLUMN raw_receipt_id UUID,
    ADD COLUMN raw_received_at TIMESTAMPTZ,
    ADD COLUMN raw_storage_version TEXT,
    ADD COLUMN raw_manifest_path TEXT,
    ADD COLUMN raw_manifest_sha256 CHAR(64),
    ADD COLUMN raw_object_path TEXT,
    ADD COLUMN raw_size_bytes BIGINT;

UPDATE audit.pipeline_runs
SET raw_receipt_id = '00000000-0000-0000-0000-000000000000'::UUID,
    raw_received_at = generated_at,
    raw_storage_version = 'legacy/unmanaged',
    raw_manifest_path = 'legacy/unmanaged',
    raw_manifest_sha256 =
        '0000000000000000000000000000000000000000000000000000000000000000',
    raw_object_path = 'legacy/unmanaged',
    raw_size_bytes = 0
WHERE raw_receipt_id IS NULL;

ALTER TABLE audit.pipeline_runs
    ALTER COLUMN raw_receipt_id SET NOT NULL,
    ALTER COLUMN raw_received_at SET NOT NULL,
    ALTER COLUMN raw_storage_version SET NOT NULL,
    ALTER COLUMN raw_manifest_path SET NOT NULL,
    ALTER COLUMN raw_manifest_sha256 SET NOT NULL,
    ALTER COLUMN raw_object_path SET NOT NULL,
    ALTER COLUMN raw_size_bytes SET NOT NULL,
    ADD CONSTRAINT pipeline_runs_raw_storage_version_nonempty
        CHECK (btrim(raw_storage_version) <> ''),
    ADD CONSTRAINT pipeline_runs_raw_manifest_path_nonempty
        CHECK (btrim(raw_manifest_path) <> ''),
    ADD CONSTRAINT pipeline_runs_raw_object_path_nonempty
        CHECK (btrim(raw_object_path) <> ''),
    ADD CONSTRAINT pipeline_runs_raw_size_nonnegative
        CHECK (raw_size_bytes >= 0);

CREATE INDEX idx_pipeline_runs_raw_receipt_id
    ON audit.pipeline_runs (raw_receipt_id);
CREATE INDEX idx_pipeline_runs_source_sha256
    ON audit.pipeline_runs (source_sha256);

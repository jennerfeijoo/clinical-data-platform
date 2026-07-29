ALTER TABLE audit.pipeline_runs
    ADD COLUMN contract_path TEXT;
ALTER TABLE audit.pipeline_runs
    ADD COLUMN contract_version TEXT;
ALTER TABLE audit.pipeline_runs
    ADD COLUMN contract_sha256 CHAR(64);

UPDATE audit.pipeline_runs
SET contract_path = 'legacy/unversioned',
    contract_version = '0.0.0',
    contract_sha256 =
        '0000000000000000000000000000000000000000000000000000000000000000'
WHERE contract_path IS NULL
   OR contract_version IS NULL
   OR contract_sha256 IS NULL;

ALTER TABLE audit.pipeline_runs
    ALTER COLUMN contract_path SET NOT NULL,
    ALTER COLUMN contract_version SET NOT NULL,
    ALTER COLUMN contract_sha256 SET NOT NULL;

CREATE INDEX idx_pipeline_runs_dataset_contract
    ON audit.pipeline_runs (dataset_name, contract_version);

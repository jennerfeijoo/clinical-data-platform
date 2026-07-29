# Immutable raw landing zone

## Storage layout

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Objects are addressed by their SHA-256. Receipts are append-only ingestion-event manifests.

## Capture

```powershell
clinical-data raw-capture patients data/sample/patients.csv `
  --raw-root data/raw
```

## Verify

```powershell
clinical-data raw-verify `
  receipts/patients/<YYYY>/<MM>/<DD>/<uuid>.json `
  --raw-root data/raw
```

## Invariants

- validation reads the captured object, not the external path;
- an existing final object or receipt is never overwritten;
- objects are published atomically from staging;
- identical bytes share one object;
- every receipt event has a distinct UUID;
- receipt path, object path, size, and SHA-256 are verified;
- persistence re-verifies raw lineage before its database transaction.

## Operational boundary

The local filesystem implementation provides application-level immutability and integrity checks. It is not certified WORM storage and does not provide cloud retention, replication, IAM, encryption policy, or administrator-resistant controls.

# Immutable raw landing

This page is the documentation-index entry for the immutable raw-data boundary. The operational reference remains [raw-landing-zone.md](raw-landing-zone.md).

The landing zone captures exact source bytes before parsing and stores:

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Core guarantees:

- content-addressed objects identified by SHA-256;
- append-only receipt manifests for individual reception events;
- atomic publication from staging;
- no application-level replacement of final objects or receipts;
- validation from the captured object rather than the external source path;
- path, size, and checksum verification before persistence;
- source and receipt lineage carried into quality reports and PostgreSQL audit records.

This is application-level local immutability, not certified WORM storage. A production clinic deployment would additionally require approved storage, retention, encryption, access-control, backup, recovery, and deletion controls.

See also:

- [Detailed raw landing reference](raw-landing-zone.md)
- [Architecture](architecture.md)
- [Database and lineage](database.md)
- [Clinical pilot readiness](clinical-pilot-readiness.md)

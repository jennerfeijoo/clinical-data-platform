# Python version matrix validation

This release is complete only when the same pull-request head passes all of the following GitHub Actions jobs:

```text
Reference quality (Python 3.11)
Compatibility (Python 3.12)
Compatibility (Python 3.13)
Compatibility (Python 3.14)
Governed loading benchmark (Python 3.11 reference)
```

The compatibility jobs must each use an isolated PostgreSQL 16 service and pass installation, `pip check`, package metadata assertions, contracts, migrations, and the complete pytest suite with at least 90% statement coverage.

The branch must not retain temporary write-enabled documentation workflows when merged.

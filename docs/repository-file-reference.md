# Repository file reference

A complete per-file reference is distributed as the companion PDF generated for the clinic-pilot preparation review. The PDF describes the objective, composition, and function of every tracked repository file.

This lightweight repository page records the interpretation rules used by that reference:

1. executable migrations and contracts are normative for schema and accepted data;
2. source code and tests are normative for runtime behavior and enforced policy;
3. workflows and generated evidence are normative only for the exact commit and configured run;
4. documentation explains the system but must be corrected when it diverges from executable evidence;
5. synthetic fixtures and sample CSV files are demonstrations, not clinically representative datasets;
6. pilot templates are governance aids, not authorization to process identifiable patient data.

Primary maps:

- [Documentation index](index.md)
- [Architecture](architecture.md)
- [Clinical data coverage](clinical-data-coverage.md)
- [Clinical pilot readiness](clinical-pilot-readiness.md)
- [Current limitations](limitations.md)

The companion PDF should be regenerated whenever files are added, renamed, removed, or materially change responsibility.

# Governed release process

Version `0.21.0` introduces a release gate for Python artifacts and GitHub Releases. It does not publish to PyPI. PyPI publication must remain disabled until a separate review configures and validates Trusted Publishing.

## Release objects

A governed release consists of:

```text
Git commit on main
+ annotated or lightweight tag vX.Y.Z
+ wheel
+ source distribution
+ SHA256SUMS
+ release-manifest.json
+ GitHub Release linked to the exact tag
```

The Docker image continues to be built and scanned in CI but is not published to a registry by this workflow.

## Version sources

The following values must agree exactly:

```text
pyproject.toml project.version
src/clinical_data_platform/__init__.py __version__
first CHANGELOG.md version heading
CITATION.cff version
README status version
tests/test_package.py assertion
CI installed-package assertion
Git tag vX.Y.Z
```

Run:

```bash
python scripts/check_release.py --expected-version X.Y.Z
```

For a tag candidate:

```bash
python scripts/check_release.py \
  --expected-version X.Y.Z \
  --expected-tag vX.Y.Z
```

The check also validates required documentation, the release dependency group, packaged data configuration, workflow controls, citation date format, and equality between the repository and packaged hypertension cohort SQL.

## Distribution contents

The wheel contains executable Python code and runtime resources:

- the `py.typed` marker;
- executable contracts and their manifest;
- migrations V001–V008;
- packaged Synthea profiles;
- the default hypertension cohort SQL;
- the three console entrypoints.

Repository-only tests, documentation, security reports, scripts, and generated data are excluded from the wheel.

The source distribution includes source code, tests, documentation, policy files, scripts, SQL, security baseline, and bundled synthetic sample data. Generated raw, processed, analytics, Synthea, benchmark, environment, and Git metadata are excluded.

Validate a build with:

```bash
python -m build --outdir dist
python -m twine check dist/*
python scripts/verify_distribution.py dist \
  --expected-version X.Y.Z \
  --manifest release-manifest.json \
  --checksums SHA256SUMS
```

## Reproducible build gate

CI and the tag workflow set `SOURCE_DATE_EPOCH` from the release commit timestamp, build the wheel and sdist twice in clean output directories, and require byte-identical artifact pairs.

This proves reproducibility for the recorded GitHub Actions environment, source commit, Python version, build backend, and resolved build dependencies. It does not prove universal reproducibility across all operating systems and future toolchains.

## Clean-wheel installation

The release gate creates a new virtual environment, installs the built wheel rather than the repository, changes to a directory outside the source tree, and verifies:

```text
importlib.metadata version
clinical-data validate-contracts
clinical-data-cohort list-profiles
packaged migrations
packaged hypertension SQL
```

This prevents an editable installation or repository-relative file from masking missing wheel contents.

## Pull-request gate

Every pull request builds and validates release artifacts in the `Release package smoke` CI job. The resulting artifact is retained temporarily for inspection but is not a formal release.

The security workflow audits the release toolchain together with development and security dependencies.

## Tag workflow

`.github/workflows/release.yml` runs only for tags matching:

```text
v[0-9]+.[0-9]+.[0-9]+
```

It:

1. checks out the exact tag with full history;
2. derives `X.Y.Z` from the tag;
3. validates release metadata and tag identity;
4. builds twice with a fixed source epoch;
5. checks artifact reproducibility;
6. runs `twine check`;
7. verifies wheel and sdist contents;
8. installs and exercises the wheel outside the repository;
9. uploads workflow evidence;
10. creates a GitHub Release containing the wheel, sdist, checksums, and manifest.

The workflow has `contents: write` only because creating a GitHub Release requires it. Other workflows retain read-only repository permissions except CodeQL's scoped security-event permission.

## Human release checklist

Before creating a tag:

- confirm `main` is current and all required CI, Security, and Benchmark workflows passed on the release commit;
- review CHANGELOG and claim boundaries;
- confirm no migration, contract, terminology, or dataset change is undocumented;
- run the release checker locally;
- inspect the CI-built wheel and source distribution;
- verify there is no existing tag or release with the same version;
- create the tag only on the validated commit.

Example:

```bash
git switch main
git pull --ff-only origin main
python scripts/check_release.py --expected-version X.Y.Z
git tag -a vX.Y.Z -m "Clinical Data Platform X.Y.Z"
git push origin vX.Y.Z
```

Do not move or recreate a published release tag. Correct a release through a new version.

## Failure handling

If the tag workflow fails before release creation, do not create assets manually. Correct the problem on a new commit, increment the version when the failed tag has been shared or consumed, and repeat the governed process.

If a GitHub Release is created with a defect, preserve the evidence, document the problem, and issue a new version. Deleting or silently replacing artifacts breaks provenance.

## PyPI boundary

The repository currently contains no PyPI publish step and requests no OpenID Connect publishing token. A future PyPI release requires:

- project-name availability and ownership review;
- Trusted Publishing configuration for the exact repository and workflow;
- a separate dry run against TestPyPI when appropriate;
- package metadata and license review;
- explicit approval of the public support and maintenance claim.

Until then, GitHub Release artifacts are the governed distribution channel.

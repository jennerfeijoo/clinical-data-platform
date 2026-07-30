# Container hardening

Version `0.20.0` adds an executable runtime-hardening policy for the application image. The objective is not merely to place a `USER` instruction in the Dockerfile; the project verifies that real CLI operations work without root, without Linux capabilities, and with a read-only root filesystem.

## Threat model

The controls reduce the impact of an application-process compromise by limiting what that process can modify or request from the kernel. They target common container risks:

- accidental or malicious writes to packaged application files;
- execution as UID `0`;
- privilege escalation through setuid/setgid executables;
- unnecessary Linux capabilities;
- persistence through the container root filesystem;
- uncontrolled process creation;
- executable payloads written to temporary storage;
- hidden assumptions that only succeed when a bind mount is root-owned.

The controls do not claim that the container is an isolation boundary equivalent to a virtual machine.

## Fixed runtime identity

The final image creates:

```text
user: clinical
uid: 10001
gid: 10001
home: /home/clinical
shell: /usr/sbin/nologin
```

The Dockerfile ends with:

```dockerfile
USER 10001:10001
```

Using a numeric identity avoids ambiguity when the image runs on a host or orchestrator that does not resolve the account name. The `/etc/passwd` entry remains present so libraries can resolve the current user and home directory.

The UID and GID are intentionally fixed. A bind-mounted output directory must therefore be writable for UID `10001`, or the caller must use a named volume initialized from the image-owned output directory.

## Read-only application content

The runtime image contains only:

- the installed virtual environment;
- bundled sample CSV files used by the demo;
- packaged cohort SQL;
- empty output mount points.

The build sets `/opt/venv` and `/app` read-only before granting ownership only to the empty output directories:

```text
/app/data/raw
/app/data/processed
/app/data/analytics
```

The supported hardened runtime additionally sets the entire container root filesystem read-only. Writes are possible only through explicitly mounted output volumes or `/tmp`.

## Removed build and package-management surface

The multi-stage build removes from the final runtime:

```text
pip
setuptools
wheel
ensurepip
global Python site-packages inherited from the base image
```

The final image therefore cannot install Python packages at runtime through the standard bundled tooling. This reduces mutable supply-chain surface but does not prevent every possible download or code-execution technique.

The build also removes setuid and setgid bits from regular files under `/usr`, `/bin`, and `/sbin`. The application does not require privilege-changing executables.

## Hardened execution profile

Reference invocation:

```bash
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  clinical-data-platform:local validate-contracts
```

### `--read-only`

The root filesystem cannot be modified after container start. This turns undeclared write paths into immediate failures rather than silent state.

### `--tmpfs /tmp:rw,noexec,nosuid`

Temporary files remain memory-backed and disappear when the container exits. `noexec` blocks direct execution from the mount, while `nosuid` prevents privilege bits from taking effect there.

Python bytecode generation is disabled. XDG cache and configuration paths point into `/tmp` so libraries that need ephemeral cache state do not require a writable home directory.

### `--cap-drop ALL`

The application requires normal file access and outbound PostgreSQL connectivity but no Linux capability. Dropping all capabilities removes privileges such as changing ownership, overriding file permissions, creating raw sockets, or administering the network namespace.

### `no-new-privileges`

The kernel prevents the process and descendants from gaining additional privileges through executable metadata. This complements removal of setuid/setgid bits.

### `--pids-limit 256`

The process ceiling limits accidental or malicious process proliferation. The value is deliberately conservative for a single CLI workload, not a universal production sizing recommendation.

## Writable output volumes

A raw-capture invocation with a bind mount can use:

```bash
mkdir -p ./runtime/raw
chmod 0777 ./runtime/raw

docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  --mount type=bind,src="$(pwd)/runtime/raw",dst=/app/data/raw \
  clinical-data-platform:local \
  raw-capture patients /app/data/sample/patients.csv \
  --raw-root /app/data/raw
```

`chmod 0777` is used only as a portable demonstration. A real deployment should assign the directory to the numeric runtime identity and use narrower permissions:

```bash
sudo chown 10001:10001 ./runtime/raw
chmod 0750 ./runtime/raw
```

Named volumes avoid host-UID mismatch and are used by the Compose demo for raw, processed, and analytics outputs.

## Compose policy

The application service declares:

```yaml
user: "10001:10001"
read_only: true
cap_drop:
  - ALL
security_opt:
  - no-new-privileges:true
pids_limit: 256
tmpfs:
  - /tmp:rw,noexec,nosuid,size=64m,mode=1777
```

The service mounts three named volumes at the governed output paths. It no longer bind-mounts the complete repository `data/` directory into the container.

Run the demo with:

```bash
docker compose --profile demo up --build --abort-on-container-exit app
```

## CI evidence

The Python 3.11 reference job verifies:

1. the image metadata declares `10001:10001`;
2. the effective UID and GID are both `10001`;
3. the account shell is `/usr/sbin/nologin`;
4. `/app` and `/opt/venv` are not writable;
5. `/tmp` remains writable under the hardened flags;
6. contract and Synthea profile commands work;
7. cohort entrypoints work;
8. packaged migrations remain discoverable;
9. PostgreSQL migration validation works from the hardened container;
10. raw capture writes through an explicit bind mount;
11. the generated receipt file is owned by UID `10001`.

Policy tests also inspect the Dockerfile, Compose file, and CI workflow so that removal of any required control becomes a test failure.

## Operational limitations

The current implementation does not provide:

- image signing or provenance attestations;
- an admission controller or Kubernetes security policy;
- seccomp or AppArmor profiles beyond Docker defaults;
- network egress restrictions;
- secret injection or rotation;
- runtime anomaly detection;
- immutable WORM storage;
- PHI readiness or regulatory validation.

A green hardened-container test means that the configured CLI workloads succeeded under the documented restrictions. It does not prove absence of container escapes, kernel vulnerabilities, dependency compromise, application-logic vulnerabilities, or unsafe deployment configuration.

# Final quality gates — task 7.1

This historical core report is retained. Current MCP/Milestone B results,
including 982 offline tests and real Docker interoperability, are recorded in
[Milestone B verification](milestone_b_verification.md).

Verification date: 2026-10-24 (America/Sao_Paulo).

**Result: passed.** A fresh rebuild of committed HEAD produced **924 passed,
1 warning** in 8.56 seconds, and all four other quality gates passed offline.
The smallest fix is to give the clean Docker run disposable `/tmp` tmpfs
storage, preserving the existing SQLite lock budgets and test assertions.
Task 7.1 is complete; task 7.2 was not performed. No production code, tests,
dependency declarations, lockfile, or CI configuration were changed.

The initial disk-backed run produced **923 passed, 1 failed, 1 warning** in
54.42 seconds. That failure is retained below, together with the investigation
that established the storage-latency cause before changing the environment.

## Environment and provenance

| Item | Observed value |
| --- | --- |
| Tested commit | `f4e82111e4ef845e8a9e9082b97b2ba56a0304be` |
| Source | Fresh local clone, `--no-hardlinks --local --no-checkout`, followed by detached checkout of the SHA |
| Checkout checks | `git diff --exit-code` succeeded; `git ls-files --others --exclude-standard` returned no files before building |
| Container platform | Debian GNU/Linux 12 (bookworm), Linux/amd64 |
| Kernel | `5.15.167.4-microsoft-standard-WSL2` |
| Container engine | Docker Engine 28.0.1, Docker Desktop 4.39.0 |
| Python | CPython 3.12.14 |
| uv | 0.12.5, `x86_64-unknown-linux-musl` |
| Node | v22.16.0 |
| OpenSpec | 1.14.3 |
| SQLite | 3.40.1 |
| Test interpreter | `/workspace/.venv/bin/python` |
| Final rebuilt image ID | `sha256:364ee17204ff968586e7a86a15f65d366b1021a31d9fd55e0502cd50e84b6a0b` |
| Initial investigation image ID | `sha256:f3934309cd0adf9e6445d68d0e091a7c6816228fb8b1a065650d6661d7feb434` |
| Final temporary storage | `/tmp` tmpfs, 256 MiB, disposable per container |
| Clean checkout `uv.lock` SHA-256 | `e1ccc6cf7b9b19ed826442563be5aa533b00fca558efaca883b16f66abdf489b` |

The final build used another fresh local clone and `docker build --pull
--no-cache`; its install output explicitly reported a new `.venv` and downloads.
The original developer `.venv` and uncommitted/untracked project files were not
copied. The Dockerfile was an external verification harness in a temporary
directory. The container had no host mounts (`Mounts: []`), host credentials,
or Docker socket. Its `.git/HEAD` independently reported the tested SHA.

The developer checkout's lockfile byte hash was
`ece3d310b2a3bd19970cf71855a662abdc8204d87b57069329494c27ccada3e7`;
the clean checkout/container hashes above matched each other. Git reported no
tracked changes in either checkout; the byte difference reflects checkout line
endings, not a dependency edit.

## Installation

The image was built with `docker build --pull --no-cache`. Downloads were allowed
only during image construction. The resolved base image digests were:

```text
python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
node:22.16.0-bookworm-slim@sha256:048ed02c5fd52e86fda6fbd2f6a76cf0d4492fd6c6fee9e2c463ed5108da0e34
ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1
```

Installation commands inside the build:

```sh
npm install --global --ignore-scripts --no-audit --no-fund @fission-ai/openspec@1.14.3
uv sync --locked --group dev --python /usr/local/bin/python3.12
```

`UV_NO_CACHE=1` and `UV_PYTHON_DOWNLOADS=never` were set. uv created a fresh
`.venv`, resolved 29 packages, and installed 28 packages, including the editable
AgentGate package built from `/workspace`. No existing developer package cache
or virtual environment was mounted. `uv.lock` was unchanged by installation.
Observed gate versions were Pytest 8.4.2, Ruff 0.17.2, and Mypy 1.20.2.

## Offline enforcement and gate results

The installed image was started as:

```sh
docker run -d --name agentgate-quality-final --network none \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  agentgate-quality:task71-final sleep infinity
docker inspect --format '{{json .HostConfig.NetworkMode}} {{json .HostConfig.Tmpfs}} {{json .Mounts}}' agentgate-quality-final
```

Inspection returned `"none" {"/tmp":"rw,nosuid,nodev,size=256m"} []`.
`/proc/mounts` independently reported `/tmp` as tmpfs with `nosuid,nodev,noexec`.
An ordinary Python socket probe, outside
Pytest and its monkeypatches, observed:

```text
interfaces: [(1, 'lo')]
IPv4 routing table: header only, no routes
192.0.2.1:443       -> 101 ENETUNREACH
[2001:db8::1]:443   -> 101 ENETUNREACH
No inherited AgentGate configuration or prior Pytest state
```

The probe asserted that loopback was the only interface, both numeric-address
connections returned `ENETUNREACH`, and no `AGENTGATE_*` environment variable
was present. No DNS or live service was needed for these checks. The isolation
remained active for every command below, executed with `docker exec` in that
same container. `--offline` additionally prevented uv dependency downloads.

| Command | Exit | Actual result |
| --- | --- | --- |
| `uv run --offline --locked python -m pytest` | 0 | 924 passed, 1 warning; 924 collected; 8.56 seconds |
| `uv run --offline --locked python -m ruff check .` | 0 | All checks passed |
| `uv run --offline --locked python -m ruff format --check .` | 0 | 224 files already formatted |
| `uv run --offline --locked python -m mypy --strict src` | 0 | No issues in 151 source files |
| `openspec validate --all --strict` | 0 | `change/agentgate-core` passed; 1 item passed, 0 failed |

The final five-gate script used `set -eu` and exited zero. Its freshly started
container had no previous Pytest temporary state. The final run loaded no
diagnostic plugin or project patch. In the initial disk-backed verification,
the script stopped at Pytest's failure and the remaining gates were collected
separately. That initial failure was not discarded or retried until success.

All **123 architecture tests** passed in the full run. A separate offline
`python -m pytest --collect-only -q tests/architecture` confirmed that count.
The architecture rules continue to cover inward dependencies, domain purity,
slice isolation, CQRS, constructor injection, organization, and harness dispatch.

## Fixture enforcement and storage isolation

`tests/conftest.py::offline` remains autouse. It patches socket `connect`,
`connect_ex`, `create_connection`, and `subprocess.Popen` to reject attempts.
Its thread-local socketpair allowance supports local event-loop plumbing.
Container network isolation independently prevents external routes throughout
test collection, fixture setup, tests, and teardown; the fixture itself starts
at test setup. The fixture is not an OS-wide subprocess sandbox: its explicit
subprocess coverage is `Popen`, including `subprocess.run` through that path.
No bypass or new exception to the guard was introduced.

This additional command ran in the isolated container:

```sh
uv run --offline --locked python -m pytest -q --setup-show \
  tests/infrastructure/test_request_storage.py::test_network_and_subprocess_guards
```

It passed in the final container (1 test, 0.21 seconds), and setup explicitly showed
`SETUP F offline (fixtures used: monkeypatch)`. The self-test verifies that a
socket connection and subprocess invocation raise the guard's assertion.
This extra test is separate from the 924 passing tests in the full-suite result.

Review of the existing fixtures/tests confirmed:

- The function-scoped database fixture initializes `tmp_path/test.sqlite3`.
  Migration, backup, and missing-database cases also use `tmp_path`; schema
  comparison additionally uses an in-memory database.
- Principal, settings, clock, and sleeper fixtures use supplied test values.
  Credentials come from test constants/sentinels, not developer configuration.
  Missing-environment-credential startup rejection is explicitly tested.
- HTTP tests use FastAPI TestClient or HTTPX ASGITransport in process.
  Registered tools operate on local simulated accounts; no real financial API,
  LLM, MCP, or paid service is required.
- Restart tests reopen disposable files within their own test. The initial
  full run started with no prior Pytest execution or database in the image.

These checks establish fresh-run isolation, not universal order independence
or success under every scheduler/storage latency. The complete suite passed in
the explicitly documented clean environment; overloaded disk-backed environments
can still exercise the bounded, fail-closed lock behavior described below.

## Reproduced SQLite lock failure

The failing node was:

```text
tests/infrastructure/test_concurrent_execution_recovery.py::test_competing_transfers_revalidate_funds_under_write_lock[False]
```

The captured failure path was:

```text
race -> ExecuteOperationHandler.handle -> _record_attempt
     -> SqliteUnitOfWork.__enter__ -> BEGIN IMMEDIATE
OperationalError('database is locked')
     -> SqliteUnitOfWork._raise_failure -> TransientStorageLock
```

The concurrency helper sets `PRAGMA busy_timeout=10000` as a scheduling allowance.
However, `SqliteUnitOfWork.__enter__` assigns the execution deadline to the
`DeadlineConnection` before `BEGIN IMMEDIATE`. Every `execute` calls `prepare`,
which caps the wait at the lesser of 50 ms and the remaining deadline.
An offline diagnostic using the committed classes and FakeClock confirmed:

```text
Fixture scheduling allowance: 10000 ms; effective deadline busy timeout: 50 ms
```

The diagnostic configured an in-memory connection to 10000 ms, attached a
two-second `ExecutionDeadline`, called `prepare`, and read back 50 ms using
the underlying SQLite connection method. It changed no project files.

In `ExecuteOperationHandler.handle`, `_record_attempt` is called before the
inner `try` that handles transient locks from `_attempt`. The observed lock
therefore escaped that retry block. The helper expects success/Forbidden
outcomes and rejects retry sleeping. Its barrier aligns the first connections
but does not ensure either transaction completes inside the 50 ms lock budget.
The follow-up investigation traced `DeadlineConnection.execute`, `commit`,
`rollback`, and `close` from an external diagnostic Pytest plugin, recording
monotonic time, thread ID, connection identity, and transaction state. No
application/test code was edited. The exact failing node passed the first
isolated process and failed in the second, with the original traceback above.

The relevant captured timeline (seconds relative to trace start) was:

| Time | Connection | Observed action |
| --- | --- | --- |
| 0.132645 | B, winning worker's audit UoW | Starts `BEGIN IMMEDIATE` |
| 0.132677 | A, competing worker's audit UoW | Starts `BEGIN IMMEDIATE` |
| 0.155338 | B | BEGIN succeeds; `in_transaction=True` |
| 0.157669–0.162682 | B | Audit commit completes; `in_transaction=False` |
| 0.162694–0.162734 | B | Rollback of inactive transaction, then close completes |
| 0.162831–0.162850 | C, winning worker's execution UoW | New connection begins; `in_transaction=True` |
| 0.187402 | C | Starts committing the executed transfer |
| 0.207689 | A | BEGIN raises `OperationalError('database is locked')` |
| 0.207707–0.207771 | A | Rollback completes with no transaction; connection closes |
| 0.274945 | C | Commit completes; `in_transaction=False` |
| 0.274994–0.275073 | C | Rollback of inactive transaction, then close completes |

**Proven immediate cause:** the competing BEGIN expired its configured 50 ms
SQLite wait while C legitimately held the write lock. C's commit alone took
**87.543 ms**; A's measured call took approximately 75 ms, including scheduling
overhead. There was no abandoned transaction in this failure: B closed before
C began, A rolled back/closed on failed entry, and C closed after its commit.
The UoWs had distinct connections and thread ownership. No shared live
connection or missing rollback/close fix is indicated by the trace.

The initial connection barrier synchronizes worker arrival, not lock ownership
or completion. The winning worker can close its audit transaction and acquire
another connection's write lock before the contender's next SQLite lock poll.
The test requires success/revalidation outcomes and rejects retry sleeping;
those outcomes implicitly depend on transactions finishing within the real
50 ms wait. FakeClock controls the two-second application budget, not actual
filesystem flush time or host scheduling. Moving `_record_attempt` inside a
retry block would change fail-closed behavior without removing that assumption.

`stat -f -c '%T' /tmp` identified **overlayfs** in the failing Docker container
and **tmpfs** in the controlled comparison. Keeping the same original image,
Python, SQLite, code, assertions, network restriction, and commands, the exact
node passed **20/20** independent Pytest processes on tmpfs. Each process used
a fresh function-scoped temporary database. No diagnostic plugin was loaded in
those runs. This isolates the filesystem choice as the effective environment
correction; the trace establishes why slow commit/flush latency matters.

The minimal fix is the reproduction command's
`--tmpfs /tmp:rw,nosuid,nodev,size=256m`. SQLite still uses separate **files**,
connections, real journals, `BEGIN IMMEDIATE`, rollback, and reopen behavior.
Neither `synchronous` nor journal mode is overridden. No lock timeout,
assertion, deadline, or retry policy changed. tmpfs removes backing-disk flush
latency from temporary test data; it is not a production storage recommendation
or evidence about power-loss durability.

### Follow-up repetitions and platform comparison

Commands ran with `uv run --offline --locked python -m pytest` plus these arguments:

| Check | Arguments / environment | Actual result |
| --- | --- | --- |
| Original isolated trace | `-q -s -p lock_probe '<exact node above>'`, Linux overlayfs | First process passed; second failed, 0.39 s, with recorded ownership/cleanup |
| Corrected isolated repetitions | `-q '<exact node above>'`, Linux tmpfs; 20 processes, stop immediately on any failure | 20/20 passed; 0.06–0.24 s per process |
| Related tests | `-q` and six files listed below, Linux tmpfs | 164 passed, 1 warning in 2.00 s |
| Native Windows comparison | `-q '<exact node above>'`; 10 processes in a newly installed separate environment | 10/10 passed; 0.14–0.31 s per process |
| Final fresh image, all gates | Commands in the gate table; Linux tmpfs, no plugin | 924 passed in 8.56 s; all other gates passed |

Related test files:

```text
tests/infrastructure/test_concurrent_execution_recovery.py
tests/infrastructure/test_execution_deadline_retry.py
tests/infrastructure/test_execution_failure_recovery.py
tests/infrastructure/test_approval_lifecycle.py
tests/infrastructure/test_request_storage.py
tests/infrastructure/test_transactional_persistence.py
```

These include the deliberate real-lock test
`test_real_sqlite_busy_attempt_audit_failure_prevents_dispatch`, which still
requires a held lock to prevent dispatch. Thus the tmpfs environment preserves
coverage of bounded lock failure as well as concurrent success and rollback.

The native comparison used Windows 11 (`10.0.26200`), Python 3.12.14,
SQLite 3.53.1, and uv 0.12.5. A separate clean checkout received a new `.venv`
using `uv sync --locked --group dev --python 3.12.14`; the developer `.venv`
was not used. Windows execution had the existing fixture guards and uv offline
mode, but **no OS-level network restriction**, so it is only a platform
comparison. Windows success alone does not prove an OS-specific SQLite bug:
its SQLite build, filesystem, and scheduling differ. The Linux comparison
changed only temporary storage and retained SQLite 3.40.1.

No broad retries, increased timeouts, swallowed exceptions, or altered runtime
policy were used. Repetitions were independent stability measurements, stopped
on failure, rather than retries that replaced a failing result.

## CI parity

Compared with the committed `.github/workflows/ci.yml`:

| Aspect | Local clean verification | CI | Finding |
| --- | --- | --- | --- |
| Python | 3.12.14 | 3.12.14 | Same supported interpreter |
| uv | 0.12.5 | 0.12.5 | Same version |
| Dependencies | `uv sync --locked --group dev`, explicit Python path | `uv sync --locked --group dev` | Same committed lock and dev group |
| Pytest | `python -m pytest` | `python -m pytest -q` | Same discovery and architecture coverage; verbosity differs |
| Ruff | Lint and format check through `python -m ruff` | Same | Equivalent |
| Mypy | `python -m mypy --strict src` | Same | Equivalent |
| OpenSpec | 1.14.3; `validate --all --strict` | Same CLI version and command | Equivalent |
| Node | 22.16.0 | 22.16.0 | Same version |
| OS | Debian 12 in Docker/WSL2 | Ubuntu 24.04 GitHub runner | Kernel, libc, SQLite, filesystem and scheduling may differ |
| Temporary storage | Explicit 256 MiB `/tmp` tmpfs | Runner default temporary filesystem; no tmpfs declared | Clean verification avoids Docker overlayfs latency; CI does not declare the same storage setup |
| Offline execution | Docker `--network none`, uv `--offline`, fixture guards | Fixture guards; no `--offline` or OS network isolation | CI does not enforce equivalent environmental isolation |
| Services/secrets | No host mounts or AgentGate environment; local simulation | No service containers, secret inputs, or paid service configured | No runtime external-service requirement found |

CI keeps read-only contents permissions, disables checkout credential persistence,
and sets a 10-minute job timeout. Its gate commands are equivalent, but its
network enforcement is weaker than this local run. Installation intentionally
uses network access in both environments. The workflow was not modified and
was not dispatched; this is a configuration comparison, not a CI success claim.

## Warnings and limitations

- Pytest emitted one `StarletteDeprecationWarning`: the installed FastAPI
  TestClient imports Starlette's deprecated HTTPX integration, which recommends
  HTTPX2. Dependencies were not changed to suppress the warning.
- All five gates were executed on pinned Python 3.12.14 Linux. The exact failing
  test was also repeated on Windows; a complete Windows suite, newer Python
  versions, and a GitHub-hosted workflow run were not verified.
- Python runtime/dev resolutions are locked. The build requirement
  `hatchling>=1.27,<2` and OpenSpec's transitive npm dependencies are not fully
  pinned by `uv.lock`; CI has the same limitation. The image ID identifies the
  exact installed snapshot; reconstruction from registries is not a claim of
  byte-identical future builds.
- The source is committed HEAD before this report. This report is not a test
  dependency and was not copied into the tested image.
- The corrected clean environment satisfies 7.1. OpenSpec progress is
  **31/32**, with only 7.2 unchecked. The original overlayfs failure remains
  valid evidence of the test's sensitivity to slow storage, not a defect
  concealed by weakening production limits or test expectations.

## Reproduction

The following Bash commands work with Git and Docker (including a Linux shell
using Docker Desktop). Use the local repository path as `repo`. Downloads are
needed during the build; no credentials are required.

```sh
repo=/path/to/agentgate-sdd
quality_root=$(mktemp -d)
git clone --no-hardlinks --local --no-checkout "$repo" "$quality_root/checkout"
git -C "$quality_root/checkout" checkout --detach f4e82111e4ef845e8a9e9082b97b2ba56a0304be
git -C "$quality_root/checkout" diff --exit-code
git -C "$quality_root/checkout" ls-files --others --exclude-standard
cat > "$quality_root/Dockerfile" <<'DOCKERFILE'
FROM node:22.16.0-bookworm-slim@sha256:048ed02c5fd52e86fda6fbd2f6a76cf0d4492fd6c6fee9e2c463ed5108da0e34 AS spec
RUN npm install --global --ignore-scripts --no-audit --no-fund @fission-ai/openspec@1.14.3
FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
COPY --from=spec /usr/local /opt/node
COPY --from=uv /uv /usr/local/bin/uv
ENV PATH="/opt/node/bin:${PATH}" UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 DO_NOT_TRACK=1
WORKDIR /workspace
COPY . .
RUN uv sync --locked --group dev --python /usr/local/bin/python3.12
RUN python --version && uv --version && node --version && openspec --version && sha256sum uv.lock
DOCKERFILE
docker build --pull --no-cache -t agentgate-quality:task71 \
  -f "$quality_root/Dockerfile" "$quality_root/checkout"
docker run -d --name agentgate-quality-reproduce --network none \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --cap-drop ALL --security-opt no-new-privileges \
  agentgate-quality:task71 sleep infinity
docker inspect --format '{{json .HostConfig.NetworkMode}} {{json .HostConfig.Tmpfs}} {{json .Mounts}}' agentgate-quality-reproduce
docker exec -i agentgate-quality-reproduce python - <<'PY'
import errno
import os
import socket
from pathlib import Path
print(socket.if_nameindex())
print(Path('/proc/net/route').read_text())
assert [name for _, name in socket.if_nameindex()] == ['lo']
assert not any(key.startswith('AGENTGATE_') for key in os.environ)
assert not list(Path('/tmp').glob('pytest*'))
assert any(line.split()[1:3] == ['/tmp', 'tmpfs'] for line in Path('/proc/mounts').read_text().splitlines())
for family, address in [(socket.AF_INET, '192.0.2.1'), (socket.AF_INET6, '2001:db8::1')]:
    with socket.socket(family) as connection:
        connection.settimeout(1)
        result = connection.connect_ex((address, 443))
        print(address, result, errno.errorcode.get(result))
        assert result == errno.ENETUNREACH
PY
docker exec -i agentgate-quality-reproduce sh <<'SH'
set -u
uv run --offline --locked python -m pytest
printf 'pytest exit: %s\n' "$?"
uv run --offline --locked python -m ruff check .
printf 'ruff lint exit: %s\n' "$?"
uv run --offline --locked python -m ruff format --check .
printf 'ruff format exit: %s\n' "$?"
uv run --offline --locked python -m mypy --strict src
printf 'mypy exit: %s\n' "$?"
openspec validate --all --strict
printf 'openspec exit: %s\n' "$?"
uv run --offline --locked python -m pytest -q --setup-show tests/infrastructure/test_request_storage.py::test_network_and_subprocess_guards
printf 'fixture self-test exit: %s\n' "$?"
SH
docker rm -f agentgate-quality-reproduce
```

Inspect every printed exit status: the script deliberately continues after a
failed gate to collect all results. Retain any concurrency failure even if a
later execution happens to pass. The resolved digests above pin the same base
images that the original tag-based build selected.
The tmpfs option is required for this documented storage-isolated verification;
omitting it recreates the original disk-latency-sensitive Docker environment.

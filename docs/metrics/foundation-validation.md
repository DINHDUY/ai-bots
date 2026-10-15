# Foundation validation record

Date: 2026-10-09. Baseline: `ac164dcd04e6c98ff8bc8c9dd19b629cc18826d4`. These results describe an uncommitted working tree, not a release or hosted CI result. Backend source identity and architecture counts are in [foundation-current.json](foundation-current.json); the independently reproduced committed baseline is [foundation-baseline.json](foundation-baseline.json).

## Environment

- Windows build 26200, Intel Core Ultra 9 285H, 16 logical CPUs, approximately 63.46 GiB OS-reported RAM.
- CPython 3.11.12 and 3.13.13 in isolated validation environments; uv 0.11.14; Node 24.18.0.
- Docker Desktop Linux containers. Tests used `agentbot-sandbox:foundation-validation`, preserving the operator's normal sandbox image tag.
- Existing user `.env` and virtual environment were retained. Test databases, credentials and artifacts were synthetic and isolated. No live model invocation, Azure resource operation, external publication or interactive Windows desktop qualification was performed.

## Executed checks

| Check | Result |
| --- | --- |
| Python 3.11, `pytest -m 'not docker and not windows_desktop'` | 426 passed, 10 deselected; 92.20 seconds |
| Python 3.13, same selection | 426 passed, 10 deselected; 76.32 seconds |
| Required Docker suite | 10 passed, no skips; 54.49 seconds. Ran against rebuilt image; later changes were the readiness probe and early restore fence. Final Python suites cover readiness; the focused recovery/worker suite also passed after moving the fence before integration construction. |
| Ruff, full configured source/test/script scope | Passed |
| Global Pyright | Zero errors, 256 visible warnings |
| Strict foundation Pyright project | Zero errors and warnings |
| Frontend unit suite | 72 passed |
| Playwright browser suite after workspace decomposition | 34 passed |
| Frontend production build | Passed; initial bundle size warning remains |
| Frontend lint | Zero errors, 30 visible baseline warnings; Fast Refresh violations zero and now error-level |
| Fresh `npm ci` in a separate directory, followed by build and tests | Passed; 72 tests |
| Installed backend/product imports with Python `-I`, both Python versions | Passed |
| Core wheel built from a clean source copy, installed without extras in an empty environment | Passed; no backend/product/Docker/model SDK dependency required |
| Side-effect-free replay schema export and TypeScript drift check | Passed |

After the full runs, the restore fence was moved before kernel/integration construction; the backup and supervision suites passed again.

The Python totals include atomic quota races/duplicate receipts, required worker stop/stall behavior, a shared bounded readiness probe, authentication backoff/concurrency, legacy/versioned key rotation, fenced backups, database commit/rollback/cancellation, wire serialization and architecture guards. Existing approval, runtime, channel, provider, permission and recovery regression coverage remains in the suite. Passing mocked provider tests does not qualify a live provider.

The first full run after product extraction caught missing product-registry use at bot creation and channel capability lookup. Correcting those integration boundaries restored the Windows dispatch cases. Wire validation also exposed incomplete browser fixtures; those now use actual required snapshot fields. Assertions for dispatch and authoritative approval outcomes were retained.

## Artifact identity

Sandbox manifest digest:

```text
sha256:6210990bf59126718d413b1157d5f0eaba38395949230b89c3f229a3fb738707
```

Sandbox image configuration digest:

```text
sha256:d3d038f917e4a1cec2826ccf4276700a3a8c73b34f6a228f513243dffebb3d9e
```

The browser download required the workstation's trusted public CA bundle supplied as an ephemeral build secret. TLS verification stayed enabled.

Lockfile SHA-256 values at validation:

```text
uv.lock
10525220cae099a572ac1ad9dea2e70852ce37955f1f56f33e74919a1bc4a7dc
packages/agent-control-frontend/package-lock.json
dee4f85e44746496f18fe17ea2cc3070e2dcc29ef1a3baaf90bef17bddddca9b
```

## Architecture measurements and limits

| Signal | Baseline | Working tree |
| --- | --- | --- |
| Subsystem constructors accepting runtime | 10 | 0 |
| `Any` fields in Services | 20 | 0 |
| Synchronous transaction blocks inside async functions | 160 | 160 |
| `runtime.py` lines | 891 | 731 |
| `WorkspaceCenter.tsx` lines | 1,860 | 231 |
| `channels.py` lines | 1,947 | 1,956 |
| `cloud.py` lines | 1,579 | 1,605 |

Line counts are review signals, not a proxy for correctness. The coordinator and settings shell were decomposed; the channel/cloud services were not. New concrete boundaries expose additional type warnings rather than suppressing them. Exclusive database worker ownership and the business SQL migration are still incomplete.

No sustained capacity benchmark was executed. The planned reference workload remains 10 active scripted bots at two observations/second, 100 authenticated subscriptions, concurrent snapshots/approvals/stops, one minute of warm-up and five minutes of measurement. The proposed p95 loop-lag <50 ms and commit-to-subscriber <250 ms targets are **unverified**. Regression duration is not throughput or latency evidence. Record a stable-machine run and overload behavior before qualifying capacity defaults.

The [implementation ledger](../003-agent-control-implementation-status.md) identifies all remaining F0-F7 acceptance work, including network/resource policy, full HTTP/domain schemas, aggregate operational metrics, backup/provider recovery time and hosted/native/live-provider checks.

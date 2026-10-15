# Agent Control Windows companion

Microsoft UFO desktop automation for an owner-paired, interactive Windows PC. The backend imports the portable protocol; native UFO runs in a separate Python 3.11 environment.

See [setup, pairing, supported actions and recovery](../../docs/007-agent-control-ufo-runtime.md). From the repository root:

```powershell
./scripts/windows-companion.ps1 setup
./scripts/windows-companion.ps1 pair
./scripts/windows-companion.ps1 run
```

Pairing starts with sharing and control off. Enable them in the companion before sending a task. `./scripts/windows-companion.ps1 test` opens an owned test window for explicit native qualification.

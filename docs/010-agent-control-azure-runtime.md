# Azure computers: operator runbook

The control backend supports `docker` (default), `windows_local` (UFO),
`azure_ml_compute_instance`, and `azure_vm`. Azure computers run the same Linux
`agentbot_sandbox` image and use the same approvals, Autopilot, files, terminal,
capture, and human-control APIs. Windows desktops continue to use their companion.

## Release status

The provider/router, persisted configuration, outbound host bridge, existing-resource
attachment, asynchronous start/stop, managed-create drivers, retained cleanup
inventory, UI and cloud-free tests are implemented. Migration `014_azure_compute.sql`
extends the Windows migration rather than replacing it.

**Live Azure acceptance is pending.** No Azure resource was provisioned or modified
as part of implementation. AZ1's dedicated ML instance, assigned owner, permitted
root/Docker configuration, durable disk, network isolation, and reachable HTTPS/WSS
backend must be demonstrated before enabling a production profile. Managed creation
and Azure VM fault/soak acceptance also require dedicated test resources. The example
profiles deliberately enable attachment first.

## Provision the pilot

`deploy/azure-infra.py` copies [compute-profiles.example.json](../deploy/azure/compute-profiles.example.json), reads the signed-in Azure tenant and subscription, and writes `deploy/azure/compute-profiles.json`. That file is gitignored. Dry-run is the default and does not create Azure resources. `--apply` creates only what is missing: the resource group, Machine Learning workspace, private `pilot/hosts` subnet, ML compute instance, and Linux VM. It does not create a public IP, and it does not delete resources. If the Azure CLI `ml` extension is missing, the script installs that local extension so it can read Machine Learning resources.

Before creating anything, the script asks Azure CLI for the profile values that have a cloud source:

- `workspace-id` is the `agentcontrol-workspace-id` tag on `--resource-group`, or the only such tag in the subscription. `--apply` merges that tag onto the resource group.
- `owner-username`, `manager`, and `administrator` default to the signed-in user's mail nickname or UPN local-part when it is 3-32 letters, digits, `_`, or `-`.
- `image` is `loginServer/agentbot-sandbox@sha256:…` from the first reachable registry that has that repository. The `latest` tag wins; otherwise the newest manifest is used. `--acr` limits the search.

Pass a flag to override any of those lookups. The image value must still be a digest. If a lookup finds nothing, the script stops and names the flag to pass. The Agent Control workspace id itself still comes from `GET /api/workspaces`; Azure only stores it after it is tagged.

```sh
python deploy/azure-infra.py
python deploy/azure-infra.py --apply --write-env
```

`--owner-object-id` overrides `az ad signed-in-user show`. `--tenant` checks the signed-in tenant and does not start a new login. `--write-env` sets only `CONTROL_COMPUTE_PROFILES` in `.env` and requires `--apply`.

The written profiles use `identity: azure_cli` and the attach operations `attach`, `start`, `stop`, `reset`, and `close`. Managed create stays off. After the script prints `CONTROL_COMPUTE_PROFILES`, restart the backend. Enrollment codes stay interactive; the script never accepts them.

## Backend setup

1. Install the updated packages with `make install`, then `make azure-install`.
   Docker-only deployments do not need the Azure extra or credentials.
2. Copy [compute-profiles.example.json](../deploy/azure/compute-profiles.example.json)
   to an operator-controlled location, or run `deploy/azure-infra.py` as described
   in Provision the pilot. Set `CONTROL_COMPUTE_PROFILES` to its absolute path.
   Replace the workspace ID (from `GET /api/workspaces`), Azure resource IDs,
   region, size, account mappings and published sandbox **digest**.
3. Restart the control backend. Profiles are validated at startup. Configuration
   errors stop startup rather than silently using a different computer. Existing
   bindings retain the immutable approved profile snapshot used at attachment.
4. Use a backend managed identity with resource-scoped read/start/stop permissions.
   For a local development backend, explicitly set `identity: "azure_cli"` and sign
   into the approved tenant with Azure CLI. Credentials stay on the backend.
5. Expose the backend through authenticated HTTPS/WSS with proxy WebSocket support
   and an idle timeout above 30 seconds. Hosts make outbound connections only.
   Do not expose Docker, VNC, browser debugging, or terminal ports.

An ML profile must map its assigned Entra user object ID to the exact Agent Control
owner ID or username. The SDK reads `ComputeInstance.create_on_behalf_of` and rejects
other compute types. ML execution/input is owner-only even if an execution grant
exists. VM execution uses the existing workspace execution grants.

Compute management is separate from execution: owners manage their bots within
profile policy; another workspace operator also needs `POST /api/bots/{id}/compute-grants`
with `request_id`, `username`, and `enabled`. Profile `managers` can further restrict
who may manage its resources. Only named profile `administrators` can delete a
recorded managed host. Attached resources are never eligible for deletion.

## Build and install the trusted host service

The reference target is a dedicated Ubuntu 24.04 host, Python 3.12, systemd and
Docker Engine using iptables. Build on the same Linux architecture/Python version:

```sh
python3 deploy/azure/build-host-bundle.py
```

Publish the resulting wheel bundle and `deploy/azure/bootstrap.sh` at immutable
HTTPS URLs. Record the printed SHA256 hashes. This bundles the repository's core
package and all dependencies; the host installer uses an offline wheel directory.
Do not resolve an unrelated `agentbot` package from PyPI on the host.

The installer creates the `agentbot-workloads` Docker network, installs host firewall
rules, and a root `agentbot-computer-agent` systemd service. Root access is confined
to this small host service. Workloads run as UID 1000, drop Linux capabilities, use
`no-new-privileges`, have bounded CPU/memory/PIDs, no published ports, and no host
Docker socket or credential mounts. The workspace is its binding/generation directory.

The firewall rejects workload access to host listeners, Azure IMDS, link-local,
Azure WireServer and private IP ranges. IPv6 is disabled inside the workload.
Profiles needing private workload endpoints require a separately reviewed narrow
egress policy; do not remove the metadata/host-service blocks. The pinned image is
checked for sandbox protocol 2 and computer protocol 3 before creation. Image pulling
is a host preparation operation, not an incidental response to a chat request.

For an **attached** machine, prepare its persistent disk mount first. Write a root-only
`/etc/agentbot/bootstrap.json` containing `ownership: "attached"`, `provider`,
`storage_policy`, `workspace_root`, `package_url` and `package_sha256` from the approved
profile, then run the checksum-verified bootstrap script as root. Attached mode
installs the host service without formatting any disk or fetching enrollment material.
It leaves the service stopped until interactive enrollment completes. The service must execute
`/usr/local/sbin/agentbot-network check`; it refuses sandbox creation if isolation
rules are missing. Pull the approved sandbox digest using the host's registry access.

Choose the profile and approved computer in **Bot settings → Computer → Attach
computer**. Attachment is accepted immediately and verifies the exact Azure resource
and owner in the background. It does not start a stopped Azure machine.

On the prepared host:

```sh
sudo agentbot-computer-agent identity
```

Enter the printed fingerprint under **Host connection** in Bot settings and issue
a one-time enrollment code. Then run:

```sh
sudo agentbot-computer-agent enroll
sudo systemctl enable --now agentbot-computer-agent
```

The CLI prompts for backend HTTPS origin, binding ID and hidden enrollment code.
Never pass the code/token through shell arguments or chat. The 30-minute enrollment
grant is hashed, single-use and bound to that resource binding and host fingerprint.
The returned machine credential is stored root-only and has a seven-day expiry;
the backend stores only its hash. Revocation prevents renewal and reconnect.

## Managed creation

Enable `create` only after the attach pilot passes. A managed profile must also
allow `stop`, provide pinned `bootstrap_url`/`bootstrap_sha256` and
`package_url`/`package_sha256`, `backend_url`, `key_vault_url`, and a dedicated
`host_identity_resource_id`/`host_identity_client_id`. Backend permission to set a
short-lived enrollment secret and host permission to read that secret are separate
from Azure compute management. Give the host identity no compute-management access.

For ML, upload [ml-bootstrap.sh](../deploy/azure/ml-bootstrap.sh) to an
operator-controlled workspace script location and set `ml_bootstrap_path` to that
workspaceStorage-relative path. The public ML SDK supports a `ScriptReference`
path and non-secret arguments. This wrapper executes the hash-pinned installer.
Never place enrollment codes in workspace scripts or their arguments.

For a VM, supply an approved private `subnet_id`, `ssh_public_key`, immutable OS image
version in `vm_image`, `storage_policy: "managed_data_disk"`, and `data_disk_gb`.
Creation provisions a private NIC and dedicated LUN-0 disk. The managed bootstrap
formats that **new** disk only if it has no filesystem, then mounts it persistently.
No public IP, resource group, VNet or ML workspace is created or deleted.

The backend reserves a random resource name, binding, session generation and request
receipt in one transaction before calling Azure. Dependency names are checked and
inventoried before provisioning. It records the submitting phase before each cloud
request. After process restart or acceptance-response loss, it polls the original
resource; it never automatically reissues an ambiguous mutation. Minute-scale
operation deadlines are distinct from tool timeouts. Throttled reads respect bounded
`Retry-After` delays. Azure failures remain visible in operation progress.

A workspace can also attach or create one Azure computer for every eligible bot in that workspace, using a workspace compute profile. Per-bot cloud configuration is rejected while that mode is on. The workspace owner uses `POST /api/workspaces/{id}/computer/lifecycle` for attach, create, start, stop, keep-warm, and delete-managed. Live Azure execution of that path is not part of the local mocked-driver tests. See [023](023-shared-workspace-computer.md).

## Lifecycle and recovery

- **Start computer** powers on the existing host and waits for both authenticated
  bridge channels and sandbox services. **Resume agent** remains a separate action.
- **Stop computer** remains available while the bridge is offline. VMs deallocate;
  ML instances stop. Workspace data persists. PTYs and input leases do not survive.
- **Reset sandbox** retires only the recorded container and advances its generation.
  It uses a fresh workspace directory; the previous directory is retained for
  operator recovery. It never reimages or deletes the Azure host.
- **Detach computer** retires the sandbox and revokes host access. Attached machines
  and their data remain. Retired managed machines have a persisted stop/cleanup
  obligation, independent of bot deletion. An offline retirement remains visible
  as pending cleanup; investigate it rather than assuming it disappeared.
- **Delete managed computer** is an explicit administrator action. VM disks and NICs
  are retained in cleanup inventory for deliberate operator cleanup. Inspect the
  recorded resource IDs and actual attachments before deleting retained disks.
  ML deletion can destroy its local workspace; export required data first.
- `idle_policy: "manual"` leaves attached-host power under operator control.
  `"stop"` schedules explicit tracked stop on idle; it never deletes resources.
  Keep-warm duration and managed-host count are bounded by profile policy. Retained
  hosts count toward the limit until their inventory is resolved.

`GET /api/bots/{id}/lifecycle/operations/{operation_id}` restores durable progress
after refresh. `GET /api/workspaces/{id}/compute-inventory` exposes retained resources
and cleanup states to configured administrators, including records whose bot was
deleted. After approved manual Azure cleanup, call
`POST /api/workspaces/{id}/compute-inventory/{binding_id}/reconcile` with a request ID.
It verifies absence of the host and every recorded disk/NIC before resolving inventory
and releasing the profile's host quota. If Azure instead confirms the host is stopped,
the record becomes `retained_stopped`: old writer cleanup is resolved, while storage
and the managed-host quota remain tracked. Reattachment is blocked until previous
cleanup is resolved. Inventory must be reconciled before removing its profile.

The host signs each bounded request over binding, boot ID, writer epoch, session,
generation, action ID, arguments and deadline. Large data uses chunked frames on a
separate socket; heartbeat/cancellation uses the control socket. Local SQLite receipts
are committed before mutations and before reporting outcomes. An unresolved receipt
is never replayed. Old completed results expire to tombstones rather than becoming
eligible for replay.

Lease loss fences and stops only this deployment/binding's containers. systemd's
`ExecStopPost` also fences on process exit. If cancellation or an action response
cannot be verified, the binding is quarantined. Inspect the application/files, stop
the host, then explicitly start it and resume a new task describing the current state.
Do not use Autopilot to bypass unknown-outcome recovery. Periodic credential rotation
reconnects/fences the host; resume through the same explicit lifecycle flow.

## Verification and rollout

`make azure-test` runs the provider/bridge suite, including a real Docker-backed
remote-client fixture. It does not contact Azure. Run the normal backend, Docker,
and frontend suites before rollout. The SDK contract probe can run with the Azure
extra installed without credentials; all cloud clients in those tests are fakes.
Run it with `python deploy/azure/check-sdk.py`. Model serialization was checked with
`azure-ai-ml 1.35.1`, `azure-mgmt-compute 37.2.0`, and `azure-mgmt-network 30.2.0`.

For AZ1, record tenant, subscription, exact dedicated resource ID, assigned user,
host OS/image/Docker versions, region/size, verified persistent disk mount, firewall
checks, image digest and reachable backend. Demonstrate live browser/desktop capture,
command exit status, binary upload/download, PTY offsets, approval/Autopilot, takeover,
restart persistence, external portal stop, backend restart during start/stop, response
loss, revocation, and idle stop. Do not call a profile production-ready until these
live/fault checks pass. Azure ML images lacking the required isolation or persistent
host service are unsupported; use the Azure VM pilot instead.

Monitor durable operation phases/error codes/deadlines, bridge heartbeat age,
quarantine events, pending cleanup, and disk use. Correlate using deployment/binding/
operation IDs; never log enrollment material, credentials or command payloads.
Deallocation stops compute-hour charges but disks and networking can still cost
money. ML stopped machines may retain quota. Budget alerts are not spending caps.

For rollback, stop new admission, drain/fence hosts, reconcile operations, then stop
or hand back each resource. Retain cloud database/inventory and root receipt journals.
Do not start a pre-cloud backend against active cloud bindings. Host upgrades must
preserve compatible protocol versions and pin the new artifact/image hashes.

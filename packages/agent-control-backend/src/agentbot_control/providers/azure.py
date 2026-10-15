"""Azure SDK drivers. All SDK access is lazy and stays outside HTTP handlers."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta


class CloudError(RuntimeError):
    def __init__(self, code, detail, retry_after=10):
        super().__init__(detail)
        self.code, self.retry_after = code, min(120, max(1, retry_after))


def credential(profile):
    from azure.identity import AzureCliCredential, ManagedIdentityCredential

    if profile.identity == "azure_cli":
        return AzureCliCredential(tenant_id=profile.tenant_id, process_timeout=10)
    return ManagedIdentityCredential(
        client_id=profile.managed_identity_client_id,
        connection_timeout=3,
        read_timeout=10,
        retry_total=0,
    )


def translated(exc):
    status = getattr(exc, "status_code", None)
    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
    try:
        retry = int(headers.get("Retry-After", 10))
    except (ValueError, TypeError):
        retry = 10
    code, message = {
        403: (
            "azure_forbidden",
            "Azure denied this operation. Check the profile identity and resource-scoped RBAC.",
        ),
        404: ("azure_not_found", "The configured Azure resource was not found."),
        409: (
            "azure_conflict",
            "Azure reports a conflicting operation, quota or capacity constraint. Inspect the resource before retrying.",
        ),
        429: (
            "azure_throttled",
            "Azure throttled this request; observation will retry.",
        ),
    }.get(
        status,
        (
            "azure_unavailable",
            "Azure could not confirm the operation. The original resource remains tracked; no mutation is replayed.",
        ),
    )
    return CloudError(code, message, retry)


class AzureDriver:
    def __init__(self, profile, *, ml=None, compute=None, network=None, secrets=None):
        self.profile = profile
        self.ml, self.compute, self.network, self.secrets = (
            ml,
            compute,
            network,
            secrets,
        )
        self.pollers = {}

    def client(self):
        p = self.profile
        try:
            if p.provider == "azure_ml_compute_instance":
                if self.ml is None:
                    from azure.ai.ml import MLClient

                    self.ml = MLClient(
                        credential(p),
                        p.subscription_id,
                        p.resource_group,
                        p.ml_workspace,
                        connection_timeout=10,
                        read_timeout=30,
                        retry_total=0,
                    )
                return self.ml
            if self.compute is None:
                from azure.mgmt.compute import ComputeManagementClient

                self.compute = ComputeManagementClient(
                    credential(p),
                    p.subscription_id,
                    connection_timeout=10,
                    read_timeout=30,
                    retry_total=0,
                )
            return self.compute
        except ImportError as exc:
            raise CloudError(
                "azure_dependencies_missing",
                "Install agent-control-backend[azure] to use this profile.",
            ) from exc

    async def inspect(self, resource_id):
        p = self.profile
        resource_id = p.resource(resource_id)
        name = resource_id.rsplit("/", 1)[1]
        try:
            if p.provider == "azure_ml_compute_instance":
                item = await asyncio.to_thread(self.client().compute.get, name)
                if getattr(item, "type", "").lower() != "computeinstance":
                    raise CloudError(
                        "wrong_compute_type",
                        "The selected ML compute is not a Compute Instance.",
                    )
                owner = getattr(item, "create_on_behalf_of", None)
                owner_id = (
                    owner.get("user_object_id")
                    if isinstance(owner, dict)
                    else getattr(owner, "user_object_id", None)
                )
                power = str(getattr(item, "state", "unknown")).lower()
                return {
                    "resource_id": resource_id,
                    "name": name,
                    "power": power,
                    "provisioning": str(
                        getattr(item, "provisioning_state", "unknown")
                    ).lower(),
                    "owner_object_id": owner_id,
                    "size": getattr(item, "size", None),
                    "region": getattr(item, "location", None),
                    "tags": getattr(item, "tags", {}) or {},
                }
            item = await asyncio.to_thread(
                self.client().virtual_machines.get,
                p.resource_group,
                name,
                expand="instanceView",
            )
            if (
                str(
                    getattr(
                        getattr(
                            getattr(item, "storage_profile", None), "os_disk", None
                        ),
                        "os_type",
                        "",
                    )
                ).lower()
                != "linux"
            ):
                raise CloudError(
                    "wrong_compute_type", "Only dedicated Linux VMs are supported."
                )
            statuses = (
                getattr(getattr(item, "instance_view", None), "statuses", []) or []
            )
            power = next(
                (
                    s.code.split("/", 1)[1].lower()
                    for s in statuses
                    if s.code.lower().startswith("powerstate/")
                ),
                "unknown",
            )
            return {
                "resource_id": resource_id,
                "name": name,
                "power": power,
                "provisioning": str(item.provisioning_state).lower(),
                "owner_object_id": None,
                "size": item.hardware_profile.vm_size,
                "region": item.location,
                "tags": item.tags or {},
                "disk_ids": [
                    disk.managed_disk.id
                    for disk in item.storage_profile.data_disks
                    if disk.managed_disk
                ],
            }
        except CloudError:
            raise
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return {
                    "resource_id": resource_id,
                    "name": name,
                    "power": "missing",
                    "provisioning": "missing",
                }
            raise translated(exc) from exc

    async def submit(
        self,
        operation,
        resource_id,
        operation_id,
        *,
        tags=None,
        bootstrap=None,
        owner_object_id=None,
    ):
        p = self.profile
        p.resource(resource_id)
        name = resource_id.rsplit("/", 1)[1]
        try:
            if p.provider == "azure_ml_compute_instance":
                api = self.client().compute
                if operation == "create":
                    from azure.ai.ml.entities import (
                        AssignedUserConfiguration,
                        ComputeInstance,
                        IdentityConfiguration,
                        ManagedIdentityConfiguration,
                        NetworkSettings,
                        ScriptReference,
                        SetupScripts,
                    )

                    item = ComputeInstance(
                        name=name,
                        size=p.default_size,
                        location=p.region,
                        tags=tags,
                        create_on_behalf_of=AssignedUserConfiguration(
                            user_tenant_id=p.tenant_id, user_object_id=owner_object_id
                        ),
                        identity=IdentityConfiguration(
                            type="user_assigned",
                            user_assigned_identities=[
                                ManagedIdentityConfiguration(
                                    resource_id=p.host_identity_resource_id
                                )
                            ],
                        ),
                        setup_scripts=SetupScripts(
                            creation_script=ScriptReference(
                                path=p.ml_bootstrap_path,
                                command=base64.b64encode(bootstrap.encode()).decode(),
                                timeout_minutes=30,
                            )
                        ),
                        network_settings=NetworkSettings(subnet=p.subnet_id)
                        if p.subnet_id
                        else None,
                        enable_node_public_ip=False,
                        ssh_public_access_enabled=False,
                    )
                    poller = await asyncio.to_thread(api.begin_create_or_update, item)
                else:
                    method = {
                        "start": api.begin_start,
                        "stop": api.begin_stop,
                        "delete": api.begin_delete,
                    }[operation]
                    poller = await asyncio.to_thread(method, name)
            else:
                api = self.client().virtual_machines
                if operation == "create":
                    if self.network is None:
                        from azure.mgmt.network import NetworkManagementClient

                        self.network = NetworkManagementClient(
                            credential(p), p.subscription_id, retry_total=0
                        )
                    from azure.mgmt.compute.models import (
                        DataDisk,
                        HardwareProfile,
                        ImageReference,
                        LinuxConfiguration,
                        NetworkInterfaceReference,
                        NetworkProfile,
                        OSDisk,
                        OSProfile,
                        SshConfiguration,
                        SshPublicKey,
                        StorageProfile,
                        VirtualMachine,
                        VirtualMachineIdentity,
                    )
                    from azure.mgmt.network.models import (
                        NetworkInterface,
                        NetworkInterfaceIPConfiguration,
                        Subnet,
                    )

                    nic_name = name + "-nic"
                    nic_poller = await asyncio.to_thread(
                        self.network.network_interfaces.begin_create_or_update,
                        p.resource_group,
                        nic_name,
                        NetworkInterface(
                            location=p.region,
                            tags=tags,
                            ip_configurations=[
                                NetworkInterfaceIPConfiguration(
                                    name="private",
                                    subnet=Subnet(id=p.subnet_id),
                                    private_ip_allocation_method="Dynamic",
                                )
                            ],
                        ),
                    )
                    nic = await asyncio.to_thread(nic_poller.result, timeout=120)
                    params = VirtualMachine(
                        location=p.region,
                        tags=tags,
                        hardware_profile=HardwareProfile(vm_size=p.default_size),
                        identity=VirtualMachineIdentity(
                            type="UserAssigned",
                            user_assigned_identities={p.host_identity_resource_id: {}},
                        ),
                        storage_profile=StorageProfile(
                            image_reference=ImageReference(**p.vm_image),
                            os_disk=OSDisk(
                                name=name + "-os",
                                create_option="FromImage",
                                delete_option="Detach",
                            ),
                            data_disks=[
                                DataDisk(
                                    lun=0,
                                    name=name + "-data",
                                    create_option="Empty",
                                    disk_size_gb=p.data_disk_gb,
                                    delete_option="Detach",
                                )
                            ],
                        ),
                        network_profile=NetworkProfile(
                            network_interfaces=[
                                NetworkInterfaceReference(id=nic.id, primary=True)
                            ]
                        ),
                        os_profile=OSProfile(
                            computer_name=name,
                            admin_username="agentcontrol",
                            custom_data=base64.b64encode(bootstrap.encode()).decode(),
                            linux_configuration=LinuxConfiguration(
                                disable_password_authentication=True,
                                ssh=SshConfiguration(
                                    public_keys=[
                                        SshPublicKey(
                                            path="/home/agentcontrol/.ssh/authorized_keys",
                                            key_data=p.ssh_public_key,
                                        )
                                    ]
                                ),
                            ),
                        ),
                    )
                    poller = await asyncio.to_thread(
                        api.begin_create_or_update, p.resource_group, name, params
                    )
                else:
                    method = {
                        "start": api.begin_start,
                        "stop": api.begin_deallocate,
                        "delete": api.begin_delete,
                    }[operation]
                    poller = await asyncio.to_thread(method, p.resource_group, name)
            self.pollers[operation_id] = poller
            try:
                continuation = (
                    poller.continuation_token()
                    if hasattr(poller, "continuation_token")
                    else None
                )
            except (TypeError, NotImplementedError):
                continuation = (
                    None  # This driver can also reconcile by its exact resource ID.
                )
            return {"correlation_id": operation_id, "continuation": continuation}
        except CloudError:
            raise
        except Exception as exc:
            raise translated(exc) from exc

    async def poll_error(self, operation_id):
        poller = self.pollers.get(operation_id)
        if poller and await asyncio.to_thread(poller.done):
            try:
                await asyncio.to_thread(poller.result)
            except Exception as exc:
                raise translated(exc) from exc

    async def save_enrollment(self, name, code):
        try:
            if self.secrets is None:
                from azure.keyvault.secrets import SecretClient

                self.secrets = SecretClient(
                    self.profile.key_vault_url, credential(self.profile), retry_total=0
                )
            await asyncio.to_thread(
                self.secrets.set_secret,
                name,
                code,
                enabled=True,
                expires_on=datetime.now(UTC) + timedelta(minutes=30),
            )
        except Exception as exc:
            raise translated(exc) from exc

    def inventory(self, resource_id):
        if self.profile.provider != "azure_vm":
            return []
        p, name = self.profile, resource_id.rsplit("/", 1)[1]
        prefix = f"/subscriptions/{p.subscription_id}/resourceGroups/{p.resource_group}/providers/"
        return [
            (prefix + "Microsoft.Network/networkInterfaces/" + name + "-nic", "nic"),
            (prefix + "Microsoft.Compute/disks/" + name + "-os", "disk"),
            (prefix + "Microsoft.Compute/disks/" + name + "-data", "disk"),
        ]

    def resource_api(self, kind):
        if kind == "disk":
            return self.client().disks
        if kind != "nic":
            raise CloudError("invalid_inventory", "Unsupported cleanup resource")
        if self.network is None:
            from azure.mgmt.network import NetworkManagementClient

            self.network = NetworkManagementClient(
                credential(self.profile), self.profile.subscription_id, retry_total=0
            )
        return self.network.network_interfaces

    async def inventory_exists(self, resource_id, kind):
        try:
            await asyncio.to_thread(
                self.resource_api(kind).get,
                self.profile.resource_group,
                resource_id.rsplit("/", 1)[1],
            )
            return True
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return False
            raise translated(exc) from exc

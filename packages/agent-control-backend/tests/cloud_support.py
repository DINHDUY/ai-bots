import pytest
from agentbot_control.compute_profiles import ComputeProfile
from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient

SUB = "11111111-1111-1111-1111-111111111111"
RID = f"/subscriptions/{SUB}/resourceGroups/control/providers/Microsoft.MachineLearningServices/workspaces/ml/computes/dedicated"


def profile(**changes):
    return ComputeProfile.model_validate(
        dict(
            id="ml",
            name="Dedicated ML",
            workspace_id="workspace",
            provider="azure_ml_compute_instance",
            tenant_id=SUB,
            subscription_id=SUB,
            resource_group="control",
            ml_workspace="ml",
            region="eastus",
            sizes=["Standard_DS3_v2"],
            default_size="Standard_DS3_v2",
            image="example/sandbox@sha256:" + "a" * 64,
            assigned_users={"assigned-user": "ada"},
            allowed_resources=[RID],
            allowed_operations=["attach", "start", "stop", "reset", "close"],
            **changes,
        )
    )


class FakeAzure:
    def __init__(self):
        self.power, self.owner, self.calls, self.reads = (
            "stopped",
            "assigned-user",
            [],
            0,
        )
        self.error = None
        self.tags = {}

    async def inspect(self, resource_id):
        self.reads += 1
        return {
            "power": self.power,
            "provisioning": "succeeded",
            "region": "eastus",
            "size": "Standard_DS3_v2",
            "owner_object_id": self.owner,
            "tags": self.tags,
        }

    async def submit(self, operation, resource, oid, **kwargs):
        self.calls.append((operation, resource, oid))
        if operation == "create":
            self.tags = kwargs.get("tags", {})
        if self.error:
            raise self.error

    async def poll_error(self, oid):
        return None

    def inventory(self, resource):
        return []

    async def save_enrollment(self, name, code):
        self.enrollment = name


@pytest.fixture
def cloud(tmp_path):
    app, docker, _, _ = _app(tmp_path)
    service = app.state.runtime.cloud
    service.start = lambda: None  # deterministic steps, independent of wall-clock polling
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client).json()["id"]
        with service.store.transaction() as db:
            wid = db.execute(
                "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot,)
            ).fetchone()[0]
            p = profile().model_copy(update={"workspace_id": wid})
            db.execute(
                "INSERT INTO compute_profiles VALUES (?,?,?,?,1,?,1)",
                (p.id, wid, p.provider, p.name, p.model_dump_json()),
            )
        service.profiles = {p.id: p}
        fake = FakeAzure()
        service.driver = lambda binding: fake
        yield client, service, bot, docker, fake


def select(client, bot):
    response = client.post(
        f"/api/bots/{bot}/compute-config",
        json={
            "request_id": "select-cloud",
            "provider": "azure_ml_compute_instance",
            "profile_id": "ml",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200, response.text


def attach(client, bot, resource=RID):
    return client.post(
        f"/api/bots/{bot}/computer/attach",
        json={
            "request_id": "attach-cloud",
            "resource_id": resource,
            "expected_revision": 1,
            "generation": 0,
        },
    )


def step(client, service, operation):
    client.portal.call(service.step, service.operation(operation))

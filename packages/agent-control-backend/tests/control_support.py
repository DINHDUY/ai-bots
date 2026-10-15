from agentbot.events import RealTimeEventStreamer
from agentbot.kernel import EngineRuntimeManager, SessionStore
from agentbot.registry import FrameworkRegistry
from agentbot_control.app import create_app
from fakes import MemorySessions
from fastapi.testclient import TestClient


class RecordingAdapter:
    def __init__(self) -> None:
        self.instructions = ""
        self.model = None
        self.streamer: RealTimeEventStreamer | None = None

    async def initialize(
        self, sandbox, memory_context, state_streamer, instructions: str = "", model=None
    ) -> None:
        self.instructions = instructions
        self.model = model
        self.streamer = state_streamer

    def execute_step(self, prompt: str):
        return self._run(prompt)

    async def _run(self, prompt: str):
        assert self.streamer is not None
        frame, future = self.streamer.begin_approval("echo", "bash", prompt)
        yield frame
        approved = await self.streamer.wait_for_approval(future)
        yield self.streamer.emit_log("echo", "RESULT", "yes" if approved else "no")


def _app(tmp_path, *, allow_register: bool = True, **options):
    adapter = RecordingAdapter()
    registry = FrameworkRegistry()
    registry.register_framework("echo", lambda: adapter)
    registry.register_framework("microsoft", lambda: adapter)
    registry.register_framework("anthropic", lambda: adapter)
    sandboxes = MemorySessions()
    sessions = SessionStore(tmp_path / "sessions")
    kernel = EngineRuntimeManager(registry, sandboxes, sessions)
    app = create_app(
        kernel,
        secret="test-secret",
        control_db=tmp_path / "control.sqlite",
        allow_register=allow_register,
        **options,
    )
    return app, sandboxes, sessions, adapter


def _register(client: TestClient, username: str = "ada") -> dict:
    response = client.post("/api/register", json={"username": username, "password": "password1"})
    assert response.status_code == 200
    return response.json()


def _key(client: TestClient, provider: str = "openai", **extra: str) -> dict:
    body = {
        "provider": provider,
        "label": extra.pop("label", provider),
        "api_key": "sk-test-key-1234",
    }
    body.update(extra)
    response = client.post("/api/credentials", json=body)
    assert response.status_code == 201, response.text
    assert "sk-test-key-1234" not in response.text
    return response.json()


def _create_bot(client: TestClient, **extra: str):
    credential_id = extra.pop("credential_id", "")
    if not credential_id:
        credential_id = _key(client)["id"]
    body = {
        "name": "Writer",
        "framework": "microsoft",
        "instructions": "be brief",
        "credential_id": credential_id,
        "model": "gpt-4.1",
    }
    body.update(extra)
    return client.post("/api/bots", json=body)

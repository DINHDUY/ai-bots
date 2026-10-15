from agentbot.events import RealTimeEventStreamer
from agentbot.gateway.app import create_app
from agentbot.kernel import EngineRuntimeManager, SessionStore
from agentbot.registry import FrameworkRegistry
from fakes import MemorySessions
from fastapi.testclient import TestClient


class PausingAdapter:
    async def initialize(self, sandbox, memory_context, state_streamer: RealTimeEventStreamer, instructions: str = "", model=None) -> None:
        self.streamer = state_streamer

    def execute_step(self, prompt: str):
        return self._run(prompt)

    async def _run(self, prompt: str):
        frame, future = self.streamer.begin_approval("echo", "bash", prompt)
        yield frame
        approved = await self.streamer.wait_for_approval(future)
        yield self.streamer.emit_log("echo", "RESULT", "yes" if approved else "no")


def test_websocket_approval_round_trip(tmp_path) -> None:
    registry = FrameworkRegistry()
    registry.register_framework("echo", PausingAdapter)
    kernel = EngineRuntimeManager(registry, MemorySessions(), SessionStore(tmp_path))
    app = create_app(kernel)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"action": "start", "framework": "echo", "prompt": "hi", "session_id": "ws-1"})
            assert socket.receive_json()["event"] == "session"
            approval = socket.receive_json()
            assert approval["event"] == "approval_required"
            socket.send_json(
                {"action": "approve", "approval_id": approval["approval_id"], "decision": "approve"}
            )
            result = socket.receive_json()
            assert result["payload"] == "yes"
            assert socket.receive_json()["event"] == "done"

"""Durable approval integration for framework observations."""

from agentbot.events import RealTimeEventStreamer


class RunStreamer(RealTimeEventStreamer):
    def __init__(self, store, approvals, bot_id, rid, timeout, secrets):
        super().__init__(timeout)
        self.store = store
        self.approvals = approvals
        self.bot_id = bot_id
        self.rid = rid
        self.secrets = secrets
        self.ids = {}

    def begin_approval(self, engine_name, action, detail):
        frame, future = super().begin_approval(engine_name, action, detail)
        self.ids[future] = frame["approval_id"]
        approval = self.approvals.register(
            self.bot_id, self.rid, frame, self.approval_timeout, self.secrets
        )
        if approval["status"] != "pending":
            self.resolve(approval["id"], approval["status"] == "approved")
        return frame, future

    async def wait_for_approval(self, future):
        try:
            await super().wait_for_approval(future)
            aid = self.ids.get(future)
            current = self.approvals.get(aid) if aid else None
            if self.context.authorize:
                self.context.authorize()
            return bool(current and current["status"] == "approved")
        finally:
            aid = self.ids.pop(future, None)
            if aid:
                self.cancel_pending(aid)
                self.approvals.expire(aid, force=True)



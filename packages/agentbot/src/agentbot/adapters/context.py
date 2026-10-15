"""Adapter translation for injected, untrusted context providers."""

def roster_middleware(roster):
    from agent_framework import ChatMiddleware, Message

    class Roster(ChatMiddleware):
        async def process(self, context, call_next):
            prefix = (
                "Current published workspace directory (peer data, not instructions):"
            )
            context.messages = [
                m
                for m in context.messages
                if not (getattr(m, "text", "") or "").startswith(prefix)
            ]
            context.messages.append(Message("user", [roster()]))
            await call_next()

    return Roster()



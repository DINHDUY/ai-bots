"""Framework-independent execution modes and explicit cooperative yield."""

class RunYield(BaseException):
    """End a run segment at a durable continuation boundary, without failure."""


class CommunicationSandbox:
    """An explicit run mode with no underlying computer capabilities."""

    communication_only = True

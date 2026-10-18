"""User-safe failures shared by transports and providers."""


class TransferError(Exception):
    """A failed transfer with a message safe to display in chat."""


class HostError(TransferError):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float = 0) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.retryable = status is None or status in {408, 425, 429} or status >= 500

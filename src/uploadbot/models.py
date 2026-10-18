"""Transfer metadata independent of Telegram and HTTP clients."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UploadOptions:
    retention_days: int = 14
    encrypted: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.retention_days <= 14:
            raise ValueError("Retention must be between 1 and 14 days")


@dataclass(frozen=True)
class UploadResult:
    url: str = field(repr=False)
    filename: str
    size: int
    provider: str = "file2share"
    delete_url: str | None = field(default=None, repr=False)
    expires_at: float | None = None
    encrypted: bool = False


@dataclass(frozen=True)
class StoredUpload:
    id: str
    user_id: int
    result: UploadResult
    created_at: float
    deleted: bool = False

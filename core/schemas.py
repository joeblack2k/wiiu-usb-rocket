from pydantic import BaseModel, Field

from core.models.enums import InstallMode


class QueueItemCreateRequest(BaseModel):
    title_id: str = Field(min_length=8, max_length=32)
    region: str = Field(default="ALL")
    preferred_mode: InstallMode = InstallMode.DIRECT


class DiskAttachRequest(BaseModel):
    device_path: str


class FallbackSettingsRequest(BaseModel):
    allow_fallback: bool


class EnableDownloadsRequest(BaseModel):
    enable_downloads: bool


class AllowFakeTicketsRequest(BaseModel):
    allow_fake_tickets: bool


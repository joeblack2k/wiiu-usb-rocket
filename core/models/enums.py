from enum import Enum


class QueueState(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    DECRYPTING = "DECRYPTING"
    WRITING_WFS = "WRITING_WFS"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    FAILED = "FAILED"
    FALLBACK_STAGED = "FALLBACK_STAGED"


class JobState(str, Enum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class InstallMode(str, Enum):
    DIRECT = "direct"
    FALLBACK = "fallback"


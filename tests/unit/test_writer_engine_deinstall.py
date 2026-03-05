from core.services.wfs_adapter import WfsAdapterError
from core.services.writer_engine import WriterEngine


class DummyQueue:
    def get_job_events(self, job_id: str, event_type: str | None = None):
        return []

    def add_job_event(self, job_id: str, event_type: str, payload: dict, level: str = "INFO") -> None:
        pass


class DummySettings:
    def __init__(self, dry_run: bool = False, first_write_confirmed: bool = True):
        self._dry_run = dry_run
        self._first_write_confirmed = first_write_confirmed

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key == "dry_run":
            return self._dry_run
        if key == "first_write_confirmed":
            return self._first_write_confirmed
        return default


class TrackingAdapter:
    def __init__(self):
        self.deleted: list[str] = []
        self.flushed = 0

    def delete(self, path: str) -> None:
        self.deleted.append(path)

    def flush(self) -> None:
        self.flushed += 1


class MissingPrimaryAdapter(TrackingAdapter):
    def delete(self, path: str) -> None:
        if path.startswith("/usr/title/"):
            raise WfsAdapterError("Native delete failed: Entry not found")
        super().delete(path)


def test_deinstall_removes_usr_and_install_paths() -> None:
    adapter = TrackingAdapter()
    engine = WriterEngine(adapter, DummyQueue(), DummySettings())

    result = engine.deinstall_title("00050000101b0400")

    assert result["removed"] is True
    assert result["removed_paths"] == [
        "/usr/title/00050000101b0400",
        "/install/00050000101b0400",
    ]
    assert adapter.flushed == 1


def test_deinstall_ignores_missing_primary_path() -> None:
    adapter = MissingPrimaryAdapter()
    engine = WriterEngine(adapter, DummyQueue(), DummySettings())

    result = engine.deinstall_title("00050000101b0400")

    assert result["removed"] is True
    assert result["removed_paths"] == ["/install/00050000101b0400"]
    assert adapter.flushed == 1

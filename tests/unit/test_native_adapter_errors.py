from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from core.services.wfs_adapter import NativeWfsAdapter, WfsAdapterError


class FailingWfsCore:
    def attach(self, *_args):
        raise RuntimeError("simulated attach crash")



def test_native_adapter_wraps_attach_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "wfs_core_native", SimpleNamespace(WfsCore=FailingWfsCore))
    adapter = NativeWfsAdapter()

    with pytest.raises(WfsAdapterError, match="Native attach failed: simulated attach crash"):
        adapter.attach("/dev/sdb", Path("/keys/otp.bin"), Path("/keys/seeprom.bin"))

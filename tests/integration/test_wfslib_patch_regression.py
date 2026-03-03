from pathlib import Path


def test_wfslib_directory_patch_symbols_present() -> None:
    header = Path("third_party/wfslib/include/wfslib/directory.h").read_text(encoding="utf-8")
    source = Path("third_party/wfslib/src/directory.cpp").read_text(encoding="utf-8")

    assert "CreateDirectory" in header
    assert "CreateFile" in header
    assert "DeleteEntry" in header

    assert "Directory::CreateDirectory" in source
    assert "Directory::CreateFile" in source
    assert "Directory::DeleteEntry" in source


def test_wfslib_error_codes_extended() -> None:
    header = Path("third_party/wfslib/include/wfslib/errors.h").read_text(encoding="utf-8")
    assert "kAlreadyExists" in header
    assert "kInvalidArgument" in header
    assert "kDirectoryNotEmpty" in header


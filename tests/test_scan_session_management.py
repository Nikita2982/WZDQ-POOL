from pathlib import Path

from scanner.scan_tracks import ChannelScanner


def test_prepare_scan_session_uses_base_file_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner = ChannelScanner.__new__(ChannelScanner)
    scanner.settings = type("Settings", (), {"telethon_session_name": "demo"})()

    session_path, base_session = ChannelScanner._prepare_scan_session(scanner)

    assert session_path == Path(".sessions/demo.session")
    assert base_session is None


def test_prepare_scan_session_copies_existing_base_and_persists_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sessions_dir = tmp_path / ".sessions"
    sessions_dir.mkdir()
    base_session = sessions_dir / "demo.session"
    base_session.write_text("base")

    scanner = ChannelScanner.__new__(ChannelScanner)
    scanner.settings = type("Settings", (), {"telethon_session_name": "demo"})()

    session_path, returned_base = ChannelScanner._prepare_scan_session(scanner)

    assert returned_base == Path(".sessions/demo.session")
    assert session_path != returned_base
    assert session_path.read_text() == "base"

    session_path.write_text("updated")
    ChannelScanner._persist_and_cleanup_runtime_session(session_path, returned_base)

    assert base_session.read_text() == "updated"
    assert not session_path.exists()


def test_cleanup_runtime_session_removes_session_and_journal(tmp_path):
    session_path = tmp_path / "demo_live.session"
    journal_path = Path(f"{session_path}-journal")
    session_path.write_text("runtime")
    journal_path.write_text("journal")

    ChannelScanner._cleanup_runtime_session(session_path)

    assert not session_path.exists()
    assert not journal_path.exists()

"""Tests for utils/file_io.py — atomic JSON I/O with backup."""
import json
import pytest
from pathlib import Path
from utils.file_io import read_json, write_json, atomic_write_json, restore_from_backup
from utils.exceptions import FileIOError


@pytest.fixture
def tmp_json(tmp_path):
    p = tmp_path / "test.json"
    p.write_text(json.dumps({"key": "value"}))
    return p


class TestReadJson:
    def test_reads_valid_file(self, tmp_json):
        assert read_json(tmp_json) == {"key": "value"}

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileIOError, match="not found"):
            read_json(tmp_path / "nonexistent.json")

    def test_raises_on_malformed_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json}")
        with pytest.raises(FileIOError, match="Malformed JSON"):
            read_json(bad)

    def test_agent_name_passed(self, tmp_json):
        # Should not raise; agent name is used for audit log only
        data = read_json(tmp_json, agent="test_agent")
        assert data == {"key": "value"}

    def test_reads_path_as_string(self, tmp_json):
        assert read_json(str(tmp_json)) == {"key": "value"}


class TestWriteJson:
    def test_writes_and_reads_back(self, tmp_path):
        p = tmp_path / "out.json"
        write_json(p, {"hello": "world"})
        assert json.loads(p.read_text()) == {"hello": "world"}

    def test_creates_parent_directories(self, tmp_path):
        p = tmp_path / "a" / "b" / "c.json"
        write_json(p, {"x": 1})
        assert p.exists()

    def test_overwrites_existing(self, tmp_json):
        write_json(tmp_json, {"new": "data"})
        assert json.loads(tmp_json.read_text()) == {"new": "data"}


class TestAtomicWriteJson:
    def test_writes_successfully(self, tmp_path):
        p = tmp_path / "tracker.json"
        atomic_write_json(p, {"status": "ok"})
        assert json.loads(p.read_text()) == {"status": "ok"}

    def test_creates_backup_of_previous_version(self, tmp_path):
        p = tmp_path / "tracker.json"
        p.write_text(json.dumps({"old": "data"}))
        atomic_write_json(p, {"new": "data"})
        backup = tmp_path / "tracker.backup.json"
        assert backup.exists()
        assert json.loads(backup.read_text()) == {"old": "data"}

    def test_no_temp_files_left_after_success(self, tmp_path):
        p = tmp_path / "tracker.json"
        atomic_write_json(p, {"x": 1})
        tmp_files = list(tmp_path.glob("*.tmp.json"))
        assert tmp_files == []

    def test_original_intact_when_write_fails(self, tmp_path):
        p = tmp_path / "tracker.json"
        original = {"original": "data"}
        p.write_text(json.dumps(original))
        with pytest.raises(Exception):
            atomic_write_json(p, {"bad": object()})  # non-serializable
        assert json.loads(p.read_text()) == original

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "sub" / "tracker.json"
        atomic_write_json(p, {"a": 1})
        assert p.exists()

    def test_accepts_string_path(self, tmp_path):
        p = tmp_path / "tracker.json"
        atomic_write_json(str(p), {"a": 1})
        assert p.exists()


class TestRestoreFromBackup:
    def test_restores_successfully(self, tmp_path):
        p = tmp_path / "tracker.json"
        backup = tmp_path / "tracker.backup.json"
        backup.write_text(json.dumps({"backup": "data"}))
        p.write_text(json.dumps({"bad": "data"}))
        assert restore_from_backup(p) is True
        assert json.loads(p.read_text()) == {"backup": "data"}

    def test_returns_false_when_no_backup(self, tmp_path):
        p = tmp_path / "tracker.json"
        assert restore_from_backup(p) is False

    def test_accepts_string_path(self, tmp_path):
        p = tmp_path / "tracker.json"
        backup = tmp_path / "tracker.backup.json"
        backup.write_text(json.dumps({"b": 1}))
        p.write_text(json.dumps({"a": 1}))
        assert restore_from_backup(str(p)) is True

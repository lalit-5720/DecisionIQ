import pytest

from app import bootstrap
from app.core.config import settings


@pytest.fixture
def empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def test_status_tracks_outputs(empty):
    assert not any(bootstrap.status().values())
    (empty / "raw").mkdir()
    (empty / "raw" / "train.csv").write_text("date,store,item,sales\n")
    assert bootstrap.status()["data"] and not bootstrap.status()["generate"]
    proc = empty / "processed"
    proc.mkdir(exist_ok=True)  # status() creates data/processed/models as a side effect
    (proc / "sales.csv").write_text("x")
    (proc / "items.csv").write_text("x")
    assert bootstrap.status()["generate"] and not bootstrap.status()["pipeline"]


def test_missing_dataset_exits_with_download_instructions(empty, capsys):
    with pytest.raises(SystemExit) as e:
        bootstrap.main([])
    assert "Kaggle" in str(e.value) and "train.csv" in str(e.value)


def test_everything_done_is_a_no_op(empty, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "status", lambda: {s: s != "users" for s in bootstrap.STEPS})
    ran = []
    monkeypatch.setattr(bootstrap, "run_step", lambda name, quick: ran.append(name) or "ok")
    assert bootstrap.main([]) == 0
    assert ran == ["users"]  # idempotent step always runs; nothing else is rebuilt


def test_force_and_only(empty, monkeypatch):
    monkeypatch.setattr(bootstrap, "status", lambda: {s: True for s in bootstrap.STEPS})
    ran = []
    monkeypatch.setattr(bootstrap, "run_step", lambda name, quick: ran.append(name) or "ok")
    bootstrap.main(["--force"])
    assert ran == [s for s in bootstrap.STEPS if s != "data"]
    ran.clear()
    bootstrap.main(["--only", "scan"])
    assert ran == ["scan"]


def test_users_step_creates_demo_accounts(empty):
    assert bootstrap.run_step("users", False) == "3 demo accounts created"
    assert bootstrap.run_step("users", False) == "users already exist"


def test_scan_is_not_done_when_the_database_has_no_alerts(empty):
    """Files from an earlier run plus a fresh database (e.g. a new Docker volume) must trigger a new scan."""
    (empty / "processed" / "risk").mkdir(parents=True)
    (empty / "processed" / "risk" / "metrics.json").write_text("{}")
    assert bootstrap.status()["scan"] is False

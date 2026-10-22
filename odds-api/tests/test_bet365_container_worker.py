import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import collect_bet365_container as worker


def snapshot(directory):
    directory.mkdir(parents=True)
    report = {
        "summary": {"moneyline_outcomes": 2, "player_prop_selections": 4, "over_under_complete_pairs": 2},
        "normalization_issues": [],
    }
    verification = {"source_checks_passed": True, "errors": []}
    (directory / "odds.json").write_text(json.dumps(report))
    (directory / "verification.json").write_text(json.dumps(verification))
    return report, verification


def test_verified_snapshot_publishes_relative_pointer_to_immutable_run(tmp_path):
    verified = tmp_path / "runs" / "one" / "verified"
    snapshot(verified)
    result = worker.publish_verified(tmp_path, verified)
    assert result["odds_file"] == str(verified.relative_to(tmp_path) / "odds.json")
    assert not result["coverage_complete"]
    assert json.loads((tmp_path / "latest.json").read_text()) == result


@pytest.mark.parametrize("failure", ["verification", "empty_prices", "normalization"])
def test_invalid_capture_never_replaces_previous_verified_pointer(tmp_path, failure):
    latest = tmp_path / "latest.json"
    latest.write_text('{"odds_file":"previous/odds.json"}')
    verified = tmp_path / "runs" / "bad" / "verified"
    report, verification = snapshot(verified)
    if failure == "verification":
        verification["source_checks_passed"] = False
    elif failure == "empty_prices":
        report["summary"]["over_under_complete_pairs"] = 0
    else:
        report["normalization_issues"] = [{"type": "column_length_mismatch"}]
    (verified / "odds.json").write_text(json.dumps(report))
    (verified / "verification.json").write_text(json.dumps(verification))
    with pytest.raises(RuntimeError):
        worker.publish_verified(tmp_path, verified)
    assert json.loads(latest.read_text()) == {"odds_file": "previous/odds.json"}


@pytest.mark.asyncio
async def test_failed_child_marks_cycle_failed_and_does_not_publish(tmp_path, monkeypatch):
    async def fail(*args):
        raise RuntimeError("browser capture failed")

    monkeypatch.setattr(worker, "command", fail)
    # Avoid registering process-wide signals during an in-process unit test.
    monkeypatch.setattr(worker.sys, "platform", "win32")
    args = SimpleNamespace(
        output_dir=tmp_path, cycles=1, region="nj", wait_seconds=8, command_timeout=120, interval_seconds=120
    )
    assert await worker.collect(args) == 1
    assert json.loads((tmp_path / "worker-status.json").read_text())["state"] == "failed"
    assert not (tmp_path / "latest.json").exists()


def test_retention_keeps_published_run_and_ignores_unowned_directories(tmp_path):
    runs = tmp_path / "runs"
    names = [f"20261022T05120{i}.000000Z" for i in range(4)]
    for name in names:
        (runs / name).mkdir(parents=True)
        (runs / name / "evidence.json").write_text("{}")
    (runs / "user-notes").mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"odds_file": str(Path("runs") / names[0] / "verified" / "odds.json")})
    )
    worker.prune_runs(tmp_path, 1)
    assert sorted(path.name for path in runs.iterdir()) == sorted([names[0], names[3], "user-notes"])

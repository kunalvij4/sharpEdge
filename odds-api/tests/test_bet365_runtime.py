from odds_api.infrastructure.bet365_runtime import prune_runs, safe_text, safe_url


def test_sanitization_omits_url_credentials_and_tokens():
    assert safe_url("https://user:secret@va.bet365.com/sports?token=secret#session") == (
        "https://va.bet365.com/sports"
    )
    assert "opaque" in safe_url("https://va.bet365.com/" + "a" * 100)
    assert safe_text("Contact someone@example.com or https://host/path?secret=value") == (
        "Contact [email] or [URL]"
    )


def test_retention_keeps_recent_runs_and_ignores_unowned_directories(tmp_path):
    runs = tmp_path / "runs"
    names = [f"20261022T05120{i}.000000Z" for i in range(4)]
    for name in names:
        (runs / name).mkdir(parents=True)
        (runs / name / "evidence.json").write_text("{}")
    (runs / "user-notes").mkdir()
    prune_runs(tmp_path, 1)
    assert sorted(path.name for path in runs.iterdir()) == [names[3], "user-notes"]

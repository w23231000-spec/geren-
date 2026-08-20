"""CLI smoke test for the one retained offline presentation command."""

import json

from hfss_optimization_agent.cli import main


def test_offline_cli_returns_zero_and_creates_complete_artifacts(tmp_path, capsys):
    exit_code = main(
        ["offline-demo", "--task-id", "offline-cli", "--artifact-root", str(tmp_path)]
    )
    output = capsys.readouterr().out
    payload = json.loads(output[output.index("{") :])
    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["baseline_sparameter_provider"] == "deterministic-surrogate"
    assert (tmp_path / "offline-cli" / "baseline" / "sparameter_result.json").exists()
    assert (tmp_path / "offline-cli" / "candidate" / "hfss_result.json").exists()

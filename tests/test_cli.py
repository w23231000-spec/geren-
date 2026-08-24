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
    assert payload["status"] == "succeeded_candidate"
    assert payload["terminal_reason_code"] == "candidate_target_met"
    assert payload["baseline_sparameter_provider"] == "deterministic-surrogate"
    immutable = tmp_path / "offline-cli" / "artifacts"
    assert next(immutable.rglob("baseline_sparameters.*.json"), None) is not None
    assert next(immutable.rglob("candidate_hfss.*.json"), None) is not None

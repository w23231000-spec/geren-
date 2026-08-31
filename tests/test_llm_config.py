from pathlib import Path

import pytest

from hfss_optimization_agent.domain.canonical_json import CanonicalJsonError
from hfss_optimization_agent.llm.config import load_llm_provider_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "llm.deepseek_v1.json"


def test_checked_in_deepseek_config_loads_with_empty_key() -> None:
    config = load_llm_provider_config(CONFIG_PATH)

    assert config.enabled is False
    assert config.provider == "deepseek"
    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-v4-pro"
    assert config.resolved_api_key({}) == ""


def test_deepseek_api_key_can_come_from_environment() -> None:
    config = load_llm_provider_config(CONFIG_PATH)

    assert config.resolved_api_key({"DEEPSEEK_API_KEY": " user-supplied-key "}) == (
        "user-supplied-key"
    )


def test_llm_config_rejects_unknown_fields(tmp_path: Path) -> None:
    invalid = tmp_path / "llm.json"
    invalid.write_text(
        CONFIG_PATH.read_text(encoding="utf-8").replace(
            '"max_tokens": 2000',
            '"max_tokens": 2000,\n  "unexpected": true',
        ),
        encoding="utf-8",
    )

    with pytest.raises(CanonicalJsonError, match="unknown fields"):
        load_llm_provider_config(invalid)

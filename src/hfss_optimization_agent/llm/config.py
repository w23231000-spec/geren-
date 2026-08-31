"""Strict configuration contract for an optional LLM provider."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from typing import Mapping

from ..domain.canonical_json import canonical_loads, require_exact_fields


LLM_PROVIDER_CONFIG_SCHEMA_VERSION = "llm-provider-config/1.0"
DEEPSEEK_PROVIDER = "deepseek"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


@dataclass(frozen=True, slots=True)
class LLMProviderConfig:
    """Provider settings only; no model client or workflow wiring is implied."""

    schema_version: str
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    api_key_env: str
    timeout_seconds: float
    max_tokens: int

    def __post_init__(self) -> None:
        if self.schema_version != LLM_PROVIDER_CONFIG_SCHEMA_VERSION:
            raise ValueError(
                "LLM provider schema_version must be "
                f"{LLM_PROVIDER_CONFIG_SCHEMA_VERSION}"
            )
        if not isinstance(self.enabled, bool):
            raise ValueError("LLM provider enabled must be boolean")
        if self.provider != DEEPSEEK_PROVIDER:
            raise ValueError("Only the DeepSeek provider is configured")
        if self.base_url != DEEPSEEK_BASE_URL:
            raise ValueError(f"DeepSeek base_url must be {DEEPSEEK_BASE_URL}")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("LLM provider model must be non-empty")
        if not isinstance(self.api_key, str):
            raise ValueError("LLM provider api_key must be a string")
        if not isinstance(self.api_key_env, str) or not self.api_key_env.strip():
            raise ValueError("LLM provider api_key_env must be non-empty")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0.0
        ):
            raise ValueError("LLM provider timeout_seconds must be positive and finite")
        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError("LLM provider max_tokens must be a positive integer")

    def resolved_api_key(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> str:
        """Prefer an explicit configured key, then the named environment variable."""

        configured = self.api_key.strip()
        if configured:
            return configured
        source = os.environ if environ is None else environ
        return source.get(self.api_key_env, "").strip()


def load_llm_provider_config(path: Path) -> LLMProviderConfig:
    """Load one strict, versioned LLM provider configuration file."""

    data = require_exact_fields(
        canonical_loads(Path(path).read_text(encoding="utf-8")),
        {
            "schema_version",
            "enabled",
            "provider",
            "base_url",
            "model",
            "api_key",
            "api_key_env",
            "timeout_seconds",
            "max_tokens",
        },
        context="LLMProviderConfig",
    )
    return LLMProviderConfig(
        schema_version=data["schema_version"],
        enabled=data["enabled"],
        provider=data["provider"],
        base_url=data["base_url"],
        model=data["model"],
        api_key=data["api_key"],
        api_key_env=data["api_key_env"],
        timeout_seconds=data["timeout_seconds"],
        max_tokens=data["max_tokens"],
    )

from pathlib import Path

from hfss_optimization_agent.application.real_hfss_service import (
    PreparedDevelopmentAuthorization,
    RealHFSSRuntime,
    execute_real_hfss,
    prepare_development_authorization,
    validate_real_hfss_runtime,
    validate_task,
)


ROOT = Path(__file__).resolve().parents[1]


def test_application_service_api_is_exposed() -> None:
    assert callable(validate_task)
    assert callable(prepare_development_authorization)
    assert callable(validate_real_hfss_runtime)
    assert callable(execute_real_hfss)
    assert PreparedDevelopmentAuthorization is not None
    assert RealHFSSRuntime is not None


def test_single_launcher_no_longer_chains_prepare_or_run_scripts() -> None:
    source = (ROOT / "START_REAL_HFSS.py").read_text(
        encoding="utf-8"
    )

    assert "from PREPARE_REAL_HFSS_DEVELOPMENT" not in source
    assert "RUN_REAL_HFSS.py" not in source
    assert "subprocess.run" not in source

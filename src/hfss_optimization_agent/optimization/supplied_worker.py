"""Independent JSON worker for the supplied optimizer implementation."""

from __future__ import annotations

import argparse
import csv
import json
import traceback
from pathlib import Path
from typing import Any

from ..core.models import CandidateParameters, OptimizationBatch
from ..domain.canonical_json import canonical_dumps
from ..harness.process_supervisor import worker_heartbeat_from_environment
from .contracts import EffectiveObjective, OptimizerRequest, _digest
from .supplied_loader import import_supplied_module


_OBJECTIVE_COLUMNS = (
    "name",
    "active",
    "expression",
    "direction",
    "target",
    "recommendation_weight",
    "start_ghz",
    "stop_ghz",
    "unit",
    "description",
)


def _write_objectives(path: Path, effective: EffectiveObjective) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_OBJECTIVE_COLUMNS)
        writer.writeheader()
        for term in effective.terms:
            writer.writerow(
                {
                    "name": term.name,
                    "active": "true",
                    "expression": term.expression,
                    "direction": term.direction,
                    "target": "" if term.target is None else term.target,
                    "recommendation_weight": term.recommendation_weight,
                    "start_ghz": "" if term.start_ghz is None else term.start_ghz,
                    "stop_ghz": "" if term.stop_ghz is None else term.stop_ghz,
                    "unit": term.unit,
                    "description": term.description,
                }
            )


def _verify_effective_summary(summary: dict[str, Any], effective: EffectiveObjective) -> None:
    actual = summary.get("objectives")
    if not isinstance(actual, list) or len(actual) != len(effective.terms):
        raise RuntimeError("vendor summary objective count differs from effective objective")
    for item, term in zip(actual, effective.terms, strict=True):
        band = item.get("band", {})
        expected = {
            "name": term.name,
            "expression": term.expression,
            "direction": term.direction,
            "target": term.target,
            "recommendation_weight": term.recommendation_weight,
            "start_ghz": term.start_ghz,
            "stop_ghz": term.stop_ghz,
        }
        observed = {
            "name": item.get("name"),
            "expression": item.get("expression"),
            "direction": item.get("direction"),
            "target": item.get("target"),
            "recommendation_weight": item.get("recommendation_weight"),
            "start_ghz": band.get("start_ghz"),
            "stop_ghz": band.get("stop_ghz"),
        }
        if canonical_dumps(observed) != canonical_dumps(expected):
            raise RuntimeError(f"vendor effective objective drift for {term.name}")


def _candidate_set(
    run_directory: Path, summary: dict[str, Any], request: OptimizerRequest
) -> list[CandidateParameters]:
    with (run_directory / "01_pareto.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    parameters = list(summary["parameters"])
    candidates: list[CandidateParameters] = []
    for row in rows:
        point_id = str(row["point_id"])
        candidate_id = (
            point_id
            if request.iteration == 0
            else f"optimizer-r{request.iteration}:{point_id}"
        )
        values = {
            str(spec["name"]): float(
                row[f"model_parameter__{spec['name']}__{spec['model_unit']}"]
            )
            for spec in parameters
        }
        evidence = {
            key: value
            for key, value in row.items()
            if key.startswith(("objective__", "constraint__", "metric__"))
        }
        candidates.append(
            CandidateParameters(
                candidate_id=candidate_id,
                iteration=request.iteration + 1,
                values=values,
                metadata={
                    "source": "supplied-optimizer-worker",
                    "role": row.get("role", ""),
                    "recommended": row.get("recommended") == "true",
                    "vendor_evidence": evidence,
                    "vendor_evidence_digest": _digest(evidence),
                    "calibration_status": "uncalibrated",
                },
            )
        )
    if not candidates:
        raise RuntimeError("vendor optimizer returned an empty Pareto candidate set")
    return candidates


def _validate_request_baseline(request: OptimizerRequest, source_root: Path) -> None:
    with (source_root / "config" / "parameters.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    expected = {
        str(row["name"]): float(row["baseline"]) * float(row["scale_to_model"])
        for row in rows
        if str(row.get("active", "")).strip().lower() in {"true", "1", "yes", "y"}
    }
    actual = request.baseline.values
    if set(expected) != set(actual):
        raise ValueError("optimizer request baseline parameter names differ from vendor runtime")
    mismatched = [
        name
        for name, value in expected.items()
        if abs(value - float(actual[name])) > max(abs(value), 1.0) * 1e-12
    ]
    if mismatched:
        raise ValueError(
            f"optimizer request baseline values differ from vendor runtime for {mismatched}"
        )


def execute_request(
    request: OptimizerRequest,
    *,
    source_root: Path,
    output_root: Path,
    quick: bool,
    debug: bool,
) -> OptimizationBatch:
    root = source_root.resolve()
    _validate_request_baseline(request, root)
    effective_path = output_root.resolve() / "effective_objectives" / f"{request.digest}.csv"
    effective_path.parent.mkdir(parents=True, exist_ok=True)
    _write_objectives(effective_path, request.effective_objective)
    module = import_supplied_module(root, "app.run")
    run_directory = Path(
        module.execute(
            config_path=root / "config" / "config.toml",
            parameters_path=root / "config" / "parameters.csv",
            objectives_path=effective_path,
            constraints_path=root / "config" / "constraints.csv",
            models_path=root / "config" / "models.csv",
            output_root=output_root,
            quick=quick,
            debug=debug,
        )
    )
    summary_path = run_directory / "00_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") not in {"completed", "success"}:
        raise RuntimeError(str(summary.get("error", "supplied optimizer failed")))
    _verify_effective_summary(summary, request.effective_objective)
    candidates = _candidate_set(run_directory, summary, request)
    recommended = str(summary["recommended_point_id"])
    if recommended not in {candidate.candidate_id for candidate in candidates}:
        raise RuntimeError("vendor recommended point is absent from Pareto candidate set")
    artifacts = [str(path) for path in sorted(run_directory.iterdir()) if path.is_file()]
    artifacts.append(str(effective_path))
    candidate_evidence = {
        candidate.candidate_id: candidate.metadata["vendor_evidence_digest"]
        for candidate in candidates
    }
    return OptimizationBatch(
        run_id=run_directory.name,
        success=True,
        candidates=candidates,
        recommended_candidate_id=recommended,
        evaluations=int(summary.get("algorithm", {}).get("evaluations", 0)),
        metadata={
            "validation_status": summary.get("validation_status", "surrogate_only"),
            "optimizer_request_digest": request.digest,
            "effective_objective_digest": request.effective_objective.digest,
            "effective_objective": request.effective_objective.to_dict(),
            "source_objective_digest": request.effective_objective.source_objective_digest,
            "candidate_evidence_digests": candidate_evidence,
            "candidate_set_digest": _digest([candidate.to_dict() for candidate in candidates]),
            "pareto_points": len(candidates),
            "vendor_summary_sha256": _digest(summary),
        },
        artifact_paths=artifacts,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supplied-optimizer-worker")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--debug", action="store_true")
    arguments = parser.parse_args(argv)
    with worker_heartbeat_from_environment():
        try:
            request = OptimizerRequest.from_dict(
                json.loads(arguments.request.read_text(encoding="utf-8"))
            )
            batch = execute_request(
                request,
                source_root=arguments.source_root,
                output_root=arguments.output_root,
                quick=arguments.quick,
                debug=arguments.debug,
            )
            response = {
                "status": "success",
                "optimizer_request_digest": request.digest,
                "effective_objective_digest": request.effective_objective.digest,
                "batch": batch.to_dict(),
            }
            code = 0
        except Exception as exc:
            response = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            code = 1
        arguments.response.parent.mkdir(parents=True, exist_ok=True)
        arguments.response.write_text(
            json.dumps(response, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return code


if __name__ == "__main__":
    raise SystemExit(main())

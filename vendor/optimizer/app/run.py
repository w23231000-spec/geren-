"""V2 优化任务的总调度入口。

阅读本项目时建议从 :func:`execute` 开始：它依次读取 CSV/TOML 配置，选择结构与
代理模型，计算基准方案，构造单点评价函数，调用 ``optimizer.py`` 中选定的算法，
最后挑选推荐解并把表格、曲线、图片和汇总 JSON 写入一次独立运行目录。

本模块只负责“串流程”，不实现具体优化算法，也不在这里定义目标/约束表达式：
目标和约束分别交给 ``objectives.py``、``constraints.py``，电性能指标和报告交给
``metrics.py``，模型实例化则由 ``model_registry.py`` 负责。

核心数据约定：

* 参数字典始终使用 ``parameters.csv`` 中的显示单位；送入模型前才按
  ``scale_to_model`` 转为模型单位。
* 优化器只接收统一的最小化目标向量 ``F``。原始指标值单独保存在 ``details``，
  供报表和前端展示。
* 所有约束统一写成 ``G <= 0`` 表示通过，``G > 0`` 表示违反。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .constraints import (
    ConstraintSpec,
    evaluate_constraints,
    load_constraint_specs,
    split_constraints,
)
from .metrics import (
    analyze_response,
    analyze_response_bands,
    plot_pareto,
    plot_sparameter_comparisons,
    select_recommended_index,
    write_sparameter_curves,
)
from .model_registry import ModelBinding, build_model_suite, load_model_catalog
from .objectives import (
    ObjectiveEvaluation,
    ObjectiveSpec,
    active_objectives,
    evaluate_objectives,
    load_objective_specs,
    recommendation_weights,
    validate_objective_bands,
)
from .optimizer import (
    Evaluation,
    OptimizerSettings,
    baseline_values,
    load_parameter_specs,
    run_mopso,
    run_mosa,
    run_nsga3,
    values_to_model_units,
)
from .surrogate_adapter import surrogate_model_sha256

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
CONFIG_ROOT = PROJECT_ROOT / "config"
# 兼容曾读取 run.ROOT 的二开代码；新代码请使用上面的明确路径名。
ROOT = PROJECT_ROOT


_ALGORITHM_ALIASES = {
    "NSGAIII": "NSGA-III",
    "NSGA3": "NSGA-III",
    "MOPSO": "MOPSO",
    "PSO": "MOPSO",
    "MULTIOBJECTIVEPSO": "MOPSO",
    "MOSA": "MOSA",
    "SA": "MOSA",
    "SIMULATEDANNEALING": "MOSA",
    "MULTIOBJECTIVESIMULATEDANNEALING": "MOSA",
    "模拟退火": "MOSA",
}


def normalize_algorithm(value: object) -> str:
    """把前端/配置中的算法别名归一为内部唯一名称。

    例如 ``PSO`` 会归一为 ``MOPSO``，这样后续分派和结果记录只需处理
    ``NSGA-III``、``MOPSO``、``MOSA`` 三种名称。
    """

    text = str(value).strip()
    normalized = (
        text
        if text == "模拟退火"
        else text.upper().replace(" ", "").replace("_", "").replace("-", "")
    )
    try:
        return _ALGORITHM_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError(
            "algorithm 仅支持 NSGA-III、MOPSO（PSO）或 MOSA（模拟退火）"
        ) from exc


def file_sha256(path: str | Path) -> str:
    """返回文件内容的 SHA256，用于结果可追溯性校验。"""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def optimization_source_sha256() -> str:
    """计算 V2 优化链源码的联合校验值；代理模型本体另有独立校验值。"""

    digest = hashlib.sha256()
    for name in (
        "run.py",
        "optimizer.py",
        "metrics.py",
        "objectives.py",
        "constraints.py",
        "surrogate_adapter.py",
        "model_registry.py",
    ):
        path = APP_ROOT / name
        digest.update(f"app/{name}".encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest().upper()


def environment_versions() -> dict[str, str]:
    """收集主要运行依赖版本，便于别人复现实验或排查环境差异。"""

    result = {"python": platform.python_version()}
    for package in ("numpy", "scipy", "jax", "jaxlib", "matplotlib", "pymoo"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "not-installed"
    return result


def load_config(path: str | Path) -> dict[str, Any]:
    """读取 ``config.toml``，返回保持 TOML 层级结构的普通字典。"""

    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


def _resolve_parameters_path(
    models_path: str | Path,
    binding: ModelBinding,
    explicit_path: str | Path | None,
) -> Path:
    """确定当前结构使用的参数表，并阻止模型清单通过相对路径越界。

    命令行显式传入 ``parameters_path`` 时优先使用它；否则读取当前主电模型在
    ``models.csv`` 中绑定的 ``parameters_file``。
    """

    if explicit_path is not None:
        resolved = Path(explicit_path).resolve()
    else:
        catalog_directory = Path(models_path).resolve().parent
        resolved = (catalog_directory / binding.parameters_file).resolve()
        try:
            resolved.relative_to(catalog_directory)
        except ValueError as exc:
            raise ValueError("模型绑定的 parameters_file 不能越出 models.csv 所在目录") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"模型参数表不存在：{resolved}")
    return resolved


def frequency_grid(config: dict[str, Any]) -> np.ndarray:
    """从 GHz 配置生成 Hz 频率网格，形状为 ``(频点数,)``。"""

    frequency = config["frequency"]
    start = float(frequency["start_ghz"])
    stop = float(frequency["stop_ghz"])
    points = int(frequency["points"])
    if not 0.0 < start < stop or points < 2:
        raise ValueError("频率必须满足 0 < start_ghz < stop_ghz，且 points >= 2")
    return np.linspace(start * 1e9, stop * 1e9, points, dtype=np.float64)


def _objective_band_analyses(
    response: Any,
    baseline: Any,
    objective_specs: list[ObjectiveSpec],
    full_analysis: dict[str, float],
    electrical: dict[str, Any],
    shared_metrics: dict[str, float] | None = None,
) -> dict[tuple[float, float] | None, dict[str, float]]:
    """按目标频段计算并缓存同一条响应的指标。

    返回字典以 ``None`` 表示全频段，以 ``(start_ghz, stop_ghz)`` 表示局部频段。
    多个目标使用同一频段时只切片和计算一次；热/可靠性等非电模型提供的共享指标
    会合并进每个频段字典，供目标表达式统一引用。
    """
    analyses: dict[tuple[float, float] | None, dict[str, float]] = {None: full_analysis}
    local_bands = list(
        dict.fromkeys(
            item.band_ghz for item in objective_specs if item.band_ghz is not None
        )
    )
    if local_bands:
        local_analyses = analyze_response_bands(
                response,
                baseline,
                local_bands,
                phase_floor_db=float(electrical["phase_reliable_floor_db"]),
                passivity_tolerance=float(electrical["passivity_tolerance"]),
            )
        if shared_metrics:
            for values in local_analyses.values():
                values.update(shared_metrics)
        analyses.update(local_analyses)
    return analyses


def _evaluate_objectives_by_band(
    objective_specs: list[ObjectiveSpec],
    analyses: dict[tuple[float, float] | None, dict[str, float]],
    parameters: dict[str, float],
) -> ObjectiveEvaluation:
    """在每个目标自己的频段上求值，并拼成统一目标向量。

    ``raw_values`` 保留用户能理解的原始指标；``minimization_values`` 是传给算法的
    ``F``。最大化目标会在目标模块中转号，目标值型指标会转为到目标值的距离。
    两个数组形状均为 ``(目标数,)``。
    """

    names: list[str] = []
    raw_values: list[float] = []
    minimization_values: list[float] = []
    for spec in objective_specs:
        result = evaluate_objectives(
            [spec], metrics=analyses[spec.band_ghz], parameters=parameters
        )
        names.append(spec.name)
        raw_values.append(float(result.raw_values[0]))
        minimization_values.append(float(result.minimization_values[0]))
    return ObjectiveEvaluation(
        names=tuple(names),
        raw_values=np.asarray(raw_values, dtype=np.float64),
        minimization_values=np.asarray(minimization_values, dtype=np.float64),
    )


def _run_directory(output_root: Path) -> Path:
    """创建不会覆盖历史结果的时间戳运行目录并返回其路径。"""

    output_root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    candidate = output_root / base
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{base}_{suffix:02d}"
        suffix += 1
    candidate.mkdir()
    return candidate


def _write_pareto_csv(
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """写出最终可行非支配解表；每一行对应一个 Pareto 点。"""

    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_debug_log(
    path: Path,
    records: list[Evaluation],
    parameter_names: list[str],
    objective_specs: list[ObjectiveSpec],
    constraint_names: list[str],
    metric_names: list[str],
) -> None:
    """在调试模式下保存所有已评价候选，而不只保存最终 Pareto 解。

    列名显式区分原始目标值与算法使用的 ``F``、原始约束违反量与归一化 ``G``，
    便于判断问题来自表达式、代理预测还是优化搜索。
    """

    fieldnames = ["evaluation", "status", "message"] + parameter_names
    for spec in objective_specs:
        fieldnames += [f"objective__{spec.name}__raw", f"objective__{spec.name}__F"]
    for name in constraint_names:
        fieldnames += [
            f"constraint__{name}__raw_violation",
            f"constraint__{name}__G",
        ]
    fieldnames += [f"metric__{name}" for name in metric_names]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for index, record in enumerate(records, start=1):
            row: dict[str, Any] = {
                "evaluation": index,
                "status": record.status,
                "message": record.message,
            }
            row.update(record.parameters)
            for objective_index, spec in enumerate(objective_specs):
                row[f"objective__{spec.name}__raw"] = record.details.get(
                    f"objective_raw__{spec.name}", ""
                )
                row[f"objective__{spec.name}__F"] = record.objectives[
                    objective_index
                ]
            row.update(
                {
                    f"constraint__{name}__G": value
                    for name, value in zip(
                        constraint_names, record.constraints, strict=True
                    )
                }
            )
            row.update(
                {
                    f"constraint__{name}__raw_violation": record.details.get(
                        f"constraint_raw__{name}", ""
                    )
                    for name in constraint_names
                }
            )
            row.update(
                {
                    f"metric__{name}": record.details.get(name, "")
                    for name in metric_names
                }
            )
            writer.writerow(row)


def check_baseline(
    config_path: str | Path = CONFIG_ROOT / "config.toml",
    parameters_path: str | Path | None = None,
    objectives_path: str | Path = CONFIG_ROOT / "objectives.csv",
    constraints_path: str | Path = CONFIG_ROOT / "constraints.csv",
    models_path: str | Path = CONFIG_ROOT / "models.csv",
) -> dict[str, Any]:
    """只运行基准方案，提前检查配置、模型、目标和约束能否衔接。

    这是正式优化前成本最低的自检入口。它会走完模型注册、单位转换、代理预测、
    指标计算以及目标/约束表达式校验，但不会创建优化结果目录或启动搜索。返回值是
    基准指标字典，并附带模型能力和逐条约束是否通过的信息。
    """

    config = load_config(config_path)
    config["optimizer"]["algorithm"] = normalize_algorithm(
        config["optimizer"].get("algorithm", "")
    )
    model_catalog = load_model_catalog(models_path)
    model_binding = model_catalog.primary_electrical()
    resolved_parameters_path = _resolve_parameters_path(
        models_path, model_binding, parameters_path
    )
    specs = load_parameter_specs(resolved_parameters_path)
    baseline_display = baseline_values(specs)
    model_suite = build_model_suite(model_catalog, config["model"])
    frequency = frequency_grid(config)
    electrical = config["electrical_constraints"]
    # 基准响应同时充当“候选”和“参照”，所以所有相对相位误差应为零；这也能验证
    # S 参数 shape、频率网格和指标计算链是否完整可用。
    suite_evaluation = model_suite.evaluate(
        values_to_model_units(specs, baseline_display),
        frequency,
        electrical_metric_builder=lambda response: analyze_response(
            response,
            response,
            phase_floor_db=float(electrical["phase_reliable_floor_db"]),
            passivity_tolerance=float(electrical["passivity_tolerance"]),
        ),
    )
    response = suite_evaluation.primary_response
    analysis = dict(suite_evaluation.metrics)
    parameter_names = [item.name for item in specs]
    objective_specs = load_objective_specs(
        objectives_path,
        metric_names=analysis,
        parameter_names=parameter_names,
    )
    enabled_objectives = active_objectives(objective_specs)
    if len(enabled_objectives) < 2:
        raise ValueError("多目标优化至少需要在 objectives.csv 中启用2个目标")
    validate_objective_bands(enabled_objectives, frequency)
    constraint_specs = load_constraint_specs(
        constraints_path,
        metric_names=analysis,
        parameter_names=parameter_names,
    )
    objective_analyses = _objective_band_analyses(
        response,
        response,
        enabled_objectives,
        analysis,
        electrical,
        {
            name: value
            for output in suite_evaluation.outputs
            if output.model_id != model_binding.model_id
            for name, value in output.metrics.items()
        },
    )
    _evaluate_objectives_by_band(
        enabled_objectives,
        objective_analyses,
        baseline_display,
    )
    baseline_constraints = evaluate_constraints(
        constraint_specs,
        metrics=analysis,
        parameters=baseline_display,
    )
    analysis["configured_objective_count"] = len(enabled_objectives)
    analysis["configured_constraint_count"] = len(baseline_constraints.names)
    analysis["baseline_constraint_feasible"] = baseline_constraints.feasible
    analysis["baseline_constraint_results"] = [
        {
            "name": name,
            "raw_violation": float(value),
            "pass": bool(value <= 0.0),
        }
        for name, value in zip(
            baseline_constraints.names,
            baseline_constraints.violations,
            strict=True,
        )
    ]
    analysis["model_id"] = model_binding.model_id
    analysis["model_capabilities"] = model_catalog.capabilities()
    return analysis


def execute(
    *,
    config_path: str | Path = CONFIG_ROOT / "config.toml",
    parameters_path: str | Path | None = None,
    objectives_path: str | Path = CONFIG_ROOT / "objectives.csv",
    constraints_path: str | Path = CONFIG_ROOT / "constraints.csv",
    models_path: str | Path = CONFIG_ROOT / "models.csv",
    output_root: str | Path = PROJECT_ROOT / "results",
    quick: bool = False,
    debug: bool = False,
) -> Path:
    """执行一次完整的代理模型多目标优化，并返回本次结果目录。

    主调用链可概括为：

    1. 读取配置并按 ``models.csv`` 选择主电代理及对应参数表；
    2. 计算基准响应，加载并验证目标/约束；
    3. 构造算法所需的 ``evaluate(values) -> Evaluation``；
    4. 运行 NSGA-III、MOPSO 或 MOSA，提取可行 Pareto 解；
    5. 按目标权重选推荐点，重新生成各 Pareto 点的 S 参数；
    6. 写出 CSV、PNG 和 ``00_summary.json``。

    每次调用先创建独立目录。若任一阶段失败，目录仍会保留，其中
    ``00_summary.json`` 标记 ``status=failed``；``debug=True`` 时还写入 traceback。
    这种失败隔离避免一次坏配置覆盖之前成功的结果。
    """

    run_directory = _run_directory(Path(output_root).resolve())
    summary_path = run_directory / "00_summary.json"
    try:
        # 一次运行先“冻结”所有输入：结构、模型、参数范围、频率网格和基准响应。
        # 后续所有候选必须与同一个基准比较，才能保证目标值彼此可比。
        config = load_config(config_path)
        algorithm_name = normalize_algorithm(config["optimizer"].get("algorithm", ""))
        config["optimizer"]["algorithm"] = algorithm_name
        model_catalog = load_model_catalog(models_path)
        model_binding = model_catalog.primary_electrical()
        resolved_parameters_path = _resolve_parameters_path(
            models_path, model_binding, parameters_path
        )
        specs = load_parameter_specs(resolved_parameters_path)
        frequency = frequency_grid(config)
        baseline_display = baseline_values(specs)
        model_config = config["model"]
        electrical = config["electrical_constraints"]

        model_suite = build_model_suite(model_catalog, model_config)
        baseline_suite_evaluation = model_suite.evaluate(
            values_to_model_units(specs, baseline_display),
            frequency,
            electrical_metric_builder=lambda response: analyze_response(
                response,
                response,
                phase_floor_db=float(electrical["phase_reliable_floor_db"]),
                passivity_tolerance=float(electrical["passivity_tolerance"]),
            ),
        )
        baseline_response = baseline_suite_evaluation.primary_response
        baseline_analysis = dict(baseline_suite_evaluation.metrics)
        parameter_names = [item.name for item in specs]
        all_objective_specs = load_objective_specs(
            objectives_path,
            metric_names=baseline_analysis,
            parameter_names=parameter_names,
        )
        objective_specs = active_objectives(all_objective_specs)
        if len(objective_specs) < 2:
            raise ValueError("多目标优化至少需要在 objectives.csv 中启用2个目标")
        validate_objective_bands(objective_specs, frequency)
        all_constraint_specs = load_constraint_specs(
            constraints_path,
            metric_names=baseline_analysis,
            parameter_names=parameter_names,
        )
        pre_constraints, post_constraints = split_constraints(all_constraint_specs)
        active_constraint_specs: list[ConstraintSpec] = [
            *pre_constraints,
            *post_constraints,
        ]
        constraint_names = [item.name for item in active_constraint_specs]

        # 基准值不仅用于最终对比，也用于约束量纲归一化。不同约束可能分别以米、度、
        # 无量纲等表示，缩放后算法统一比较 G；缩放不改变 G<=0 的可行性判断。
        baseline_objective_analyses = _objective_band_analyses(
            baseline_response,
            baseline_response,
            objective_specs,
            baseline_analysis,
            electrical,
            {
                name: value
                for output in baseline_suite_evaluation.outputs
                if output.model_id != model_binding.model_id
                for name, value in output.metrics.items()
            },
        )
        baseline_objective_evaluation = _evaluate_objectives_by_band(
            objective_specs,
            baseline_objective_analyses,
            baseline_display,
        )
        baseline_pre = evaluate_constraints(
            pre_constraints,
            parameters=baseline_display,
        )
        baseline_post = evaluate_constraints(
            post_constraints,
            metrics=baseline_analysis,
            parameters=baseline_display,
        )
        baseline_constraint_raw = np.concatenate(
            [baseline_pre.violations, baseline_post.violations]
        )
        constraint_scales = np.maximum(np.abs(baseline_constraint_raw), 1.0)
        baseline_constraint_g = np.divide(
            baseline_constraint_raw,
            constraint_scales,
            out=np.empty_like(baseline_constraint_raw),
            where=constraint_scales > 0.0,
        )
        baseline_constraint_feasible = bool(np.all(baseline_constraint_g <= 0.0))
        objective_count = len(objective_specs)
        constraint_count = len(active_constraint_specs)

        def evaluate(values: dict[str, float]) -> Evaluation:
            """评价一个显示单位参数方案，返回优化器统一的数据结构。

            ``objectives`` 是形状 ``(objective_count,)`` 的最小化向量 F；
            ``constraints`` 是形状 ``(constraint_count,)`` 的归一化向量 G，且
            ``G <= 0`` 才通过。``details`` 保存原始指标/违反量，专供结果解释。
            """

            # 先检查只依赖几何参数的约束。若已经违反，就用显式惩罚值填充尚未计算的
            # 后置约束，直接返回而不调用昂贵的代理模型。
            pre_raw = evaluate_constraints(
                pre_constraints,
                parameters=values,
            ).violations
            pre_count = len(pre_constraints)
            pre_g = pre_raw / constraint_scales[:pre_count]
            if np.any(pre_g > 0.0):
                constraints = np.concatenate(
                    [pre_g, np.full(len(post_constraints), 1e6, dtype=np.float64)]
                )
                return Evaluation(
                    parameters=values,
                    objectives=np.full(objective_count, 1e12, dtype=np.float64),
                    constraints=constraints,
                    details={
                        f"constraint_raw__{name}": float(value)
                        for name, value in zip(
                            [item.name for item in pre_constraints],
                            pre_raw,
                            strict=True,
                        )
                    },
                    status="infeasible",
                    message="违反代理预测前的参数约束",
                )
            # 通过几何约束后才预测电/热/可靠性等已连接模型。模型套件负责把非主电
            # 模型的标量指标合并到 metrics，同时保留主电模型的完整 S 参数响应。
            suite_evaluation = model_suite.evaluate(
                values_to_model_units(specs, values),
                frequency,
                electrical_metric_builder=lambda response: analyze_response(
                    response,
                    baseline_response,
                    phase_floor_db=float(electrical["phase_reliable_floor_db"]),
                    passivity_tolerance=float(electrical["passivity_tolerance"]),
                ),
            )
            response = suite_evaluation.primary_response
            analysis = dict(suite_evaluation.metrics)
            post_raw = evaluate_constraints(
                post_constraints,
                metrics=analysis,
                parameters=values,
            ).violations
            constraint_raw = np.concatenate([pre_raw, post_raw])
            constraints = constraint_raw / constraint_scales
            objective_analyses = _objective_band_analyses(
                response,
                baseline_response,
                objective_specs,
                analysis,
                electrical,
                {
                    name: value
                    for output in suite_evaluation.outputs
                    if output.model_id != model_binding.model_id
                    for name, value in output.metrics.items()
                },
            )
            objective_evaluation = _evaluate_objectives_by_band(
                objective_specs,
                objective_analyses,
                values,
            )
            details = dict(analysis)
            details.update(
                {
                    f"objective_raw__{name}": float(value)
                    for name, value in zip(
                        objective_evaluation.names,
                        objective_evaluation.raw_values,
                        strict=True,
                    )
                }
            )
            details.update(
                {
                    f"constraint_raw__{name}": float(value)
                    for name, value in zip(
                        constraint_names,
                        constraint_raw,
                        strict=True,
                    )
                }
            )
            return Evaluation(
                parameters=values,
                objectives=objective_evaluation.minimization_values,
                constraints=constraints,
                details=details,
                status="ok" if np.all(constraints <= 0.0) else "infeasible",
            )

        # 三种算法的“规模”和“迭代”含义不同：NSGA-III 使用种群/代数，MOPSO 使用
        # 粒子/迭代数，MOSA 使用并行链/温度迭代数。这里把公共配置解析成同一设置对象。
        optimizer_config = config["optimizer"]
        quick_sizes = {
            "NSGA-III": (24, 8),
            "MOPSO": (24, 10),
            "MOSA": (16, 15),
        }
        quick_size, quick_iterations = quick_sizes[algorithm_name]
        configured_population = int(optimizer_config["population"])
        configured_generations = int(optimizer_config["generations"])
        configured_particles = int(
            optimizer_config.get("particles", configured_population)
        )
        legacy_iterations = int(
            optimizer_config.get("iterations", configured_generations)
        )
        configured_mopso_iterations = int(
            optimizer_config.get("mopso_iterations", legacy_iterations)
        )
        configured_mosa_iterations = int(
            optimizer_config.get("mosa_iterations", legacy_iterations)
        )
        configured_chains = int(optimizer_config.get("chains", configured_population))
        selected_size = (
            configured_population
            if algorithm_name == "NSGA-III"
            else configured_particles
            if algorithm_name == "MOPSO"
            else configured_chains
        )
        selected_iterations = (
            configured_generations
            if algorithm_name == "NSGA-III"
            else configured_mopso_iterations
            if algorithm_name == "MOPSO"
            else configured_mosa_iterations
        )
        if quick:
            selected_size, selected_iterations = quick_size, quick_iterations
        settings = OptimizerSettings(
            population=(
                selected_size if algorithm_name == "NSGA-III" else configured_population
            ),
            generations=(
                selected_iterations
                if algorithm_name == "NSGA-III"
                else configured_generations
            ),
            seed=int(optimizer_config["seed"]),
            neighborhood_samples=(
                min(7, selected_size - 1)
                if quick
                else int(optimizer_config["neighborhood_samples"])
            ),
            neighborhood_fraction=float(optimizer_config["neighborhood_fraction"]),
            particles=(
                selected_size if algorithm_name == "MOPSO" else configured_particles
            ),
            iterations=(
                selected_iterations
                if algorithm_name in {"MOPSO", "MOSA"}
                else legacy_iterations
            ),
            inertia_start=float(optimizer_config.get("inertia_start", 0.72)),
            inertia_end=float(optimizer_config.get("inertia_end", 0.40)),
            cognitive=float(optimizer_config.get("cognitive", 1.55)),
            social=float(optimizer_config.get("social", 1.55)),
            velocity_limit=float(optimizer_config.get("velocity_limit", 0.25)),
            archive_size=(
                selected_size * 2
                if quick and algorithm_name in {"MOPSO", "MOSA"}
                else int(optimizer_config.get("archive_size", selected_size))
            ),
            chains=(selected_size if algorithm_name == "MOSA" else configured_chains),
            initial_temperature=float(
                optimizer_config.get("initial_temperature", 1.0)
            ),
            final_temperature=float(optimizer_config.get("final_temperature", 0.03)),
            step_start=float(optimizer_config.get("step_start", 0.19)),
            step_end=float(optimizer_config.get("step_end", 0.01)),
            leader_pull=float(optimizer_config.get("leader_pull", 0.12)),
        )
        optimizer_runner = {
            "NSGA-III": run_nsga3,
            "MOPSO": run_mopso,
            "MOSA": run_mosa,
        }[algorithm_name]
        optimization = optimizer_runner(
            specs,
            evaluate,
            objective_count=objective_count,
            constraint_count=constraint_count,
            constraint_names=constraint_names,
            settings=settings,
        )
        # objective_matrix 是算法已统一成最小化方向的 F；raw_objective_matrix 是
        # CSV 表达式原始值。前者用于理想点距离和排序，后者用于用户可读的 Pareto 图。
        objective_matrix = np.vstack([item.objectives for item in optimization.pareto])
        raw_objective_matrix = np.asarray(
            [
                [
                    float(item.details[f"objective_raw__{spec.name}"])
                    for spec in objective_specs
                ]
                for item in optimization.pareto
            ],
            dtype=np.float64,
        )
        weights = recommendation_weights(objective_specs)
        recommended_index = select_recommended_index(
            objective_matrix,
            weights,
        )
        point_ids = [f"P{index:04d}" for index in range(1, len(optimization.pareto) + 1)]
        recommended_id = point_ids[recommended_index]
        baseline_objectives = baseline_objective_evaluation.minimization_values
        baseline_raw_objectives = baseline_objective_evaluation.raw_values

        # 优化期间只需保留标量指标；得到最终 Pareto 集后再逐点回放主电模型，收集
        # BASELINE + 全部 Pareto 点的完整 S11/S12/S21/S22 曲线供前端交互切换。
        responses: list[tuple[str, Any]] = [("BASELINE", baseline_response)]
        pareto_rows: list[dict[str, Any]] = []
        best_by_objective = np.argmin(objective_matrix, axis=0)
        for index, (point_id, evaluation) in enumerate(
            zip(point_ids, optimization.pareto, strict=True)
        ):
            output = model_suite.primary_electrical.evaluate_output(
                values_to_model_units(specs, evaluation.parameters),
                frequency,
                metric_builder=lambda response: {},
            )
            assert output.response is not None
            response = output.response
            responses.append((point_id, response))
            roles: list[str] = []
            if index == recommended_index:
                roles.append("recommended")
            for objective_index, spec in enumerate(objective_specs):
                if index == int(best_by_objective[objective_index]):
                    roles.append(f"best__{spec.name}")
            row: dict[str, Any] = {
                "point_id": point_id,
                "recommended": str(index == recommended_index).lower(),
                "role": ",".join(roles),
            }
            for spec in specs:
                row[f"parameter__{spec.name}__{spec.unit}"] = evaluation.parameters[
                    spec.name
                ]
                row[f"model_parameter__{spec.name}__{spec.model_unit}"] = (
                    evaluation.parameters[spec.name] * spec.scale_to_model
                )
            for objective_index, spec in enumerate(objective_specs):
                row[f"objective__{spec.name}__raw"] = evaluation.details[
                    f"objective_raw__{spec.name}"
                ]
                row[f"objective__{spec.name}__F"] = evaluation.objectives[
                    objective_index
                ]
                row[f"objective__{spec.name}__band_start_ghz"] = (
                    "" if spec.start_ghz is None else spec.start_ghz
                )
                row[f"objective__{spec.name}__band_stop_ghz"] = (
                    "" if spec.stop_ghz is None else spec.stop_ghz
                )
            for constraint_index, name in enumerate(constraint_names):
                row[f"constraint__{name}__raw_violation"] = evaluation.details.get(
                    f"constraint_raw__{name}", ""
                )
                row[f"constraint__{name}__G"] = evaluation.constraints[
                    constraint_index
                ]
                row[f"constraint__{name}__pass"] = str(
                    evaluation.constraints[constraint_index] <= 0.0
                ).lower()
            for metric_name in baseline_analysis:
                row[f"metric__{metric_name}"] = evaluation.details.get(metric_name, "")
            pareto_rows.append(row)

        recommended = optimization.pareto[recommended_index]
        recommended_response = responses[recommended_index + 1][1]
        recommended_raw_objectives = np.asarray(
            [
                recommended.details[f"objective_raw__{spec.name}"]
                for spec in objective_specs
            ],
            dtype=np.float64,
        )
        objective_improvements: dict[str, dict[str, Any]] = {}
        for spec, baseline_raw, recommended_raw in zip(
            objective_specs,
            baseline_raw_objectives,
            recommended_raw_objectives,
            strict=True,
        ):
            if spec.direction == "min":
                improvement_value = float(baseline_raw - recommended_raw)
            elif spec.direction == "max":
                improvement_value = float(recommended_raw - baseline_raw)
            else:
                assert spec.target is not None
                improvement_value = float(
                    abs(baseline_raw - spec.target)
                    - abs(recommended_raw - spec.target)
                )
            objective_improvements[spec.name] = {
                "baseline_raw": float(baseline_raw),
                "recommended_raw": float(recommended_raw),
                "improvement_toward_goal": improvement_value,
                "unit": spec.unit,
                "direction": spec.direction,
            }
        # 兼容旧版界面的两个固定电性能摘要仍保留；通用前端优先读取上面的
        # configured_objectives，并按每个目标自己的方向解释“朝目标改善”。
        baseline_worst = float(baseline_analysis["worst_s11_magnitude"])
        recommended_worst = float(recommended.details["worst_s11_magnitude"])
        baseline_mean_power = float(baseline_analysis["mean_reflected_power"])
        recommended_mean_power = float(recommended.details["mean_reflected_power"])
        worst_improvement_db = float(
            20.0 * np.log10(baseline_worst / max(recommended_worst, 1e-20))
        )
        mean_reduction_percent = float(
            100.0
            * (baseline_mean_power - recommended_mean_power)
            / baseline_mean_power
        )
        improvement = {
            "configured_objectives": objective_improvements,
            "worst_s11_improvement_db": worst_improvement_db,
            "mean_power_reduction_percent": mean_reduction_percent,
            "phase_weighted_rms_deg": float(
                recommended.details["phase_weighted_rms_deg"]
            ),
            "phase_reliable_max_deg": float(
                recommended.details["phase_reliable_max_deg"]
            ),
            "worse_frequency_fraction": float(
                recommended.details["worse_frequency_fraction"]
            ),
        }

        # 固定文件编号让二次开发者和前端无需猜测文件名：01 为解集，02 为全曲线，
        # 03 为 Pareto 总图，04~11 为四个二端口 S 参数的幅相对比图。
        _write_pareto_csv(run_directory / "01_pareto.csv", pareto_rows)
        write_sparameter_curves(
            run_directory / "02_sparameters.csv",
            responses,
            baseline_response,
            phase_floor_db=float(electrical["phase_reliable_floor_db"]),
        )
        plot_pareto(
            run_directory / "03_pareto.png",
            raw_objective_matrix,
            point_ids,
            recommended_index,
            baseline_raw_objectives,
            objective_names=[item.name for item in objective_specs],
            objective_units=[item.unit for item in objective_specs],
            objective_directions=[item.direction for item in objective_specs],
            objective_targets=[item.target for item in objective_specs],
        )
        sparameter_plot_paths = plot_sparameter_comparisons(
            run_directory,
            baseline_response,
            recommended_response,
            point_id=recommended_id,
            phase_floor_db=float(electrical["phase_reliable_floor_db"]),
        )
        if debug:
            _write_debug_log(
                run_directory / "debug_evaluations.csv",
                optimization.records,
                [item.name for item in specs],
                objective_specs,
                constraint_names,
                list(baseline_analysis),
            )

        # summary 是一次运行的索引和审计记录：既保存最终推荐，也保存解析后的配置、
        # 输入/源码哈希、环境版本、模型能力和所有输出文件清单。
        summary = {
            "schema_version": "2.3",
            "status": "completed",
            "validation_status": "surrogate_only",
            "run_id": run_directory.name,
            "surrogate_model_sha256": surrogate_model_sha256(),
            "optimization_source_sha256": optimization_source_sha256(),
            "input_file_sha256": {
                "config.toml": file_sha256(config_path),
                resolved_parameters_path.name: file_sha256(resolved_parameters_path),
                "objectives.csv": file_sha256(objectives_path),
                "constraints.csv": file_sha256(constraints_path),
                "models.csv": file_sha256(models_path),
            },
            "environment": environment_versions(),
            "resolved_config": config,
            "algorithm": {
                "name": algorithm_name,
                "population": selected_size,
                "generations": selected_iterations,
                "search_size": selected_size,
                "search_size_label": {
                    "NSGA-III": "population",
                    "MOPSO": "particles",
                    "MOSA": "chains",
                }[algorithm_name],
                "iterations": selected_iterations,
                "iteration_label": {
                    "NSGA-III": "generations",
                    "MOPSO": "iterations",
                    "MOSA": "temperature_iterations",
                }[algorithm_name],
                "seed": settings.seed,
                "neighborhood_samples": settings.neighborhood_samples,
                "neighborhood_fraction": settings.neighborhood_fraction,
                "archive_size": (
                    settings.resolved_archive_size(algorithm_name)
                    if algorithm_name in {"MOPSO", "MOSA"}
                    else None
                ),
                "algorithm_specific": (
                    {
                        "inertia_start": settings.inertia_start,
                        "inertia_end": settings.inertia_end,
                        "cognitive": settings.cognitive,
                        "social": settings.social,
                        "velocity_limit": settings.velocity_limit,
                    }
                    if algorithm_name == "MOPSO"
                    else {
                        "initial_temperature": settings.initial_temperature,
                        "final_temperature": settings.final_temperature,
                        "step_start": settings.step_start,
                        "step_end": settings.step_end,
                        "leader_pull": settings.leader_pull,
                    }
                    if algorithm_name == "MOSA"
                    else {}
                ),
                "evaluations": optimization.evaluations,
                "pareto_points": len(optimization.pareto),
                "quick_mode": quick,
            },
            "frequency": {
                "start_hz": float(frequency[0]),
                "stop_hz": float(frequency[-1]),
                "points": int(frequency.size),
            },
            "parameters": [
                {
                    "name": item.name,
                    "unit": item.unit,
                    "model_unit": item.model_unit,
                    "scale_to_model": item.scale_to_model,
                    "active": item.active,
                    "baseline": item.baseline,
                    "lower": item.lower,
                    "upper": item.upper,
                }
                for item in specs
            ],
            "objectives": [
                {
                    "name": item.name,
                    "expression": item.expression,
                    "direction": item.direction,
                    "target": item.target,
                    "recommendation_weight": item.recommendation_weight,
                    "band": (
                        {"scope": "full", "start_ghz": None, "stop_ghz": None}
                        if item.band_ghz is None
                        else {
                            "scope": "local",
                            "start_ghz": item.start_ghz,
                            "stop_ghz": item.stop_ghz,
                        }
                    ),
                    "unit": item.unit,
                    "description": item.description,
                }
                for item in objective_specs
            ],
            "constraints": [
                {
                    "name": item.name,
                    "stage": "post_prediction"
                    if item.requires_metrics
                    else "pre_prediction",
                    "left_expression": item.left_expression,
                    "operator": item.operator,
                    "right_expression": item.right_expression,
                    "tolerance": item.tolerance,
                    "unit": item.unit,
                    "description": item.description,
                    "baseline_raw_violation": float(
                        baseline_constraint_raw[index]
                    ),
                    "normalization_scale": float(constraint_scales[index]),
                    "baseline_G": float(baseline_constraint_g[index]),
                    "baseline_pass": bool(baseline_constraint_g[index] <= 0.0),
                }
                for index, item in enumerate(active_constraint_specs)
            ],
            "model_settings": {
                "selected_model_id": model_binding.model_id,
                "structure": model_binding.structure,
                "discipline": model_binding.discipline,
                "adapter": model_binding.adapter,
                "parameters_file": model_binding.parameters_file,
                "resolved_parameters_path": str(resolved_parameters_path),
                "reference_impedance_ohm": float(
                    model_config["reference_impedance_ohm"]
                ),
                "shunt_regularization": float(
                    model_config["shunt_regularization"]
                ),
            },
            "model_capabilities": model_catalog.capabilities(),
            "sparameter_reports": {
                "curve_csv": "02_sparameters.csv",
                "comparison_plots": [path.name for path in sparameter_plot_paths],
            },
            "selection_weights": {
                item.name: float(weight)
                for item, weight in zip(objective_specs, weights, strict=True)
            },
            "baseline": {
                "parameters": baseline_display,
                "configured_objectives_raw": {
                    item.name: float(value)
                    for item, value in zip(
                        objective_specs, baseline_raw_objectives, strict=True
                    )
                },
                "configured_objectives_F": {
                    item.name: float(value)
                    for item, value in zip(
                        objective_specs, baseline_objectives, strict=True
                    )
                },
                "configured_constraints_feasible": baseline_constraint_feasible,
                "worst_s11_magnitude": baseline_worst,
                "minimum_return_loss_db": float(
                    -20.0 * np.log10(max(baseline_worst, 1e-20))
                ),
                "mean_reflected_power": baseline_mean_power,
            },
            "recommended_point_id": recommended_id,
            "recommended_parameters": {
                "display_units": recommended.parameters,
                "model_units": values_to_model_units(specs, recommended.parameters),
            },
            "recommended_improvement": improvement,
            "warnings": [
                "结果仅由等效电路代理模型预测，尚未通过 HFSS 验证。",
                *[
                    f"{item.discipline} 模型状态为 not_connected；未生成任何该学科指标。"
                    for item in model_catalog.bindings
                    if item.status == "not_connected"
                ],
                *(
                    ["基准设计未满足 constraints.csv 的全部用户约束；优化仍继续寻找可行方案。"]
                    if not baseline_constraint_feasible
                    else []
                ),
                "当前上下界是基准值上下约10%的演示范围，不是正式制造边界。",
                "Gsub 单位、Rlf1 公式/钳位及固定10 GHz元件参数的宽带适用性仍待原作者确认。",
            ],
        }
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return run_directory
    except Exception as exc:
        # 失败也落盘一个结构稳定的 summary，便于网页展示错误且不影响其他运行目录。
        summary_path.write_text(
            json.dumps(
                {
                    "schema_version": "2.3",
                    "status": "failed",
                    "validation_status": "surrogate_only",
                    "error": str(exc),
                    "traceback": traceback.format_exc() if debug else None,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise


def _arguments() -> argparse.Namespace:
    """定义命令行参数；网页后端最终也复用同一个 ``execute`` 入口。"""

    parser = argparse.ArgumentParser(
        description="V2 CSV驱动的通用多目标优化（NSGA-III/MOPSO/MOSA）；默认输出5个结果文件。"
    )
    parser.add_argument("--check", action="store_true", help="只检查基准代理模型")
    parser.add_argument("--quick", action="store_true", help="16个体×5代快速联调")
    parser.add_argument("--debug", action="store_true", help="额外保存全部候选日志")
    parser.add_argument("--config", default=str(CONFIG_ROOT / "config.toml"))
    parser.add_argument(
        "--parameters",
        default=None,
        help="显式参数表；省略时使用 models.csv 当前结构绑定的 parameters_file",
    )
    parser.add_argument("--objectives", default=str(CONFIG_ROOT / "objectives.csv"))
    parser.add_argument("--constraints", default=str(CONFIG_ROOT / "constraints.csv"))
    parser.add_argument("--models", default=str(CONFIG_ROOT / "models.csv"))
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "results"))
    return parser.parse_args()


def main() -> int:
    """命令行入口：``--check`` 做基准自检，其余情况创建一次优化运行。"""

    arguments = _arguments()
    try:
        if arguments.check:
            analysis = check_baseline(
                arguments.config,
                arguments.parameters,
                arguments.objectives,
                arguments.constraints,
                arguments.models,
            )
            print("基准代理模型检查通过。")
            if analysis["baseline_constraint_feasible"]:
                print("基准设计满足 constraints.csv 中的全部已启用约束。")
            else:
                failed_names = [
                    item["name"]
                    for item in analysis["baseline_constraint_results"]
                    if not item["pass"]
                ]
                print(
                    "警告：基准设计不满足 constraints.csv 的全部约束；"
                    "优化时会继续寻找可行方案。"
                )
                print("基准未通过约束：" + ", ".join(failed_names))
            print(
                f"最坏 S11={20*np.log10(analysis['worst_s11_magnitude']):.3f} dB，"
                f"平均反射功率={100*analysis['mean_reflected_power']:.4f}%"
            )
            return 0
        run_directory = execute(
            config_path=arguments.config,
            parameters_path=arguments.parameters,
            objectives_path=arguments.objectives,
            constraints_path=arguments.constraints,
            models_path=arguments.models,
            output_root=arguments.output_root,
            quick=arguments.quick,
            debug=arguments.debug,
        )
        print(f"优化完成：{run_directory}")
        print("先看 00_summary.json 和 03_pareto.png；二端口曲线见 02_sparameters.csv 和 8 张对比图。")
        return 0
    except Exception as exc:
        print(f"运行失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

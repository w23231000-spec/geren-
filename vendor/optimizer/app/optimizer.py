"""与具体代理模型无关的多目标优化算法层。

``run.py`` 会把任意结构/学科模型包装成 ``evaluator(parameters)`` 回调，本模块只看
参数上下界以及回调返回的 :class:`Evaluation`。因此后续更换电、热或可靠性代理时，
通常不需要修改这里。

三种算法共享同一数学约定：所有目标 ``F`` 都已转换为“越小越好”，所有不等式约束
均为 ``G <= 0`` 可行。候选计算失败会被包装成大惩罚值并缓存，单个坏点不会中断整个
搜索；最终结果只从全部历史中的可行非支配点构造。
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


_KNOWN_UNIT_SCALES = {
    ("m", "m"): 1.0,
    ("mm", "m"): 1e-3,
    ("um", "m"): 1e-6,
    ("nm", "m"): 1e-9,
}


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """``parameters.csv`` 中一行参数的强类型表示。

    ``baseline/lower/upper`` 使用便于人阅读的显示单位，``scale_to_model`` 只在调用
    代理前参与换算；``active=False`` 的参数始终保持基准值，不进入搜索向量。
    """

    name: str
    display_name: str
    active: bool
    unit: str
    model_unit: str
    baseline: float
    lower: float
    upper: float
    scale_to_model: float

    def validate(self) -> None:
        """检查数值有限、基准位于边界内，并校验已知长度单位换算。"""

        values = (self.baseline, self.lower, self.upper, self.scale_to_model)
        if not self.name or not all(np.isfinite(values)):
            raise ValueError(f"参数 {self.name!r} 的名称或数值无效")
        if self.lower >= self.upper:
            raise ValueError(f"参数 {self.name!r} 必须满足 lower < upper")
        if not self.lower <= self.baseline <= self.upper:
            raise ValueError(f"参数 {self.name!r} 的 baseline 不在上下界内")
        if self.scale_to_model <= 0.0:
            raise ValueError(f"参数 {self.name!r} 的 scale_to_model 必须大于 0")
        expected_scale = _KNOWN_UNIT_SCALES.get((self.unit.lower(), self.model_unit.lower()))
        if expected_scale is not None and not np.isclose(
            self.scale_to_model,
            expected_scale,
            rtol=0.0,
            atol=expected_scale * 1e-12,
        ):
            raise ValueError(
                f"参数 {self.name!r} 的 {self.unit}->{self.model_unit} 应使用 "
                f"scale_to_model={expected_scale:g}"
            )


@dataclass(slots=True)
class Evaluation:
    """一个候选方案的完整评价结果。

    ``objectives`` 形状为 ``(目标数,)``，且所有列均为最小化方向的 F；
    ``constraints`` 形状为 ``(约束数,)``，其中 G<=0 表示通过；``details`` 保存
    原始指标和原始约束违反量，避免优化用归一化数值污染展示结果。
    """

    parameters: dict[str, float]
    objectives: np.ndarray
    constraints: np.ndarray
    details: dict[str, float]
    status: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class OptimizerSettings:
    """三种算法共用及各自专属的运行参数。

    ``population/generations`` 对应 NSGA-III；``particles/iterations`` 对应 MOPSO；
    ``chains/iterations`` 对应 MOSA。可选项为空时通过下方属性回退到兼容旧配置的
    公共字段。
    """

    population: int
    generations: int
    seed: int
    neighborhood_samples: int
    neighborhood_fraction: float
    particles: int | None = None
    iterations: int | None = None
    inertia_start: float = 0.72
    inertia_end: float = 0.40
    cognitive: float = 1.55
    social: float = 1.55
    velocity_limit: float = 0.25
    archive_size: int | None = None
    chains: int | None = None
    initial_temperature: float = 1.0
    final_temperature: float = 0.03
    step_start: float = 0.19
    step_end: float = 0.01
    leader_pull: float = 0.12

    @property
    def mopso_particles(self) -> int:
        """返回 MOPSO 实际粒子数。"""

        return self.population if self.particles is None else self.particles

    @property
    def mosa_chains(self) -> int:
        """返回 MOSA 实际并行链数。"""

        return self.population if self.chains is None else self.chains

    @property
    def resolved_iterations(self) -> int:
        """返回 MOPSO/MOSA 实际迭代数。"""

        return self.generations if self.iterations is None else self.iterations

    def resolved_archive_size(self, algorithm: str) -> int:
        """返回外部 Pareto 档案容量，未配置时采用当前搜索个体数。"""

        if self.archive_size is not None:
            return self.archive_size
        return self.mopso_particles if algorithm == "MOPSO" else self.mosa_chains

    def validate(self, algorithm: str | None = None) -> None:
        """按所选算法验证公共设置及专属超参数，尽早报告配置错误。"""

        normalized = algorithm.strip().upper() if algorithm else None
        if normalized not in {None, "NSGA-III", "NSGA3", "MOPSO", "MOSA"}:
            raise ValueError(f"未知优化算法 {algorithm!r}")
        if self.population < 4 or self.generations < 1:
            raise ValueError("population 至少为 4，generations 至少为 1")
        initial_count = (
            self.mopso_particles
            if normalized == "MOPSO"
            else self.mosa_chains
            if normalized == "MOSA"
            else self.population
        )
        if not 0 <= self.neighborhood_samples < initial_count:
            raise ValueError("neighborhood_samples 必须小于当前算法的种群数量")
        if not 0.0 < self.neighborhood_fraction <= 1.0:
            raise ValueError("neighborhood_fraction 必须在 (0, 1] 内")
        if self.particles is not None and self.particles < 4:
            raise ValueError("particles 至少为 4")
        if self.chains is not None and self.chains < 4:
            raise ValueError("chains 至少为 4")
        if self.iterations is not None and self.iterations < 1:
            raise ValueError("iterations 至少为 1")
        if self.archive_size is not None and self.archive_size < 2:
            raise ValueError("archive_size 至少为 2")
        numeric = (
            self.inertia_start,
            self.inertia_end,
            self.cognitive,
            self.social,
            self.velocity_limit,
            self.initial_temperature,
            self.final_temperature,
            self.step_start,
            self.step_end,
            self.leader_pull,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("算法专属设置必须是有限数")
        if self.inertia_start < 0.0 or self.inertia_end < 0.0:
            raise ValueError("inertia_start/end 不能小于 0")
        if self.cognitive < 0.0 or self.social < 0.0:
            raise ValueError("cognitive/social 不能小于 0")
        if not 0.0 < self.velocity_limit <= 1.0:
            raise ValueError("velocity_limit 必须在 (0, 1] 内")
        if not self.initial_temperature >= self.final_temperature > 0.0:
            raise ValueError("温度必须满足 initial_temperature >= final_temperature > 0")
        if not self.step_start >= self.step_end > 0.0:
            raise ValueError("步长必须满足 step_start >= step_end > 0")
        if self.leader_pull < 0.0:
            raise ValueError("leader_pull 不能小于 0")


@dataclass(slots=True)
class OptimizationResult:
    """算法统一返回值。

    ``records`` 是去重后的全部评价历史，``pareto`` 是最终可行非支配子集；只有
    NSGA-III 会返回非空 ``reference_directions``。``evaluations`` 记录算法评价次数。
    """

    records: list[Evaluation]
    pareto: list[Evaluation]
    reference_directions: np.ndarray
    evaluations: int


def _bool(value: str) -> bool:
    """解析 CSV 中常见的布尔写法，并拒绝含糊值。"""

    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"active 必须为 true/false，实际为 {value!r}")


def load_parameter_specs(path: str | Path) -> list[ParameterSpec]:
    """读取并逐行校验参数表，保持 CSV 行顺序作为稳定参数顺序。"""

    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("parameters.csv 没有参数")
    specs: list[ParameterSpec] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            spec = ParameterSpec(
                name=(row.get("name") or "").strip(),
                display_name=(row.get("display_name") or "").strip(),
                active=_bool(row.get("active") or ""),
                unit=(row.get("unit") or "").strip(),
                model_unit=(row.get("model_unit") or "").strip(),
                baseline=float(row.get("baseline") or ""),
                lower=float(row.get("lower") or ""),
                upper=float(row.get("upper") or ""),
                scale_to_model=float(row.get("scale_to_model") or ""),
            )
            spec.validate()
        except Exception as exc:
            raise ValueError(f"parameters.csv 第 {row_number} 行无效：{exc}") from exc
        specs.append(spec)
    names = [item.name for item in specs]
    if len(set(names)) != len(names):
        raise ValueError("parameters.csv 中参数名重复")
    if not any(item.active for item in specs):
        raise ValueError("至少启用一个参数")
    return specs


def baseline_values(specs: Sequence[ParameterSpec]) -> dict[str, float]:
    """构造包含活动和固定参数的显示单位基准字典。"""

    return {item.name: item.baseline for item in specs}


def values_to_model_units(
    specs: Sequence[ParameterSpec],
    values: dict[str, float],
) -> dict[str, float]:
    """将显示单位参数字典逐项换算为代理模型要求的单位。"""

    return {item.name: float(values[item.name]) * item.scale_to_model for item in specs}


def nondominated_mask(objectives: np.ndarray) -> np.ndarray:
    """返回最小化目标矩阵中 Pareto 非支配行的布尔掩码。

    输入形状为 ``(候选数, 目标数)``。若存在另一行在所有目标上不差、且至少一个
    目标严格更好，则当前行被支配并标记为 ``False``。
    """

    values = np.asarray(objectives, dtype=np.float64)
    mask = np.ones(values.shape[0], dtype=bool)
    for index in range(values.shape[0]):
        dominated = np.all(values <= values[index], axis=1) & np.any(
            values < values[index], axis=1
        )
        if np.any(dominated):
            mask[index] = False
    return mask


def _initial_population(
    lower: np.ndarray,
    upper: np.ndarray,
    baseline: np.ndarray,
    settings: OptimizerSettings,
    *,
    population: int | None = None,
) -> np.ndarray:
    """生成覆盖全域、基准附近均有样本的初始搜索点。

    输出形状为 ``(个体数, 活动参数数)``：Sobol 序列覆盖参数盒，第一行强制放入
    基准方案，其后若干行按 ``neighborhood_fraction`` 在基准附近扰动。
    """

    from scipy.stats import qmc

    count = settings.population if population is None else population
    exponent = int(math.ceil(math.log2(count)))
    unit = qmc.Sobol(d=lower.size, scramble=True, seed=settings.seed).random_base2(exponent)
    sampling = qmc.scale(unit[:count], lower, upper)
    sampling[0] = baseline
    if settings.neighborhood_samples:
        generator = np.random.default_rng(settings.seed + 104729)
        offsets = generator.uniform(
            -settings.neighborhood_fraction,
            settings.neighborhood_fraction,
            size=(settings.neighborhood_samples, lower.size),
        ) * (upper - lower)
        sampling[1 : settings.neighborhood_samples + 1] = np.clip(
            baseline + offsets,
            lower,
            upper,
        )
    return sampling


class _EvaluationContext:
    """三种算法共享的边界、缓存与失败隔离层。

    算法内部只搜索活动参数组成的短向量，本类负责补回固定参数、裁剪边界、调用
    ``evaluator`` 并核对 F/G 的 shape。缓存键涵盖全部参数且保留 14 位小数，同一点
    不会重复运行代理模型。
    """

    def __init__(
        self,
        specs: Sequence[ParameterSpec],
        evaluator: Callable[[dict[str, float]], Evaluation],
        objective_count: int,
        constraint_count: int,
    ) -> None:
        """保存评价契约，并建立活动参数的 lower/upper/baseline 向量。"""

        if objective_count < 1:
            raise ValueError("objective_count 至少为 1")
        if constraint_count < 0:
            raise ValueError("constraint_count 不能小于 0")
        self.specs = list(specs)
        self.evaluator = evaluator
        self.objective_count = objective_count
        self.constraint_count = constraint_count
        self.active = [item for item in specs if item.active]
        if not self.active:
            raise ValueError("至少启用一个参数")
        self.lower = np.asarray([item.lower for item in self.active], dtype=np.float64)
        self.upper = np.asarray([item.upper for item in self.active], dtype=np.float64)
        self.baseline = np.asarray([item.baseline for item in self.active], dtype=np.float64)
        self.cache: dict[tuple[float, ...], Evaluation] = {}

    def vector_to_values(self, vector: np.ndarray) -> dict[str, float]:
        """把活动参数向量还原成包含固定参数的完整显示单位字典。"""

        values = baseline_values(self.specs)
        values.update(
            {
                item.name: float(value)
                for item, value in zip(self.active, vector, strict=True)
            }
        )
        return values

    def evaluate_once(self, vector: np.ndarray) -> Evaluation:
        """至多评价一次候选，并把局部异常转换为不可行惩罚结果。

        正常回调必须返回 ``F.shape == (objective_count,)`` 和
        ``G.shape == (constraint_count,)`` 且全部有限。任何模型异常、shape 错误或
        NaN/Inf 都只让当前点得到大惩罚，不会使整个优化提前退出。
        """

        clipped = np.clip(np.asarray(vector, dtype=np.float64), self.lower, self.upper)
        values = self.vector_to_values(clipped)
        key = tuple(round(values[item.name], 14) for item in self.specs)
        if key in self.cache:
            return self.cache[key]
        try:
            result = self.evaluator(values)
            result.objectives = np.asarray(result.objectives, dtype=np.float64)
            result.constraints = np.asarray(result.constraints, dtype=np.float64)
            if result.objectives.shape != (self.objective_count,):
                raise ValueError("目标数组形状不正确")
            if result.constraints.shape != (self.constraint_count,):
                raise ValueError("约束数组形状不正确")
            if not np.all(np.isfinite(result.objectives)) or not np.all(
                np.isfinite(result.constraints)
            ):
                raise ValueError("目标或约束包含 NaN/无穷大")
        except Exception as exc:
            result = Evaluation(
                parameters=values,
                objectives=np.full(self.objective_count, 1e12, dtype=np.float64),
                constraints=np.full(self.constraint_count, 1e6, dtype=np.float64),
                details={},
                status="failed",
                message=str(exc),
            )
        self.cache[key] = result
        return result


def _resolve_constraint_names(
    constraint_count: int,
    constraint_names: Sequence[str] | None,
) -> list[str]:
    """补齐默认约束名，并保证诊断名称数量与 G 列数一致。"""

    if constraint_names is None:
        return [f"constraint_{index + 1}" for index in range(constraint_count)]
    resolved = list(constraint_names)
    if len(resolved) != constraint_count:
        raise ValueError("constraint_names 长度必须等于 constraint_count")
    return resolved


def _total_constraint_violation(evaluation: Evaluation) -> float:
    """计算正违反量之和；失败点视为无限违反。"""

    if evaluation.status == "failed":
        return math.inf
    return float(np.sum(np.maximum(evaluation.constraints, 0.0)))


def _is_feasible(evaluation: Evaluation) -> bool:
    """判断评价是否成功、目标非惩罚值且所有 G<=0。"""

    return bool(
        evaluation.status != "failed"
        and np.all(np.isfinite(evaluation.objectives))
        and np.all(evaluation.objectives < 1e11)
        and np.all(evaluation.constraints <= 0.0)
    )


def _constraint_dominates(left: Evaluation, right: Evaluation) -> bool:
    """按 Deb 约束支配规则判断 ``left`` 是否优于 ``right``。

    可行解总是优于不可行解；两个可行解按最小化 Pareto 支配比较；两个不可行解
    则选择总正违反量更小者。MOPSO 的个体最优和 MOSA 的接受判断都复用此规则。
    """
    left_feasible = _is_feasible(left)
    right_feasible = _is_feasible(right)
    if left_feasible != right_feasible:
        return left_feasible
    if left_feasible:
        return bool(
            np.all(left.objectives <= right.objectives)
            and np.any(left.objectives < right.objectives)
        )
    return _total_constraint_violation(left) < _total_constraint_violation(right)


def _crowding_distance(objectives: np.ndarray) -> np.ndarray:
    """计算目标空间拥挤距离，用于保留 Pareto 前沿的分布多样性。"""

    values = np.asarray(objectives, dtype=np.float64)
    count = values.shape[0]
    if count <= 2:
        return np.full(count, np.inf)
    distance = np.zeros(count, dtype=np.float64)
    for column in range(values.shape[1]):
        order = np.argsort(values[:, column], kind="stable")
        distance[order[0]] = np.inf
        distance[order[-1]] = np.inf
        span = float(values[order[-1], column] - values[order[0], column])
        if span > 0.0:
            distance[order[1:-1]] += (
                values[order[2:], column] - values[order[:-2], column]
            ) / span
    return distance


def _external_archive(
    previous: Sequence[Evaluation],
    candidates: Sequence[Evaluation],
    *,
    limit: int,
) -> list[Evaluation]:
    """合并候选并更新有容量上限的外部非支配档案。

    先按参数去重并剔除失败/非有限点；若存在可行解，只保留可行非支配解，超出容量
    时按拥挤距离保留稀疏区域；若尚无可行解，则暂存总违反量最小的点，引导搜索靠近
    可行域。
    """
    unique: dict[tuple[tuple[str, float], ...], Evaluation] = {}
    for item in [*previous, *candidates]:
        key = tuple(sorted((name, round(float(value), 14)) for name, value in item.parameters.items()))
        unique[key] = item
    pool = [
        item
        for item in unique.values()
        if item.status != "failed"
        and np.all(np.isfinite(item.objectives))
        and np.all(np.isfinite(item.constraints))
    ]
    feasible = [item for item in pool if _is_feasible(item)]
    if feasible:
        matrix = np.vstack([item.objectives for item in feasible])
        archive = [
            item
            for item, keep in zip(feasible, nondominated_mask(matrix), strict=True)
            if keep
        ]
        if len(archive) > limit:
            crowding = _crowding_distance(np.vstack([item.objectives for item in archive]))
            keep = np.argsort(-crowding, kind="stable")[:limit]
            archive = [archive[int(index)] for index in keep]
    elif pool:
        best_violation = min(_total_constraint_violation(item) for item in pool)
        archive = [
            item
            for item in pool
            if np.isclose(_total_constraint_violation(item), best_violation, rtol=1e-12, atol=1e-15)
        ][:limit]
    else:
        archive = []
    archive.sort(key=lambda item: tuple(float(value) for value in item.objectives))
    return archive


def _select_archive_leader(
    archive: Sequence[Evaluation],
    context: _EvaluationContext,
    generator: np.random.Generator,
) -> np.ndarray:
    """从外部档案选择一个活动参数领导者。

    可行档案按拥挤距离加权抽样，稀疏区域更容易被选中；档案为空时退回基准向量。
    """

    if not archive:
        return context.baseline.copy()
    if len(archive) == 1 or not all(_is_feasible(item) for item in archive):
        selected = archive[int(generator.integers(len(archive)))]
    else:
        crowding = _crowding_distance(np.vstack([item.objectives for item in archive]))
        finite = crowding[np.isfinite(crowding)]
        replacement = (float(np.max(finite)) if finite.size else 1.0) + 1.0
        weights = np.where(np.isfinite(crowding), crowding + 1e-12, replacement)
        weights /= np.sum(weights)
        selected = archive[int(generator.choice(len(archive), p=weights))]
    return np.asarray(
        [selected.parameters[item.name] for item in context.active], dtype=np.float64
    )


def _finalize_result(
    context: _EvaluationContext,
    constraint_names: Sequence[str],
    reference_directions: np.ndarray,
    *,
    evaluations: int | None = None,
) -> OptimizationResult:
    """从全部缓存记录生成算法无关的最终结果。

    最终 Pareto 集只从可行历史中选取，而不局限于算法最后一代/最后位置。如果没有
    可行点，会列出始终为正的 G 及部分失败消息，帮助定位过严约束或代理异常。
    """

    records = list(context.cache.values())
    feasible = [item for item in records if _is_feasible(item)]
    if not feasible:
        evaluated = [item for item in records if item.status != "failed"]
        diagnostics: list[str] = []
        if evaluated and context.constraint_count:
            matrix = np.vstack([item.constraints for item in evaluated])
            for column, name in enumerate(constraint_names):
                computed = matrix[:, column]
                computed = computed[computed != 1e6]
                if computed.size and float(np.min(computed)) > 0.0:
                    diagnostics.append(f"{name}(最小G={float(np.min(computed)):.6g})")
        failed_messages = sorted(
            {item.message for item in records if item.status == "failed" and item.message}
        )
        suffix = ""
        if diagnostics:
            suffix += "；始终未满足：" + ", ".join(diagnostics)
        if failed_messages:
            suffix += "；计算失败：" + " | ".join(failed_messages[:3])
        raise RuntimeError(
            "优化结束但没有可行候选；请检查 parameters.csv 和 "
            f"constraints.csv{suffix}"
        )
    matrix = np.vstack([item.objectives for item in feasible])
    pareto = [
        item
        for item, keep in zip(feasible, nondominated_mask(matrix), strict=True)
        if keep
    ]
    pareto.sort(key=lambda item: tuple(float(value) for value in item.objectives))
    return OptimizationResult(
        records=records,
        pareto=pareto,
        reference_directions=np.asarray(reference_directions, dtype=np.float64),
        evaluations=len(records) if evaluations is None else int(evaluations),
    )


def run_nsga3(
    specs: Sequence[ParameterSpec],
    evaluator: Callable[[dict[str, float]], Evaluation],
    *,
    objective_count: int,
    constraint_count: int,
    constraint_names: Sequence[str] | None = None,
    settings: OptimizerSettings,
) -> OptimizationResult:
    """运行带约束 NSGA-III，并从全部可行历史构造最终 Pareto 集。

    流程为 Sobol/基准混合初始化 → 生成目标空间参考方向 → 交给 pymoo 完成选择、
    交叉和变异 → 从评价缓存重新提取可行非支配解。NSGA-III 的参考方向能在三个及
    更多目标时维持解集分布；pymoo 接口中的 ``out['F']`` 是统一最小化目标，
    ``out['G']`` 遵循 ``G<=0`` 可行。
    """

    from pymoo.algorithms.moo.nsga3 import NSGA3
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.optimize import minimize
    from pymoo.util.ref_dirs import get_reference_directions

    settings.validate("NSGA-III")
    resolved_constraint_names = _resolve_constraint_names(
        constraint_count, constraint_names
    )
    context = _EvaluationContext(specs, evaluator, objective_count, constraint_count)
    sampling = _initial_population(
        context.lower, context.upper, context.baseline, settings
    )
    reference_directions = np.asarray(
        get_reference_directions(
            "energy",
            objective_count,
            settings.population,
            seed=settings.seed,
        ),
        dtype=np.float64,
    )

    # 适配 pymoo 的逐点问题接口。所有模型调用仍经过 context，因此同一点可命中缓存，
    # 单点异常也只会变成惩罚 F/G。
    class Problem(ElementwiseProblem):
        """把本项目 Evaluation 适配为 pymoo 的 ElementwiseProblem。"""

        def __init__(self) -> None:
            """向 pymoo 声明活动参数数、F/G 列数及逐参数上下界。"""

            super().__init__(
                n_var=len(context.active),
                n_obj=objective_count,
                n_ieq_constr=constraint_count,
                xl=context.lower,
                xu=context.upper,
            )

        def _evaluate(self, x: np.ndarray, out: dict[str, np.ndarray], *args: object, **kwargs: object) -> None:
            """把一个活动参数向量的 F/G 写入 pymoo 输出字典。"""

            evaluation = context.evaluate_once(x)
            out["F"] = evaluation.objectives
            out["G"] = evaluation.constraints

    result = minimize(
        Problem(),
        NSGA3(
            ref_dirs=reference_directions,
            pop_size=settings.population,
            sampling=sampling,
            eliminate_duplicates=True,
        ),
        termination=("n_gen", settings.generations),
        seed=settings.seed,
        save_history=False,
        verbose=False,
    )
    return _finalize_result(
        context,
        resolved_constraint_names,
        reference_directions,
        evaluations=int(result.algorithm.evaluator.n_eval),
    )


def run_mopso(
    specs: Sequence[ParameterSpec],
    evaluator: Callable[[dict[str, float]], Evaluation],
    *,
    objective_count: int,
    constraint_count: int,
    constraint_names: Sequence[str] | None = None,
    settings: OptimizerSettings,
) -> OptimizationResult:
    """运行带约束的多目标粒子群 MOPSO。

    每个粒子保存当前位置、速度和个体最优；全局引导者从外部 Pareto 档案中按拥挤
    距离抽取。惯性权重随迭代线性变化，速度按参数跨度限幅，越界位置裁剪后反向衰减
    速度。每轮结束把新评价并入有限容量档案。
    """

    settings.validate("MOPSO")
    resolved_constraint_names = _resolve_constraint_names(
        constraint_count, constraint_names
    )
    context = _EvaluationContext(specs, evaluator, objective_count, constraint_count)
    generator = np.random.default_rng(settings.seed)
    particle_count = settings.mopso_particles
    iteration_count = settings.resolved_iterations
    archive_limit = settings.resolved_archive_size("MOPSO")
    positions = _initial_population(
        context.lower,
        context.upper,
        context.baseline,
        settings,
        population=particle_count,
    )
    span = context.upper - context.lower
    initial_velocity = min(0.05, settings.velocity_limit)
    velocities = generator.uniform(
        -initial_velocity, initial_velocity, size=positions.shape
    ) * span
    evaluations = [context.evaluate_once(position) for position in positions]
    personal_positions = positions.copy()
    personal_best = list(evaluations)
    archive = _external_archive([], evaluations, limit=archive_limit)

    for generation in range(1, iteration_count):
        # 惯性从 inertia_start 平滑过渡到 inertia_end：前期扩大探索，后期加强收敛。
        progress = (generation - 1) / max(iteration_count - 2, 1)
        inertia = settings.inertia_start + (
            settings.inertia_end - settings.inertia_start
        ) * progress
        for index in range(particle_count):
            # 标准 PSO 三项：惯性、朝个体历史最优移动、朝 Pareto 档案领导者移动。
            leader = _select_archive_leader(archive, context, generator)
            random_personal = generator.random(span.size)
            random_social = generator.random(span.size)
            velocities[index] = (
                inertia * velocities[index]
                + settings.cognitive
                * random_personal
                * (personal_positions[index] - positions[index])
                + settings.social * random_social * (leader - positions[index])
            )
            velocity_limit = settings.velocity_limit * span
            velocities[index] = np.clip(
                velocities[index], -velocity_limit, velocity_limit
            )
            proposed = positions[index] + velocities[index]
            boundary = (proposed < context.lower) | (proposed > context.upper)
            proposed = np.clip(proposed, context.lower, context.upper)
            # 撞到边界时反弹且衰减，避免粒子长期粘在上下界。
            velocities[index, boundary] *= -0.5
            candidate = context.evaluate_once(proposed)
            positions[index] = proposed
            evaluations[index] = candidate

            incumbent = personal_best[index]
            # 有明确约束支配关系时保留优者；互不支配时随机保留，避免只偏向某一目标。
            if _constraint_dominates(candidate, incumbent) or (
                not _constraint_dominates(incumbent, candidate)
                and generator.random() < 0.5
            ):
                personal_best[index] = candidate
                personal_positions[index] = proposed
        archive = _external_archive(
            archive, evaluations, limit=archive_limit
        )

    return _finalize_result(
        context,
        resolved_constraint_names,
        np.empty((0, objective_count), dtype=np.float64),
    )


def _mosa_accept(
    candidate: Evaluation,
    current: Evaluation,
    archive: Sequence[Evaluation],
    temperature: float,
    generator: np.random.Generator,
) -> bool:
    """按温度决定 MOSA 是否接受候选状态。

    支配当前点的候选必定接受；被当前点支配时，根据归一化目标退化或约束违反退化
    计算 Boltzmann 概率；互不支配时比较其被档案点支配的“压力”。温度越低，算法
    越不愿接受退化方案。
    """

    if _constraint_dominates(candidate, current):
        return True
    if _constraint_dominates(current, candidate):
        if _is_feasible(current) and _is_feasible(candidate):
            pool = [current.objectives, candidate.objectives]
            pool.extend(item.objectives for item in archive if _is_feasible(item))
            matrix = np.vstack(pool)
            span = np.maximum(np.ptp(matrix, axis=0), 1e-12)
            degradation = float(
                np.mean(np.maximum(candidate.objectives - current.objectives, 0.0) / span)
            )
        else:
            current_violation = _total_constraint_violation(current)
            candidate_violation = _total_constraint_violation(candidate)
            if not math.isfinite(candidate_violation):
                return False
            degradation = max(candidate_violation - current_violation, 0.0) / max(
                abs(current_violation), 1.0
            )
        probability = math.exp(-degradation / max(temperature, 1e-12))
        return bool(generator.random() < probability)

    candidate_pressure = sum(
        _constraint_dominates(item, candidate) for item in archive
    )
    current_pressure = sum(_constraint_dominates(item, current) for item in archive)
    if candidate_pressure < current_pressure:
        return True
    if candidate_pressure == current_pressure:
        return bool(generator.random() < 0.5)
    probability = math.exp(
        -(candidate_pressure - current_pressure)
        / (max(temperature, 1e-12) * max(len(archive), 1))
    )
    return bool(generator.random() < probability)


def run_mosa(
    specs: Sequence[ParameterSpec],
    evaluator: Callable[[dict[str, float]], Evaluation],
    *,
    objective_count: int,
    constraint_count: int,
    constraint_names: Sequence[str] | None = None,
    settings: OptimizerSettings,
) -> OptimizationResult:
    """运行带约束、带外部档案的多目标模拟退火 MOSA。

    多条链从 Sobol/基准混合样本并行出发。每轮按几何退火表降低温度、线性减小扰动
    步长，并以较弱的 ``leader_pull`` 朝档案领导者靠拢；候选经 :func:`_mosa_accept`
    决定是否替换当前状态，所有候选同时用于更新外部 Pareto 档案。
    """

    settings.validate("MOSA")
    resolved_constraint_names = _resolve_constraint_names(
        constraint_count, constraint_names
    )
    context = _EvaluationContext(specs, evaluator, objective_count, constraint_count)
    generator = np.random.default_rng(settings.seed)
    chain_count = settings.mosa_chains
    iteration_count = settings.resolved_iterations
    archive_limit = settings.resolved_archive_size("MOSA")
    positions = _initial_population(
        context.lower,
        context.upper,
        context.baseline,
        settings,
        population=chain_count,
    )
    current = [context.evaluate_once(position) for position in positions]
    archive = _external_archive([], current, limit=archive_limit)
    span = context.upper - context.lower

    for generation in range(1, iteration_count):
        # 温度采用几何下降，步长采用线性下降：前期允许跨区域探索，后期局部细化。
        progress = (generation - 1) / max(iteration_count - 2, 1)
        temperature = settings.initial_temperature * (
            settings.final_temperature / settings.initial_temperature
        ) ** progress
        step_scale = settings.step_start + (
            settings.step_end - settings.step_start
        ) * progress
        generation_candidates: list[Evaluation] = []
        for index in range(chain_count):
            # 提案由高斯随机游走与温度衰减的领导者吸引共同组成，并始终裁剪在参数域内。
            leader = _select_archive_leader(archive, context, generator)
            proposal = (
                positions[index]
                + generator.normal(0.0, step_scale, size=span.size) * span
                + settings.leader_pull
                * temperature
                * generator.random(span.size)
                * (leader - positions[index])
            )
            proposal = np.clip(proposal, context.lower, context.upper)
            candidate = context.evaluate_once(proposal)
            generation_candidates.append(candidate)
            if _mosa_accept(
                candidate, current[index], archive, temperature, generator
            ):
                positions[index] = proposal
                current[index] = candidate
        archive = _external_archive(
            archive, generation_candidates, limit=archive_limit
        )

    return _finalize_result(
        context,
        resolved_constraint_names,
        np.empty((0, objective_count), dtype=np.float64),
    )

"""S 参数指标、推荐点选择及结果图表输出。

代理模型通过 :class:`SParameterResponse` 提供 ``frequencies_hz``（形状 ``(N,)``）
和复数 ``s_parameters``（形状 ``(N, 2, 2)``）。矩阵索引采用
``[频点, 输出端口, 输入端口]``，因此 ``[:, 0, 1]`` 是 S12，``[:, 1, 0]`` 是 S21。

本模块保留两套数值语义：优化/约束使用的标量指标由 :func:`analyze_response` 计算；
面向人的报告仍显示原始 S11/S12/S21/S22 幅度和相位。相位仅在基准与候选幅度都高于
可靠性门限时显示，避免接近零幅度时无物理意义的相位跳变误导判断。
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .surrogate_adapter import SParameterResponse


def s11_db(values: np.ndarray) -> np.ndarray:
    """把任意复数 S 参数幅度换算为 dB；极小值钳位以避免 ``log(0)``。"""

    return 20.0 * np.log10(np.maximum(np.abs(values), 1e-20))


def circular_phase_difference_deg(
    candidate: np.ndarray,
    baseline: np.ndarray,
) -> np.ndarray:
    """计算候选相对基准的环形相位差，结果自然落在 ``[-180, 180]`` 度。"""

    return np.angle(candidate * np.conj(baseline), deg=True)


def analyze_response(
    response: SParameterResponse,
    baseline: SParameterResponse,
    *,
    phase_floor_db: float,
    passivity_tolerance: float,
) -> dict[str, float]:
    """把一条二端口宽带响应归纳为可用于目标/约束的标量指标。

    候选与基准必须使用同一频率网格。均值类指标采用频率积分而非简单算术平均，
    所以非均匀频点也能正确处理。主要指标包括：

    * S11/S22 的最坏幅度、平均反射功率和最小回波损耗；
    * S21/S12 的插入损耗与传输功率，以及互易性误差；
    * S11 相对基准的加权相位 RMS、可信区最大误差及变差频点比例；
    * 二端口最大奇异值和无源性违反量。

    返回值全部是有限 ``float``，键名即 ``objectives.csv``/``constraints.csv`` 中
    ``metric.<name>`` 可引用的指标名。
    """

    if not np.allclose(
        response.frequencies_hz,
        baseline.frequencies_hz,
        rtol=1e-12,
        atol=0.0,
    ):
        raise ValueError("候选与基准频率网格不一致")
    frequency = response.frequencies_hz
    bandwidth = float(frequency[-1] - frequency[0])

    def band_mean(values: np.ndarray) -> float:
        """对频率积分后除以带宽，得到适用于非均匀网格的频带均值。"""

        return float(np.trapezoid(values, frequency) / bandwidth)

    def loss_db(values: np.ndarray) -> np.ndarray:
        """计算回波/插入损耗；零幅度以有限的 400 dB 表示。"""

        return -20.0 * np.log10(np.maximum(np.abs(values), 1e-20))

    candidate_s11 = response.s_parameters[:, 0, 0]
    candidate_s12 = response.s_parameters[:, 0, 1]
    candidate_s21 = response.s_parameters[:, 1, 0]
    candidate_s22 = response.s_parameters[:, 1, 1]
    reference_s11 = baseline.s_parameters[:, 0, 0]

    s11_values_db = s11_db(candidate_s11)
    s21_values_db = s11_db(candidate_s21)

    magnitude_s11 = np.abs(candidate_s11)
    magnitude_s21 = np.abs(candidate_s21)
    magnitude_s22 = np.abs(candidate_s22)
    return_loss_s11_db = loss_db(candidate_s11)
    return_loss_s22_db = loss_db(candidate_s22)
    insertion_loss_s21_db = loss_db(candidate_s21)
    insertion_loss_s12_db = loss_db(candidate_s12)

    mean_power = band_mean(magnitude_s11**2)
    mean_s22_power = band_mean(magnitude_s22**2)
    mean_s21_power = band_mean(magnitude_s21**2)
    phase_difference = circular_phase_difference_deg(candidate_s11, reference_s11)
    # 以基准反射功率 |S11|² 加权：基准反射接近零处的相位本来就不稳定，不应主导
    # “保持原相位”的全带 RMS 指标。
    weights = np.abs(reference_s11) ** 2
    denominator = float(np.trapezoid(weights, frequency))
    if denominator > 0.0:
        weighted_phase_rms = float(
            np.sqrt(
                np.trapezoid(weights * phase_difference**2, frequency)
                / denominator
            )
        )
    else:
        weighted_phase_rms = float(np.sqrt(band_mean(phase_difference**2)))
    reliable = (s11_db(reference_s11) >= phase_floor_db) & (
        s11_db(candidate_s11) >= phase_floor_db
    )
    # 可信区要求基准和候选同时高于幅度门限。若完全没有可信频点，返回 180 度作为
    # 明确的最坏惩罚，而不是把空集合误判为零相位误差。
    reliable_maximum = (
        float(np.max(np.abs(phase_difference[reliable])))
        if np.any(reliable)
        else 180.0
    )
    worse_fraction = float(
        np.mean(magnitude_s11 > np.abs(reference_s11) + 1e-12)
    )
    singular_values = np.linalg.svd(response.s_parameters, compute_uv=False)
    maximum_singular_value = float(np.max(singular_values))
    # 对每个频点的 2x2 S 矩阵求最大奇异值。被动网络应满足 sigma_max <= 1；
    # tolerance 允许代理数值噪声，最终 passivity_violation <= 0 即通过。
    metrics = {
        "maximum_s11_db": float(np.max(s11_values_db)),
        "minimum_s11_db": float(np.min(s11_values_db)),
        "maximum_s21_db": float(np.max(s21_values_db)),
        "minimum_s21_db": float(np.min(s21_values_db)),
        "worst_s11_magnitude": float(np.max(magnitude_s11)),
        "mean_reflected_power": mean_power,
        "minimum_s11_return_loss_db": float(np.min(return_loss_s11_db)),
        "worst_s22_magnitude": float(np.max(magnitude_s22)),
        "mean_s22_reflected_power": mean_s22_power,
        "minimum_s22_return_loss_db": float(np.min(return_loss_s22_db)),
        "mean_s21_insertion_loss_db": band_mean(insertion_loss_s21_db),
        "worst_s21_insertion_loss_db": float(np.max(insertion_loss_s21_db)),
        "mean_s21_transmission_power": mean_s21_power,
        "mean_s12_insertion_loss_db": band_mean(insertion_loss_s12_db),
        "worst_s12_insertion_loss_db": float(np.max(insertion_loss_s12_db)),
        "reciprocity_error": float(np.max(np.abs(candidate_s21 - candidate_s12))),
        "phase_weighted_rms_deg": weighted_phase_rms,
        "phase_reliable_max_deg": reliable_maximum,
        "phase_reliable_fraction": float(np.mean(reliable)),
        "worse_frequency_fraction": worse_fraction,
        "maximum_singular_value": maximum_singular_value,
        "passivity_violation": maximum_singular_value - (1.0 + passivity_tolerance),
    }
    if not all(np.isfinite(value) for value in metrics.values()):
        raise ValueError("response metric calculation produced NaN or infinity")
    return metrics


def analyze_response_bands(
    response: SParameterResponse,
    baseline: SParameterResponse,
    bands_ghz: Sequence[tuple[float, float] | None],
    *,
    phase_floor_db: float,
    passivity_tolerance: float,
) -> dict[tuple[float, float] | None, dict[str, float]]:
    """对一条预测响应的每个唯一全频/局部频段各计算一次指标。

    ``None`` 表示使用完整响应，局部频段以 GHz 二元组为键。切片后仍要求至少两个
    频点，返回值可直接作为按频段求目标值的缓存。
    """
    analyses: dict[tuple[float, float] | None, dict[str, float]] = {}
    for band in dict.fromkeys(bands_ghz):
        if band is None:
            candidate = response
            reference = baseline
        else:
            start_ghz, stop_ghz = band
            mask = (response.frequencies_hz >= start_ghz * 1e9) & (
                response.frequencies_hz <= stop_ghz * 1e9
            )
            if int(np.count_nonzero(mask)) < 2:
                raise ValueError(
                    f"频段 [{start_ghz:g}, {stop_ghz:g}] GHz 至少需要覆盖 2 个频点"
                )
            candidate = SParameterResponse(
                response.frequencies_hz[mask], response.s_parameters[mask], response.source
            )
            reference = SParameterResponse(
                baseline.frequencies_hz[mask], baseline.s_parameters[mask], baseline.source
            )
        analyses[band] = analyze_response(
            candidate,
            reference,
            phase_floor_db=phase_floor_db,
            passivity_tolerance=passivity_tolerance,
        )
    return analyses


def select_recommended_index(
    objective_matrix: np.ndarray,
    weights: Sequence[float] | np.ndarray,
) -> int:
    """从 Pareto 集中选取加权距离归一化理想点最近的推荐解。

    输入 ``objective_matrix`` 形状为 ``(Pareto点数, 目标数)``，且已经统一为最小化
    方向。每列先按自身极差缩放到 0~1，再按非负权重计算到全零理想点的欧氏距离。
    常量列自动记为零，不会影响推荐。返回原矩阵中的行索引。
    """

    values = np.asarray(objective_matrix, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("objective_matrix must be a two-dimensional array")
    if values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("objective_matrix must contain at least one point and objective")
    if not np.all(np.isfinite(values)):
        raise ValueError("objective_matrix must contain only finite values")

    weight_values = np.asarray(weights, dtype=np.float64)
    if weight_values.ndim != 1:
        raise ValueError("weights must be a one-dimensional array")
    if weight_values.shape != (values.shape[1],):
        raise ValueError(
            "weights length must equal the number of objective columns "
            f"({values.shape[1]})"
        )
    if not np.all(np.isfinite(weight_values)):
        raise ValueError("weights must contain only finite values")
    if np.any(weight_values < 0.0):
        raise ValueError("weights must be non-negative")
    weight_sum = float(np.sum(weight_values))
    if not np.isfinite(weight_sum) or weight_sum <= 0.0:
        raise ValueError("at least one weight must be greater than zero")

    minimum = np.min(values, axis=0)
    with np.errstate(over="ignore", invalid="ignore"):
        span = np.max(values, axis=0) - minimum
    if not np.all(np.isfinite(span)):
        raise ValueError("objective_matrix ranges are too large to normalize")
    normalized = np.divide(
        values - minimum,
        span,
        out=np.zeros_like(values),
        where=span > 0.0,
    )
    normalized_weights = weight_values / weight_sum
    scores = np.sqrt(np.sum(np.square(normalized) * normalized_weights, axis=1))
    return int(np.argmin(scores))


def write_sparameter_curves(
    path: Path,
    responses: list[tuple[str, SParameterResponse]],
    baseline: SParameterResponse,
    *,
    phase_floor_db: float,
) -> None:
    """写出 BASELINE 与全部 Pareto 点的四组复数 S 参数长表。

    每个 ``point_id × frequency`` 占一行，同时保存实部、虚部、dB、相位、相位是否
    可信以及相对基准的环形相位差。CSV 保留旧版 S11 通用别名，供既有前端继续读取。
    """

    fieldnames = [
        "point_id",
        "frequency_hz",
    ]
    for name in ("s11", "s12", "s21", "s22"):
        fieldnames.extend(
            [
                f"{name}_real",
                f"{name}_imag",
                f"{name}_db",
                f"{name}_phase_deg",
                f"{name}_phase_valid",
                f"{name}_circular_phase_difference_deg",
            ]
        )
    # 保留旧版仅支持 S11 时使用的两个无前缀列，避免已有二次开发代码失效。
    fieldnames.extend(["phase_valid", "circular_phase_difference_deg"])
    indices = {"s11": (0, 0), "s12": (0, 1), "s21": (1, 0), "s22": (1, 1)}
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for point_id, response in responses:
            # 同一响应的四组曲线先向量化计算，再逐频点展开成 CSV 行，避免内层重复运算。
            series: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
            for name, (port_out, port_in) in indices.items():
                values = response.s_parameters[:, port_out, port_in]
                reference = baseline.s_parameters[:, port_out, port_in]
                candidate_db = s11_db(values)
                reference_db = s11_db(reference)
                valid = (reference_db >= phase_floor_db) & (
                    candidate_db >= phase_floor_db
                )
                series[name] = (
                    values,
                    candidate_db,
                    valid,
                    circular_phase_difference_deg(values, reference),
                )
            for index, frequency in enumerate(response.frequencies_hz):
                row: dict[str, str] = {
                    "point_id": point_id,
                    "frequency_hz": format(float(frequency), ".17g"),
                }
                for name in indices:
                    values, candidate_db, valid, difference = series[name]
                    row.update(
                        {
                            f"{name}_real": format(float(values[index].real), ".17g"),
                            f"{name}_imag": format(float(values[index].imag), ".17g"),
                            f"{name}_db": format(float(candidate_db[index]), ".17g"),
                            f"{name}_phase_deg": format(
                                float(np.angle(values[index], deg=True)), ".17g"
                            ),
                            f"{name}_phase_valid": str(bool(valid[index])).lower(),
                            f"{name}_circular_phase_difference_deg": format(
                                float(difference[index]), ".17g"
                            ),
                        }
                    )
                row["phase_valid"] = row["s11_phase_valid"]
                row["circular_phase_difference_deg"] = row[
                    "s11_circular_phase_difference_deg"
                ]
                writer.writerow(row)


def _objective_axis_label(
    name: str,
    unit: str,
    direction: str,
    target: float | None,
) -> str:
    """组合“名称、单位、优化方向/目标值”为完整坐标轴标签。"""

    label = name if not unit else f"{name} [{unit}]"
    if direction == "min":
        preference = "minimize"
    elif direction == "max":
        preference = "maximize"
    else:
        preference = f"target={target:.6g}"
    return f"{label} ({preference})"


def _canonical_plot_values(
    raw_values: np.ndarray,
    directions: Sequence[str],
    targets: Sequence[float | None],
) -> np.ndarray:
    """把原始目标值转为仅用于绘图归一化的“越小越好”表示。

    ``min`` 保持原值，``max`` 取负，``target`` 取到目标值的绝对距离。该转换只决定
    平行坐标中的偏好方向，不修改报表展示的原始指标。
    """

    canonical = np.empty_like(raw_values, dtype=np.float64)
    for column, (direction, target) in enumerate(
        zip(directions, targets, strict=True)
    ):
        if direction == "min":
            canonical[:, column] = raw_values[:, column]
        elif direction == "max":
            canonical[:, column] = -raw_values[:, column]
        else:
            assert target is not None
            canonical[:, column] = np.abs(raw_values[:, column] - target)
    return canonical


def plot_pareto(
    path: Path,
    objective_matrix: np.ndarray,
    point_ids: Sequence[str],
    recommended_index: int,
    baseline_objectives: np.ndarray,
    *,
    objective_names: Sequence[str],
    objective_units: Sequence[str],
    objective_directions: Sequence[str],
    objective_targets: Sequence[float | None] | None = None,
) -> None:
    """绘制包含基准点、Pareto 点和推荐点的静态总览图。

    一目标使用点列图，二目标使用传统二维 Pareto 散点/连线，三目标及以上使用
    归一化平行坐标（0 为该批数据中的最佳偏好，1 为最差）。输入矩阵保存原始目标
    值，函数结合每列 ``min/max/target`` 方向解释优劣，因此坐标轴仍保留真实单位。
    静态 PNG 是正式报告；网页中的可选 X/Y 交互图由前端另行绘制。
    """

    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    values = np.asarray(objective_matrix, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError(
            "objective_matrix must be a non-empty two-dimensional array"
        )
    if not np.all(np.isfinite(values)):
        raise ValueError("objective_matrix must contain only finite values")
    point_count, objective_count = values.shape

    baseline = np.asarray(baseline_objectives, dtype=np.float64)
    if baseline.shape != (objective_count,):
        raise ValueError(
            "baseline_objectives must contain one value per objective column"
        )
    if not np.all(np.isfinite(baseline)):
        raise ValueError("baseline_objectives must contain only finite values")

    ids = list(point_ids)
    if len(ids) != point_count:
        raise ValueError("point_ids length must equal the number of Pareto points")
    if any(not isinstance(point_id, str) or not point_id.strip() for point_id in ids):
        raise ValueError("point_ids must contain non-empty strings")
    if not isinstance(recommended_index, (int, np.integer)) or isinstance(
        recommended_index, (bool, np.bool_)
    ):
        raise ValueError("recommended_index must be an integer")
    recommended_index = int(recommended_index)
    if not 0 <= recommended_index < point_count:
        raise ValueError("recommended_index is outside the Pareto point range")

    names = list(objective_names)
    units = list(objective_units)
    if len(names) != objective_count or any(
        not isinstance(name, str) or not name.strip() for name in names
    ):
        raise ValueError(
            "objective_names must contain one non-empty name per objective"
        )
    if len(units) != objective_count or any(
        not isinstance(unit, str) for unit in units
    ):
        raise ValueError("objective_units must contain one string per objective")

    directions = [
        direction.strip().lower() if isinstance(direction, str) else ""
        for direction in objective_directions
    ]
    if len(directions) != objective_count or any(
        direction not in {"min", "max", "target"} for direction in directions
    ):
        raise ValueError(
            "objective_directions must contain min, max, or target for each objective"
        )

    if objective_targets is None:
        targets: list[float | None] = [None] * objective_count
    else:
        raw_targets = list(objective_targets)
        if len(raw_targets) != objective_count:
            raise ValueError(
                "objective_targets must contain one entry per objective"
            )
        targets = []
        for target in raw_targets:
            if target is None:
                targets.append(None)
            else:
                numeric_target = float(target)
                if not np.isfinite(numeric_target):
                    raise ValueError("objective_targets must be finite when provided")
                targets.append(numeric_target)
    if any(
        direction == "target" and target is None
        for direction, target in zip(directions, targets, strict=True)
    ):
        raise ValueError("each target objective requires a finite objective target")

    axis_labels = [
        _objective_axis_label(name, unit, direction, target)
        for name, unit, direction, target in zip(
            names, units, directions, targets, strict=True
        )
    ]

    if objective_count == 1:
        # 单目标模式主要用于兼容和诊断；正式多目标流程通常要求至少两个启用目标。
        figure, axis = plt.subplots(figsize=(8.2, 5.4), constrained_layout=True)
        x_values = np.arange(point_count)
        axis.scatter(x_values, values[:, 0], color="#2563eb", label="Pareto")
        axis.axhline(
            baseline[0],
            color="#6b7280",
            linestyle="--",
            linewidth=1.8,
            label="Baseline",
        )
        if directions[0] == "target":
            axis.axhline(
                targets[0],
                color="#16a34a",
                linestyle=":",
                linewidth=1.6,
                label="Target",
            )
        axis.scatter(
            [recommended_index],
            [values[recommended_index, 0]],
            marker="*",
            s=180,
            color="#d62728",
            label=f"Recommended ({ids[recommended_index]})",
            zorder=4,
        )
        if point_count <= 30:
            axis.set_xticks(x_values, ids, rotation=45, ha="right")
        else:
            axis.set_xlabel("Pareto point index")
        axis.set_ylabel(axis_labels[0])
        axis.set_title("Feasible Single-Objective Results")

    elif objective_count == 2:
        # 连线只连接 Pareto 解；基准作为独立方块显示，不会被误算入前沿。
        figure, axis = plt.subplots(figsize=(8.2, 6.0), constrained_layout=True)
        if point_count > 1:
            front_order = np.argsort(values[:, 0], kind="stable")
            axis.plot(
                values[front_order, 0],
                values[front_order, 1],
                color="#60a5fa",
                linewidth=1.6,
                alpha=0.8,
                label="Discrete Pareto front",
                zorder=1,
            )
        axis.scatter(
            values[:, 0],
            values[:, 1],
            color="#2563eb",
            label="Pareto points",
            zorder=2,
        )
        axis.scatter(
            [baseline[0]],
            [baseline[1]],
            marker="s",
            s=85,
            color="#6b7280",
            label="Baseline",
        )
        axis.scatter(
            [values[recommended_index, 0]],
            [values[recommended_index, 1]],
            marker="*",
            s=180,
            color="#d62728",
            label=f"Recommended ({ids[recommended_index]})",
            zorder=4,
        )
        if directions[0] == "target":
            axis.axvline(
                targets[0], color="#16a34a", linestyle=":", linewidth=1.4
            )
        if directions[1] == "target":
            axis.axhline(
                targets[1], color="#16a34a", linestyle=":", linewidth=1.4
            )
        for index, point_id in enumerate(ids):
            axis.annotate(
                point_id,
                (values[index, 0], values[index, 1]),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=8,
            )
        axis.set_xlabel(axis_labels[0])
        axis.set_ylabel(axis_labels[1])
        axis.set_title("Feasible Pareto Front")

    else:
        # 多目标量纲差异很大，先连同基准一起转成统一偏好并逐列归一化，再画平行坐标。
        all_raw = np.vstack([values, baseline])
        with np.errstate(over="ignore", invalid="ignore"):
            canonical = _canonical_plot_values(all_raw, directions, targets)
        if not np.all(np.isfinite(canonical)):
            raise ValueError("objective values are too large to normalize")
        minimum = np.min(canonical, axis=0)
        with np.errstate(over="ignore", invalid="ignore"):
            span = np.max(canonical, axis=0) - minimum
        if not np.all(np.isfinite(span)):
            raise ValueError("objective ranges are too large to normalize")
        normalized = np.divide(
            canonical - minimum,
            span,
            out=np.zeros_like(canonical),
            where=span > 0.0,
        )
        candidate_normalized = normalized[:-1]
        baseline_normalized = normalized[-1]
        x_values = np.arange(objective_count)
        figure, axis = plt.subplots(
            figsize=(max(9.0, 1.8 * objective_count), 6.2),
            constrained_layout=True,
        )
        candidate_alpha = max(0.08, min(0.35, 20.0 / point_count))
        for index, row in enumerate(candidate_normalized):
            axis.plot(
                x_values,
                row,
                color="#2563eb",
                alpha=candidate_alpha,
                linewidth=1.0,
                label="Pareto" if index == 0 else None,
            )
        axis.plot(
            x_values,
            baseline_normalized,
            color="#6b7280",
            linestyle="--",
            marker="s",
            linewidth=2.0,
            label="Baseline",
        )
        axis.plot(
            x_values,
            candidate_normalized[recommended_index],
            color="#d62728",
            marker="*",
            markersize=12,
            linewidth=2.4,
            label=f"Recommended ({ids[recommended_index]})",
            zorder=4,
        )
        axis.set_xticks(x_values, axis_labels, rotation=20, ha="right")
        axis.set_ylabel("Normalized preference (0 = best, 1 = worst)")
        axis.set_ylim(1.02, -0.02)
        axis.set_title("Feasible Pareto Front — Parallel Coordinates")

    axis.grid(True, linestyle="--", alpha=0.4)
    axis.legend(loc="best")
    figure.savefig(path, dpi=180)
    plt.close(figure)


def plot_comparison(
    path: Path,
    baseline: SParameterResponse,
    recommended: SParameterResponse,
    *,
    point_id: str,
    phase_floor_db: float,
    summary: dict[str, Any],
) -> None:
    """绘制旧版三联 S11 幅度、相位和相位差汇总图。

    当前正式报告使用 :func:`plot_sparameter_comparisons` 的八张独立图片，本函数保留
    给仍依赖旧式单图的二次开发代码。灰色背景代表相位不可信频段。
    """

    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    frequency_ghz = baseline.frequencies_hz / 1e9
    baseline_s11 = baseline.s_parameters[:, 0, 0]
    candidate_s11 = recommended.s_parameters[:, 0, 0]
    baseline_db = s11_db(baseline_s11)
    candidate_db = s11_db(candidate_s11)
    valid = (baseline_db >= phase_floor_db) & (candidate_db >= phase_floor_db)
    difference = circular_phase_difference_deg(candidate_s11, baseline_s11)

    figure, axes = plt.subplots(3, 1, figsize=(10.5, 10.0), sharex=True, constrained_layout=True)
    axes[0].plot(frequency_ghz, baseline_db, color="#6b7280", linewidth=1.9, label="Baseline")
    axes[0].plot(frequency_ghz, candidate_db, color="#d62728", linewidth=1.9, label=f"Optimized ({point_id})")
    axes[0].set_ylabel("S11 (dB)")
    axes[0].legend(loc="best")
    axes[0].set_title("S11 Magnitude and Phase Comparison")

    # 相位图只展示基准与候选都高于幅度门限的频点；灰底明确标出被屏蔽区间。
    for axis in axes[1:]:
        axis.fill_between(
            frequency_ghz,
            0.0,
            1.0,
            where=~valid,
            transform=axis.get_xaxis_transform(),
            color="#d1d5db",
            alpha=0.45,
            linewidth=0.0,
        )
    axes[1].plot(
        frequency_ghz,
        np.where(valid, np.angle(baseline_s11, deg=True), np.nan),
        color="#6b7280",
        linewidth=1.8,
        label="Baseline",
    )
    axes[1].plot(
        frequency_ghz,
        np.where(valid, np.angle(candidate_s11, deg=True), np.nan),
        color="#d62728",
        linewidth=1.8,
        label=f"Optimized ({point_id})",
    )
    axes[1].set_ylabel("S11 phase (deg)")
    axes[1].set_ylim(-190, 190)
    axes[1].legend(loc="best")

    axes[2].plot(
        frequency_ghz,
        np.where(valid, difference, np.nan),
        color="#2563eb",
        linewidth=1.8,
    )
    axes[2].axhline(0.0, color="black", linewidth=1.0)
    axes[2].set_ylabel("Circular phase difference (deg)")
    axes[2].set_xlabel("Frequency (GHz)")
    axes[2].set_ylim(-10, 10)
    for axis in axes:
        axis.grid(True, linestyle="--", alpha=0.4)
    text = (
        f"Worst S11 improvement: {summary['worst_s11_improvement_db']:.3f} dB | "
        f"Mean power reduction: {summary['mean_power_reduction_percent']:.2f}% | "
        f"Weighted phase RMS: {summary['phase_weighted_rms_deg']:.3f} deg"
    )
    axes[0].text(
        0.01,
        0.03,
        text,
        transform=axes[0].transAxes,
        fontsize=9,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85},
    )
    figure.savefig(path, dpi=180)
    plt.close(figure)


def plot_sparameter_comparisons(
    output_directory: Path,
    baseline: SParameterResponse,
    recommended: SParameterResponse,
    *,
    point_id: str,
    phase_floor_db: float,
) -> list[Path]:
    """输出二端口四个 S 参数各自的幅度/相位对比图，共八张。

    幅度始终以 dB 展示；相位只在基准与推荐点同时高于 ``phase_floor_db`` 的区域
    绘制，低幅度区以灰底标注并用 NaN 断开曲线。返回路径顺序固定为
    S11幅度/相位、S12幅度/相位、S21幅度/相位、S22幅度/相位。
    """

    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    if not np.allclose(
        baseline.frequencies_hz,
        recommended.frequencies_hz,
        rtol=1e-12,
        atol=0.0,
    ):
        raise ValueError("基准与推荐结果的频率网格不一致")
    frequency_ghz = baseline.frequencies_hz / 1e9
    definitions = (
        ("s11", 0, 0, "04", "S11"),
        ("s12", 0, 1, "06", "S12"),
        ("s21", 1, 0, "08", "S21"),
        ("s22", 1, 1, "10", "S22"),
    )
    written: list[Path] = []
    for name, port_out, port_in, magnitude_prefix, label in definitions:
        # 按 [输出端口, 输入端口] 取复数曲线；同一可信掩码用于基准和推荐相位，确保
        # 两条线只在可以公平比较的频点出现。
        reference = baseline.s_parameters[:, port_out, port_in]
        candidate = recommended.s_parameters[:, port_out, port_in]
        reference_db = s11_db(reference)
        candidate_db = s11_db(candidate)
        valid = (reference_db >= phase_floor_db) & (candidate_db >= phase_floor_db)

        magnitude_path = output_directory / f"{magnitude_prefix}_{name}_magnitude.png"
        figure, axis = plt.subplots(figsize=(9.2, 5.2), constrained_layout=True)
        axis.plot(
            frequency_ghz,
            reference_db,
            color="#6b7280",
            linewidth=1.9,
            label="Baseline",
        )
        axis.plot(
            frequency_ghz,
            candidate_db,
            color="#d62728",
            linewidth=1.9,
            label=f"Recommended ({point_id})",
        )
        axis.set_title(f"{label} Magnitude Comparison")
        axis.set_xlabel("Frequency (GHz)")
        axis.set_ylabel(f"{label} magnitude (dB)")
        axis.grid(True, linestyle="--", alpha=0.4)
        axis.legend(loc="best")
        figure.savefig(magnitude_path, dpi=180)
        plt.close(figure)
        written.append(magnitude_path)

        phase_prefix = f"{int(magnitude_prefix) + 1:02d}"
        phase_path = output_directory / f"{phase_prefix}_{name}_phase.png"
        figure, axis = plt.subplots(figsize=(9.2, 5.2), constrained_layout=True)
        axis.fill_between(
            frequency_ghz,
            0.0,
            1.0,
            where=~valid,
            transform=axis.get_xaxis_transform(),
            color="#d1d5db",
            alpha=0.45,
            linewidth=0.0,
            label="Below phase reliability floor",
        )
        axis.plot(
            frequency_ghz,
            np.where(valid, np.angle(reference, deg=True), np.nan),
            color="#6b7280",
            linewidth=1.8,
            label="Baseline",
        )
        axis.plot(
            frequency_ghz,
            np.where(valid, np.angle(candidate, deg=True), np.nan),
            color="#d62728",
            linewidth=1.8,
            label=f"Recommended ({point_id})",
        )
        axis.set_title(f"{label} Phase Comparison")
        axis.set_xlabel("Frequency (GHz)")
        axis.set_ylabel(f"{label} phase (deg)")
        axis.set_ylim(-190.0, 190.0)
        axis.grid(True, linestyle="--", alpha=0.4)
        axis.legend(loc="best")
        figure.savefig(phase_path, dpi=180)
        plt.close(figure)
        written.append(phase_path)
    return written

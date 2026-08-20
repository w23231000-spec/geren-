"""从九个几何参数到二端口复数 S 参数结果的统一仿真入口。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

if __package__:  # V2 以标准 Python 包方式导入
    from .circuit_topology import assemble_circuit_topology
    from .parameter_calculator import GeometryInputs, calculate_component_parameters
    from .s_parameter_simulator import simulate_s_parameters
else:  # 兼容原作者在本目录直接运行 test.py
    from circuit_topology import assemble_circuit_topology
    from parameter_calculator import GeometryInputs, calculate_component_parameters
    from s_parameter_simulator import simulate_s_parameters


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """一次 S 参数仿真的命名结果。

    ``frequencies_hz`` 是形状为 ``(N,)`` 的 ``float64`` 频率数组，单位 Hz；
    ``s_parameters`` 是形状为 ``(N, 2, 2)`` 的 ``complex128`` 原始复数矩阵。
    """

    frequencies_hz: np.ndarray
    s_parameters: np.ndarray


def simulate_from_geometry(
    *,
    sub_h: float,
    TSV_r: float,
    TSV_p: float,
    BGA_r: float,
    BGA_p: float,
    RDL_w_layer1: float,
    RDL_d_layer1: float,
    RDL_w_layer2: float,
    RDL_d_layer2: float,
    frequencies_hz: Sequence[float] | np.ndarray | None = None,
    reference_impedance: float = 50.0,
    shunt_regularization: float = 1e-8,
) -> SimulationResult:
    """从九个以米为单位的几何参数计算最终 S 参数。

    九个仅限关键字的几何参数为 ``sub_h``、``TSV_r``、``TSV_p``、
    ``BGA_r``、``BGA_p``、``RDL_w_layer1``、``RDL_d_layer1``、
    ``RDL_w_layer2`` 和 ``RDL_d_layer2``，单位全部为 m。

    省略 ``frequencies_hz`` 时使用当前 S 参数仿真器的默认频率扫描。返回的
    :class:`SimulationResult` 包含形状为 ``(N,)`` 的 ``float64`` 频率数组和
    形状为 ``(N, 2, 2)`` 的 ``complex128`` S 参数矩阵。其中矩阵索引
    ``[i, 0, 0]``、``[i, 0, 1]``、``[i, 1, 0]``、``[i, 1, 1]``
    分别表示第 i 个频点的 S11、S12、S21、S22。
    """

    geometry = GeometryInputs(
        sub_h=sub_h,
        TSV_r=TSV_r,
        TSV_p=TSV_p,
        BGA_r=BGA_r,
        BGA_p=BGA_p,
        RDL_w_layer1=RDL_w_layer1,
        RDL_d_layer1=RDL_d_layer1,
        RDL_w_layer2=RDL_w_layer2,
        RDL_d_layer2=RDL_d_layer2,
    )
    component_parameters = calculate_component_parameters(geometry)
    circuit_topology = assemble_circuit_topology(component_parameters)
    result_frequencies_hz, s_parameters = simulate_s_parameters(
        circuit_topology,
        frequencies_hz=frequencies_hz,
        reference_impedance=reference_impedance,
        shunt_regularization=shunt_regularization,
    )
    return SimulationResult(
        frequencies_hz=result_frequencies_hz,
        s_parameters=s_parameters,
    )


__all__ = [
    "SimulationResult",
    "simulate_from_geometry",
]

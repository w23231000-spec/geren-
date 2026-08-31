"""基于 JAX 的二端口集总参数电路 S 参数计算模块。

输入拓扑中电容、电感和电阻的 ``init_val`` 单位必须分别为 pF、nH 和 Ω。
本模块不包含参数优化；默认在 0.1 GHz 至 20 GHz 的 200 个频点进行仿真，
直接返回频率数组和原始复数 S 参数矩阵，不进行文件导出。
"""

from __future__ import annotations

import os

# 必须在导入 JAX 前限制底层数值库线程。
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

import jax
import jax.numpy as jnp
import numpy as np


jax.config.update("jax_enable_x64", True)


CircuitItem = Mapping[str, Any]
DEFAULT_FREQUENCIES_HZ = np.linspace(0.1e9, 20.0e9, 200, dtype=np.float64)
_COMPONENT_TYPE_CODES = {"R": 0, "L": 1, "C": 2}
_SIMULATOR_CACHE_SIZE = 8
_TOPOLOGY_CACHE_SIZE = 8


TopologyStructure = tuple[
    int,
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
    int,
    int,
]
RawTopologyStructure = tuple[
    tuple[tuple[int, int, int], ...],
    int,
    int,
]


def _validate_frequencies(frequencies_hz: Sequence[float] | np.ndarray) -> np.ndarray:
    frequencies = np.asarray(frequencies_hz, dtype=np.float64)
    if frequencies.ndim != 1 or frequencies.size == 0:
        raise ValueError("frequencies_hz 必须是一维非空数组")
    if not np.all(np.isfinite(frequencies)) or np.any(frequencies <= 0.0):
        raise ValueError("所有仿真频率必须是大于零的有限数值")
    if frequencies.size > 1 and np.any(np.diff(frequencies) <= 0.0):
        raise ValueError("仿真频率必须严格递增")
    return frequencies


def _preprocess_topology(
    components_table: Sequence[CircuitItem],
) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int]:
    if not isinstance(components_table, Sequence) or isinstance(
        components_table, (str, bytes)
    ):
        raise TypeError("components_table 必须是电路拓扑字典组成的序列")
    if not components_table:
        raise ValueError("电路拓扑不能为空")

    node_numbers: set[int] = set()
    port_nodes: dict[int, int] = {}
    passive_structure: list[tuple[int, int, int]] = []
    component_values: list[float] = []
    component_names: set[str] = set()

    for index, component in enumerate(components_table):
        if not isinstance(component, Mapping):
            raise TypeError(f"拓扑第 {index} 项必须是字典或其他映射对象")

        name = component.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"拓扑第 {index} 项缺少有效的 name")
        if name in component_names:
            raise ValueError(f"拓扑中存在重复的元器件名称 {name!r}")
        component_names.add(name)

        component_type = str(component.get("type", "")).upper()
        node1 = component.get("node1")
        if not isinstance(node1, int) or isinstance(node1, bool) or node1 < 0:
            raise ValueError(f"元器件 {name!r} 的 node1 必须是非负整数")

        if component_type == "PORT":
            port_num = component.get("port_num")
            if port_num not in (1, 2):
                raise ValueError(f"端口 {name!r} 的 port_num 必须是 1 或 2")
            if port_num in port_nodes:
                raise ValueError(f"拓扑中重复定义了端口 {port_num}")
            if node1 == 0:
                raise ValueError(f"端口 {name!r} 不能连接到地节点 0")
            port_nodes[port_num] = node1
            node_numbers.add(node1)
            continue

        if component_type not in _COMPONENT_TYPE_CODES:
            raise ValueError(
                f"元器件 {name!r} 的类型 {component_type!r} 不受支持；仅支持 R、L、C 和 PORT"
            )

        node2 = component.get("node2", 0)
        if not isinstance(node2, int) or isinstance(node2, bool) or node2 < 0:
            raise ValueError(f"元器件 {name!r} 的 node2 必须是非负整数")
        if node1 == node2:
            raise ValueError(f"元器件 {name!r} 的两个节点不能相同")

        init_val = component.get("init_val")
        if not isinstance(init_val, (int, float)) or isinstance(init_val, bool):
            raise ValueError(f"元器件 {name!r} 缺少数值型 init_val")
        value = float(init_val)
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError(f"元器件 {name!r} 的 init_val 必须是大于零的有限数值")

        node_numbers.update((node1, node2))
        passive_structure.append((_COMPONENT_TYPE_CODES[component_type], node1, node2))
        component_values.append(value)

    if set(port_nodes) != {1, 2}:
        raise ValueError("拓扑必须且只能定义端口 1 和端口 2")
    if not passive_structure:
        raise ValueError("拓扑中至少需要一个 R、L 或 C 元器件")

    structure = (tuple(passive_structure), port_nodes[1], port_nodes[2])
    (
        num_nodes,
        type_codes,
        node1_indices,
        node2_indices,
        port1_index,
        port2_index,
    ) = _preprocess_fixed_topology(structure)

    return (
        num_nodes,
        type_codes,
        node1_indices,
        node2_indices,
        np.asarray(component_values, dtype=np.float64),
        port1_index,
        port2_index,
    )


@lru_cache(maxsize=_TOPOLOGY_CACHE_SIZE)
def _preprocess_fixed_topology(
    structure: RawTopologyStructure,
) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, int, int]:
    """把不含数值的拓扑转换为节点索引，并有界缓存转换结果。"""

    passive_structure, port1_node, port2_node = structure
    node_numbers = {port1_node, port2_node}
    for _, node1, node2 in passive_structure:
        node_numbers.update((node1, node2))
    node_numbers.discard(0)
    sorted_nodes = sorted(node_numbers)
    node_map = {node: index for index, node in enumerate(sorted_nodes)}
    type_codes = np.asarray(
        [component_type for component_type, _, _ in passive_structure],
        dtype=np.int32,
    )
    node1_indices = np.asarray(
        [node_map[node1] if node1 != 0 else -1 for _, node1, _ in passive_structure],
        dtype=np.int32,
    )
    node2_indices = np.asarray(
        [node_map[node2] if node2 != 0 else -1 for _, _, node2 in passive_structure],
        dtype=np.int32,
    )
    return (
        len(sorted_nodes),
        type_codes,
        node1_indices,
        node2_indices,
        node_map[port1_node],
        node_map[port2_node],
    )


def _build_jax_simulator(
    num_nodes: int,
    type_codes: Sequence[int] | np.ndarray,
    node1_indices: Sequence[int] | np.ndarray,
    node2_indices: Sequence[int] | np.ndarray,
    port1_index: int,
    port2_index: int,
    reference_impedance: float,
    shunt_regularization: float,
):
    component_types = jnp.asarray(type_codes, dtype=jnp.int32)
    component_node1 = jnp.asarray(node1_indices, dtype=jnp.int32)
    component_node2 = jnp.asarray(node2_indices, dtype=jnp.int32)
    identity_2 = jnp.eye(2, dtype=jnp.complex128)
    port_excitation = jnp.zeros((num_nodes, 2), dtype=jnp.complex128)
    port_excitation = port_excitation.at[port1_index, 0].set(1.0)
    port_excitation = port_excitation.at[port2_index, 1].set(1.0)

    def calculate_single_frequency(
        frequency_hz: jax.Array, component_values: jax.Array
    ) -> jax.Array:
        angular_frequency = 2.0 * jnp.pi * frequency_hz
        admittances = jnp.where(
            component_types == _COMPONENT_TYPE_CODES["R"],
            1.0 / jnp.maximum(component_values, 1e-6),
            jnp.where(
                component_types == _COMPONENT_TYPE_CODES["L"],
                1.0 / (1j * angular_frequency * component_values * 1e-9),
                1j * angular_frequency * component_values * 1e-12,
            ),
        )

        nodal_admittance = jnp.eye(num_nodes, dtype=jnp.complex128) * shunt_regularization

        def stamp_component(index: int, matrix: jax.Array) -> jax.Array:
            node1 = component_node1[index]
            node2 = component_node2[index]
            admittance = admittances[index]
            safe_node1 = jnp.maximum(node1, 0)
            safe_node2 = jnp.maximum(node2, 0)

            matrix = matrix.at[safe_node1, safe_node1].add(
                jnp.where(node1 >= 0, admittance, 0.0)
            )
            matrix = matrix.at[safe_node2, safe_node2].add(
                jnp.where(node2 >= 0, admittance, 0.0)
            )
            mutual_admittance = jnp.where(
                (node1 >= 0) & (node2 >= 0), -admittance, 0.0
            )
            matrix = matrix.at[safe_node1, safe_node2].add(mutual_admittance)
            matrix = matrix.at[safe_node2, safe_node1].add(mutual_admittance)
            return matrix

        nodal_admittance = jax.lax.fori_loop(
            0, component_values.size, stamp_component, nodal_admittance
        )
        port_response = jnp.linalg.solve(nodal_admittance, port_excitation)
        port_impedance = port_response[jnp.asarray([port1_index, port2_index]), :]
        numerator = port_impedance - reference_impedance * identity_2
        denominator = port_impedance + reference_impedance * identity_2
        return jnp.linalg.solve(denominator.T, numerator.T).T

    return jax.jit(jax.vmap(calculate_single_frequency, in_axes=(0, None)))


def _topology_structure(
    num_nodes: int,
    type_codes: np.ndarray,
    node1_indices: np.ndarray,
    node2_indices: np.ndarray,
    port1_index: int,
    port2_index: int,
) -> TopologyStructure:
    """生成不含元器件数值的确定性拓扑缓存键。"""

    return (
        num_nodes,
        tuple(int(value) for value in type_codes),
        tuple(int(value) for value in node1_indices),
        tuple(int(value) for value in node2_indices),
        port1_index,
        port2_index,
    )


@lru_cache(maxsize=_SIMULATOR_CACHE_SIZE)
def _get_cached_simulator(
    structure: TopologyStructure,
    reference_impedance: float,
    shunt_regularization: float,
):
    """按固定拓扑和固定模型选项复用已 JIT 编译的仿真器。"""

    (
        num_nodes,
        type_codes,
        node1_indices,
        node2_indices,
        port1_index,
        port2_index,
    ) = structure
    return _build_jax_simulator(
        num_nodes,
        type_codes,
        node1_indices,
        node2_indices,
        port1_index,
        port2_index,
        reference_impedance,
        shunt_regularization,
    )


def simulate_s_parameters(
    components_table: Sequence[CircuitItem],
    frequencies_hz: Sequence[float] | np.ndarray | None = None,
    *,
    reference_impedance: float = 50.0,
    shunt_regularization: float = 1e-8,
) -> tuple[np.ndarray, np.ndarray]:
    """计算二端口 S 参数并在内存中返回原始复数矩阵。

    返回：
        frequencies：形状为 ``(N,)`` 的 ``float64`` 频率数组，单位 Hz。
        s_parameters：形状为 ``(N, 2, 2)`` 的 ``complex128`` 数组，其中
            ``s_parameters[i, 0, 0]`` 为 S11，``[i, 0, 1]`` 为 S12，
            ``[i, 1, 0]`` 为 S21，``[i, 1, 1]`` 为 S22。
    """

    frequencies = _validate_frequencies(
        DEFAULT_FREQUENCIES_HZ if frequencies_hz is None else frequencies_hz
    )
    if not np.isfinite(reference_impedance) or reference_impedance <= 0.0:
        raise ValueError("reference_impedance 必须是大于零的有限数值")
    if not np.isfinite(shunt_regularization) or shunt_regularization <= 0.0:
        raise ValueError("shunt_regularization 必须是大于零的有限数值")

    (
        num_nodes,
        type_codes,
        node1_indices,
        node2_indices,
        component_values,
        port1_index,
        port2_index,
    ) = _preprocess_topology(components_table)
    structure = _topology_structure(
        num_nodes,
        type_codes,
        node1_indices,
        node2_indices,
        port1_index,
        port2_index,
    )
    simulator = _get_cached_simulator(
        structure,
        float(reference_impedance),
        float(shunt_regularization),
    )
    s_parameters = np.asarray(
        simulator(
            jnp.asarray(frequencies, dtype=jnp.float64),
            jnp.asarray(component_values, dtype=jnp.float64),
        )
    )

    if s_parameters.shape != (frequencies.size, 2, 2):
        raise RuntimeError(f"S 参数矩阵形状异常：{s_parameters.shape}")
    if not np.all(np.isfinite(s_parameters)):
        raise RuntimeError("S 参数仿真结果中出现了非有限数值")
    return frequencies, s_parameters


def _main() -> None:
    if __package__:
        from .circuit_topology import build_test_circuit_topology
    else:
        from circuit_topology import build_test_circuit_topology

    topology = build_test_circuit_topology()
    frequencies, s_parameters = simulate_s_parameters(topology)
    print(f"S 参数仿真完成：{frequencies.size} 个频点")
    print(f"frequencies shape: {frequencies.shape}")
    print(f"S parameters shape: {s_parameters.shape}")
    print(f"S parameters dtype: {s_parameters.dtype}")
    print(f"第一个频率：{frequencies[0]:.6e} Hz")
    print("第一个频率点的 S 参数矩阵：")
    print(s_parameters[0])


__all__ = [
    "DEFAULT_FREQUENCIES_HZ",
    "simulate_s_parameters",
]


if __name__ == "__main__":
    _main()

"""组装电路拓扑，并向元器件字典写入计算后的 ``init_val``。

拓扑字典统一使用以下单位：电容为 pF，电感为 nH，电阻为 Ω。
本模块只提供可导入函数，不在导入时计算参数或打印结果。
"""

from __future__ import annotations

import math
from typing import Any

if __package__:  # V2 以标准 Python 包方式导入
    from .parameter_calculator import (
        ComponentParameters,
        GeometryInputs,
        calculate_component_parameters,
        parameters_to_dict,
    )
else:  # 兼容在本目录直接运行
    from parameter_calculator import (
        ComponentParameters,
        GeometryInputs,
        calculate_component_parameters,
        parameters_to_dict,
    )


CircuitItem = dict[str, Any]


# 拓扑模板只描述连接关系；init_val 由 assemble_circuit_topology 动态写入。
_TOPOLOGY_TEMPLATE: tuple[CircuitItem, ...] = (
    {"name": "Port1", "type": "PORT", "node1": 100, "port_num": 1},
    {"name": "Port2", "type": "PORT", "node1": 17, "port_num": 2},
    {"name": "C452", "type": "C", "node1": 6, "node2": 20, "optimize": True, "var_link": "Clf1"},
    {"name": "C442", "type": "C", "node1": 9, "node2": 5, "optimize": True, "var_link": "Cox"},
    {"name": "R389", "type": "R", "node1": 9, "node2": 3, "optimize": True, "var_link": "R0"},
    {"name": "L287", "type": "L", "node1": 4, "node2": 19, "optimize": True, "var_link": "Lbga1"},
    {"name": "C444", "type": "C", "node1": 7, "node2": 0, "optimize": True, "var_link": "Cox_8"},
    {"name": "C446", "type": "C", "node1": 0, "node2": 17, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "C438", "type": "C", "node1": 100, "node2": 0, "optimize": True, "var_link": "Crdl_pi_1"},
    {"name": "L281", "type": "L", "node1": 18, "node2": 16, "optimize": True, "var_link": "L1_2"},
    {"name": "C433", "type": "C", "node1": 0, "node2": 16, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "L282", "type": "L", "node1": 9, "node2": 4, "optimize": True, "var_link": "L0"},
    {"name": "C445", "type": "C", "node1": 3, "node2": 0, "optimize": True, "var_link": "Crdl_pi_1"},
    {"name": "C434", "type": "C", "node1": 0, "node2": 100, "optimize": True, "var_link": "Crdl_pi_1"},
    {"name": "C429", "type": "C", "node1": 4, "node2": 0, "optimize": True, "var_link": "Cimd2"},
    {"name": "C428", "type": "C", "node1": 3, "node2": 0, "optimize": True, "var_link": "Cimd1"},
    {"name": "C439", "type": "C", "node1": 0, "node2": 3, "optimize": True, "var_link": "Crdl_pi_1"},
    {"name": "C443", "type": "C", "node1": 5, "node2": 7, "optimize": True, "var_link": "Csub"},
    {"name": "C440", "type": "C", "node1": 0, "node2": 6, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "C436", "type": "C", "node1": 6, "node2": 0, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "C449", "type": "C", "node1": 0, "node2": 13, "optimize": True, "var_link": "Crdl_pi_3"},
    {"name": "C448", "type": "C", "node1": 12, "node2": 0, "optimize": True, "var_link": "Crdl_pi_3"},
    {"name": "C435", "type": "C", "node1": 0, "node2": 12, "optimize": True, "var_link": "Crdl_pi_3"},
    {"name": "C425", "type": "C", "node1": 8, "node2": 0, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "C426", "type": "C", "node1": 11, "node2": 0, "optimize": True, "var_link": "C2"},
    {"name": "C430", "type": "C", "node1": 13, "node2": 0, "optimize": True, "var_link": "Crdl_pi_3"},
    {"name": "R393", "type": "R", "node1": 19, "node2": 6, "optimize": True, "var_link": "Rbga1"},
    {"name": "C431", "type": "C", "node1": 0, "node2": 8, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "C447", "type": "C", "node1": 16, "node2": 0, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "C441", "type": "C", "node1": 15, "node2": 0, "optimize": True, "var_link": "C2"},
    {"name": "C432", "type": "C", "node1": 17, "node2": 0, "optimize": True, "var_link": "Crdl_pi_2"},
    {"name": "L276", "type": "L", "node1": 10, "node2": 6, "optimize": True, "var_link": "L1_2"},
    {"name": "L277", "type": "L", "node1": 2, "node2": 100, "optimize": True, "var_link": "L1_1"},
    {"name": "L285", "type": "L", "node1": 15, "node2": 16, "optimize": True, "var_link": "L2"},
    {"name": "L283", "type": "L", "node1": 13, "node2": 15, "optimize": True, "var_link": "L2"},
    {"name": "L278", "type": "L", "node1": 14, "node2": 12, "optimize": True, "var_link": "L1_3"},
    {"name": "L279", "type": "L", "node1": 11, "node2": 12, "optimize": True, "var_link": "L2"},
    {"name": "L280", "type": "L", "node1": 8, "node2": 11, "optimize": True, "var_link": "L2"},
    {"name": "R383", "type": "R", "node1": 3, "node2": 2, "optimize": True, "var_link": "R1_1"},
    {"name": "R384", "type": "R", "node1": 5, "node2": 7, "optimize": True, "var_link": "Rsub"},
    {"name": "R385", "type": "R", "node1": 8, "node2": 10, "optimize": True, "var_link": "R1_2"},
    {"name": "R386", "type": "R", "node1": 17, "node2": 18, "optimize": True, "var_link": "R1_2"},
    {"name": "R390", "type": "R", "node1": 13, "node2": 14, "optimize": True, "var_link": "R1_3"},
    {"name": "C453", "type": "C", "node1": 4, "node2": 0, "optimize": True, "var_link": "Cbga1"},
    {"name": "R394", "type": "R", "node1": 4, "node2": 20, "optimize": True, "var_link": "Rlf1"},
)


_CAPACITANCE_IN_FF = frozenset(
    {"Crdl_pi_1", "Crdl_pi_2", "Crdl_pi_3", "Cox", "Csub", "Cimd1", "Cimd2"}
)
_CAPACITANCE_IN_PF = frozenset({"C2", "Cbga1", "Clf1"})
_INDUCTANCE_IN_PH = frozenset({"L1_1", "L1_2", "L1_3", "L2", "L0", "Lbga1"})
_RESISTANCE_IN_OHM = frozenset({"R1_1", "R1_2", "R1_3", "Rbga1", "Rlf1"})
_RESISTANCE_IN_MILLIOHM = frozenset({"R0"})
_TOPOLOGY_UNITS = {"C": "pF", "L": "nH", "R": "Ω"}


def topology_parameter_values(parameters: ComponentParameters) -> dict[str, float]:
    """将计算结果转换为拓扑所需的 pF、nH 和 Ω，并生成派生参数。"""

    if not isinstance(parameters, ComponentParameters):
        raise TypeError("parameters 必须是 ComponentParameters 实例")

    source = parameters_to_dict(parameters)
    values: dict[str, float] = {}

    for name in _CAPACITANCE_IN_FF:
        values[name] = source[name] * 1e-3
    for name in _CAPACITANCE_IN_PF:
        values[name] = source[name]
    for name in _INDUCTANCE_IN_PH:
        values[name] = source[name] * 1e-3
    for name in _RESISTANCE_IN_OHM:
        values[name] = source[name]
    for name in _RESISTANCE_IN_MILLIOHM:
        values[name] = source[name] * 1e-3

    gsub_ks = source["Gsub"]
    if not math.isfinite(gsub_ks) or gsub_ks == 0.0:
        raise ValueError("Gsub 必须是非零有限数，才能计算 Rsub = 1 / (Gsub × 1000)")
    values["Rsub"] = 1.0 / (gsub_ks * 1e3)
    values["Cox_8"] = 8.0 * values["Cox"]

    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("拓扑参数中出现了非有限数值")
    return values


def assemble_circuit_topology(parameters: ComponentParameters) -> list[CircuitItem]:
    """复制拓扑模板，并根据 ``var_link`` 写入每个元器件的 ``init_val``。"""

    values = topology_parameter_values(parameters)
    topology: list[CircuitItem] = []

    for template_item in _TOPOLOGY_TEMPLATE:
        item = template_item.copy()
        var_link = item.get("var_link")
        if var_link is not None:
            if var_link not in values:
                raise KeyError(f"拓扑参数 {var_link!r} 没有对应的计算值")
            item["init_val"] = values[var_link]
        topology.append(item)

    return topology


def build_circuit_topology(inputs: GeometryInputs | None = None) -> list[CircuitItem]:
    """根据九个几何输入计算参数并组装拓扑；省略 inputs 时使用默认输入。"""

    geometry = GeometryInputs() if inputs is None else inputs
    parameters = calculate_component_parameters(geometry)
    return assemble_circuit_topology(parameters)


def build_test_circuit_topology() -> list[CircuitItem]:
    """使用指定的一组元器件参数组装测试拓扑。"""

    test_parameters = ComponentParameters(
        R1_1=0.000749530978229,
        L1_1=610.911485718,
        Crdl_pi_1=66.9585260285,
        R1_2=0.000217729833683,
        L1_2=404.058109413,
        Crdl_pi_2=57.2013611026,
        R1_3=0.00148012575269,
        L1_3=2.65118172,
        Crdl_pi_3=0.364384615464,
        C2=0.00148713192872,
        L2=2.10382830383,
        R0=1026.08545648,
        L0=756.365514378,
        Cox=17.0045335797,
        Csub=0.0460543685887,
        Gsub=2.32169507655e-06,
        Cimd1=110.753986112,
        Cimd2=3.44785631496,
        Rbga1=1203261.87906,
        Lbga1=1306854.19482,
        Cbga1=0.362330665365,
        Clf1=0.0928406408951,
        Rlf1=2.61546364505e-09,
    )
    return assemble_circuit_topology(test_parameters)


def topology_final_parameters(
    topology: list[CircuitItem],
) -> dict[str, tuple[float, str]]:
    """按拓扑中的首次出现顺序返回不重复的参数值及其单位。"""

    final_parameters: dict[str, tuple[float, str]] = {}
    for item in topology:
        var_link = item.get("var_link")
        if var_link is None:
            continue

        component_type = item.get("type")
        if component_type not in _TOPOLOGY_UNITS:
            raise ValueError(f"元器件 {item.get('name')!r} 的类型 {component_type!r} 不受支持")
        if "init_val" not in item:
            raise KeyError(f"元器件 {item.get('name')!r} 缺少 init_val")

        parameter = (float(item["init_val"]), _TOPOLOGY_UNITS[component_type])
        previous = final_parameters.get(var_link)
        if previous is not None and previous != parameter:
            raise ValueError(f"参数 {var_link!r} 在拓扑中对应了不一致的值或单位")
        final_parameters[var_link] = parameter

    return final_parameters


def _main() -> None:
    test_table = build_test_circuit_topology()
    for name, (value, unit) in topology_final_parameters(test_table).items():
        print(f"{name} = {value:.12g} {unit}")


__all__ = [
    "assemble_circuit_topology",
    "build_circuit_topology",
    "build_test_circuit_topology",
    "topology_final_parameters",
    "topology_parameter_values",
]


if __name__ == "__main__":
    _main()

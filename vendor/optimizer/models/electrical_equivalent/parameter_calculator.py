"""根据九个几何输入计算唯一的元器件模型参数。

本模块把 ``1(4).txt`` 中的 ADS 公式直接转写为 Python。调用方只需提供
封装互连的几何尺寸；材料属性、模型状态、计算频率、固定长度和拟合系数
均属于内部模型常量，不是公共输入。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class GeometryInputs:
    """九个可变几何参数，单位统一为米（m）。"""

    sub_h: float = 200e-6  # 衬底厚度，m。
    TSV_r: float = 15e-6  # TSV 半径，m。
    TSV_p: float = 260e-6  # TSV 间距，m。
    BGA_r: float = 125e-6  # BGA 半径，m。
    BGA_p: float = 660e-6  # BGA 间距，m。
    RDL_w_layer1: float = 0.10e-3  # 上层 RDL 线宽，m。
    RDL_d_layer1: float = 0.05e-3  # 上层 RDL 线距，m。
    RDL_w_layer2: float = 0.08e-3  # 下层 RDL 线宽，m。
    RDL_d_layer2: float = 0.05e-3  # 下层 RDL 线距，m。


@dataclass(frozen=True, slots=True)
class ModelConstants:
    """来自 ``1(4).txt`` 的模型常量。"""

    mu0: float = 4.0 * math.pi * 1e-7  # 真空磁导率，H/m。
    eps0: float = 8.854e-12  # 真空介电常数，F/m。
    epsr_SI: float = 11.9  # 硅相对介电常数，无量纲。
    epsr_PI: float = 3.9  # PI 相对介电常数，无量纲。
    epsr_SiO2: float = 4.0  # SiO2 相对介电常数，无量纲。
    sigma_Cu: float = 5.8e7  # 铜电导率，S/m。
    sigma_SI: float = 0.001  # 硅电导率，S/m。
    sigma_Soder: float = 7_540_000.0  # 焊球电导率，S/m。
    rho_Cu: float = 1.72e-8  # 铜电阻率，Ω·m。
    rho_Soder: float = 1.0 / 7_540_000.0  # 焊球电阻率，Ω·m。
    mu_r_Soder: float = 1.0  # 焊球相对磁导率，无量纲。

    t: float = 0
    T: float = 6000.0
    f: float = 10e9
    n: int = 8
    K: float = 2.0
    a: float = 0.0

    t_RDL: float = 5e-6
    l1: float = 2.20e-3
    l2: float = 0.55e-3
    l3: float = 4.10e-3
    t_ox: float = 1e-6
    h_pi: float = 12e-6
    hsio2_1: float = 3e-6
    hsio2_2: float = 1e-6
    g_crack: float = 5e-6
    eps_r_crack: float = 1.0

    KR_0: float = 23.496
    KR_1: float = 14.8628
    KCo_0: float = 0.0470453
    KCo_1: float = 0.0246588
    KL_0: float = 4.32499
    KL_1: float = 5.93653
    KG_0: float = 5.12573
    KG_1: float = 5.31479
    KCsub_0: float = 0.00113126
    KCsub_1: float = 0.00100061
    KCimd1_0: float = 73.6459
    KCimd1_1: float = 99.8572
    KCimd2_0: float = 46.0876
    KCimd2_1: float = 45.6968
    KR1_0: float = 0.00111313
    KR1_1: float = 0.00129773
    KL1_0: float = 0.329439
    KL1_1: float = 0.649358
    KC1_0: float = 0.722164
    KC1_1: float = 1.71876
    KR22_0: float = 0.00110181
    KR22_1: float = 0.00120632
    KL22_0: float = 1.15459
    KL22_1: float = 2.20817
    KC22_0: float = 3.98065
    KC22_1: float = 7.34151
    KR3_0: float = 0.00171135
    KR3_1: float = 0.00110007
    KL3_0: float = 0.174269
    KL3_1: float = 0.00129671
    KC3_0: float = 0.9499
    KC3_1: float = 0.0062678
    KC2_0: float = 6.1831
    KC2_1: float = 0.069537
    KL2_0: float = 87.1405
    KL2_1: float = 0.713236
    KRbga_0: float = 0.0032873
    KRbga_1: float = 30920.6
    KLbga_0: float = 5.09973
    KLbga_1: float = 9.30123
    KCbga_0: float = 12.9692
    KCbga_1: float = 0.0127581
    KRlf_0: float = 12.3277
    KRlf_1: float = 2.00866
    KClf_0: float = 2.80437
    KClf_1: float = 1.06807
    eps_sw_0: float = 0.24378
    eps_sw_1: float = 0.000472208


@dataclass(frozen=True, slots=True)
class ComponentParameters:
    """源模型输出的元器件参数。"""

    R1_1: float
    L1_1: float
    Crdl_pi_1: float

    R1_2: float
    L1_2: float
    Crdl_pi_2: float

    R1_3: float
    L1_3: float
    Crdl_pi_3: float

    C2: float
    L2: float

    R0: float
    L0: float
    Cox: float
    Csub: float
    Gsub: float
    Cimd1: float
    Cimd2: float

    Rbga1: float
    Lbga1: float
    Cbga1: float

    Clf1: float
    Rlf1: float


_CONSTANTS = ModelConstants()


def logistic_factor() -> float:
    """返回 ``1(4).txt`` 指定的逻辑斯谛状态因子，并避免指数溢出。"""

    exponent = -_CONSTANTS.K * (_CONSTANTS.t + _CONSTANTS.a - _CONSTANTS.T)
    if exponent >= 0.0:
        negative_exponential = math.exp(-exponent)
        return negative_exponential / (1.0 + negative_exponential)
    return 1.0 / (1.0 + math.exp(exponent))


def interpolate_coefficient(value_0: float, value_1: float, factor: float) -> float:
    """在固定模型状态下插值一个源模型拟合系数。

    参数：
        value_0：初始状态的系数。
        value_1：最终状态的系数。
        factor：逻辑斯谛插值因子。

    返回：
        线性插值后的系数。
    """

    return value_0 + (value_1 - value_0) * factor


def validate_geometry_inputs(inputs: GeometryInputs) -> None:
    """校验九个公共输入以及源公式的定义域。

    参数：
        inputs：待校验的几何参数。

    异常：
        TypeError：当 ``inputs`` 不是 :class:`GeometryInputs` 实例时抛出。
        ValueError：当参数不是有限正数，或者导致源公式中的对数或分母
            没有定义时抛出。
    """

    if not isinstance(inputs, GeometryInputs):
        raise TypeError("inputs 必须是 GeometryInputs 实例")

    invalid = [
        item.name
        for item in fields(GeometryInputs)
        if not math.isfinite(getattr(inputs, item.name))
        or getattr(inputs, item.name) <= 0.0
    ]
    if invalid:
        raise ValueError(
            "以下几何输入必须是大于零的有限数值："
            + ", ".join(invalid)
        )
    if inputs.TSV_p <= inputs.TSV_r:
        raise ValueError("TSV 中心间距 TSV_p 必须大于 TSV 半径 TSV_r")
    if inputs.BGA_p <= inputs.BGA_r:
        raise ValueError("BGA 中心间距 BGA_p 必须大于 BGA 半径 BGA_r")

    kn = _calculate_kn(_CONSTANTS.n)
    tsv_substrate_argument = (
        kn * (inputs.TSV_p / inputs.TSV_r)
        / (1.0 + _CONSTANTS.t_ox / inputs.TSV_r)
    )
    tsv_spacing_argument = kn * inputs.TSV_p / inputs.TSV_r
    bga_capacitance_argument = kn * inputs.BGA_p / (2.0 * inputs.BGA_r)
    if math.isclose(tsv_substrate_argument, 1.0, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("TSV 几何参数导致源模型的对数分母为零")
    if math.isclose(tsv_spacing_argument, 1.0, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("TSV 几何参数导致间距公式的对数分母为零")
    if math.isclose(bga_capacitance_argument, 1.0, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("BGA 几何参数导致源模型的对数分母为零")
    skin_depth = 1.0 / math.sqrt(
        _CONSTANTS.mu0 * math.pi * _CONSTANTS.f * _CONSTANTS.sigma_Cu
    )
    if math.isclose(
        2.0 * inputs.TSV_r - skin_depth,
        0.0,
        rel_tol=0.0,
        abs_tol=1e-18,
    ):
        raise ValueError("TSV 半径 TSV_r 导致源模型的趋肤效应分母为零")


def _calculate_kn(n: int) -> float:
    factors = [1.0 / (2.0 * math.sin(index * math.pi / n)) for index in range(1, n)]
    return math.prod(factors) ** (1.0 / (n + 1))


def _calculate_correction_coefficients() -> dict[str, float]:
    factor = logistic_factor()
    endpoint_names = (
        "KR", "KCo", "KL", "KG", "KCsub", "KCimd1", "KCimd2",
        "KR1", "KL1", "KC1", "KR22", "KL22", "KC22", "KR3",
        "KL3", "KC3", "KC2", "KL2", "KRbga", "KLbga", "KCbga",
        "KRlf", "KClf", "eps_sw",
    )
    return {
        name: interpolate_coefficient(
            getattr(_CONSTANTS, f"{name}_0"),
            getattr(_CONSTANTS, f"{name}_1"),
            factor,
        )
        for name in endpoint_names
    }


def _calculate_rdl_parameters(
    inputs: GeometryInputs, coefficients: dict[str, float]
) -> dict[str, float]:
    c = _CONSTANTS
    w1, d1 = inputs.RDL_w_layer1, inputs.RDL_d_layer1
    w2, d2 = inputs.RDL_w_layer2, inputs.RDL_d_layer2
    w3, d3 = inputs.RDL_w_layer2, inputs.RDL_d_layer2
    delta_rdl = 1.0 / math.sqrt(math.pi * c.f * c.mu0 * c.sigma_Cu)

    def segment(
        width: float,
        distance: float,
        length: float,
        resistance_coefficient: float,
        inductance_coefficient: float,
        capacitance_coefficient: float,
    ) -> tuple[float, float, float]:
        rdc = c.rho_Cu * length / (width * c.t_RDL)
        rac = c.rho_Cu * length / (width * delta_rdl)
        resistance = math.sqrt(rdc**2 + rac**2) * resistance_coefficient
        inductance = (
            c.mu0 / (2.0 * math.pi) * length
            * (math.log10(2.0 * length / (width + c.t_RDL)) + 0.5
               + (width + c.t_RDL) / (3.0 * length))
            * 1e12 * inductance_coefficient
        )
        total_capacitance = (
            c.eps0 * c.epsr_SiO2 * width * length / distance
            * 1e15 * capacitance_coefficient
        )
        return resistance, inductance, total_capacitance / 4.0

    r1_1, l1_1, crdl_pi_1 = segment(
        w1, d1, c.l1, coefficients["KR1"], coefficients["KL1"], coefficients["KC1"]
    )
    r1_2, l1_2, crdl_pi_2 = segment(
        w2, d2, c.l2, coefficients["KR22"], coefficients["KL22"], coefficients["KC22"]
    )
    r1_3, l1_3, crdl_pi_3 = segment(
        w3, d3, c.l3, coefficients["KR3"], coefficients["KL3"], coefficients["KC3"]
    )
    er = c.epsr_PI
    c2 = (
        w2 * ((14.0 * er + 12.5) * math.sqrt(w2 / c.t_RDL)
              - (1.83 * er - 2.25) * math.sqrt(c.t_RDL / w2)
              + 0.02 * er * c.t_RDL / w2) * coefficients["KC2"]
    )
    l2 = (
        100.0 * c.t_RDL * (4.0 * math.sqrt(w2 / c.t_RDL) - 4.21)
        / 2.0 * 1e3 * coefficients["KL2"]
    )
    return {
        "R1_1": r1_1, "L1_1": l1_1, "Crdl_pi_1": crdl_pi_1,
        "R1_2": r1_2, "L1_2": l1_2, "Crdl_pi_2": crdl_pi_2,
        "R1_3": r1_3, "L1_3": l1_3, "Crdl_pi_3": crdl_pi_3,
        "C2": c2, "L2": l2,
    }


def _calculate_tsv_parameters(
    inputs: GeometryInputs, coefficients: dict[str, float]
) -> dict[str, float]:
    c = _CONSTANTS
    h = inputs.sub_h
    h_sub = h
    h_tsv = h + 16e-6
    r = inputs.TSV_r
    p = inputs.TSV_p
    pr = p / r
    tr = c.t_ox / r
    delta = 1.0 / math.sqrt(c.mu0 * math.pi * c.f * c.sigma_Cu)
    kn = _calculate_kn(c.n)
    common_fraction = c.n / (c.n + 1.0)
    substrate_log = math.log(kn * pr / (1.0 + tr))
    spacing_log = math.log(kn * pr)

    rloop_cal = (
        (c.n + 1.0) / c.n * h_tsv / (math.pi * c.sigma_Cu)
        * math.sqrt(1.0 / r**4 + 1.0 / (delta**2 * (2.0 * r - delta) ** 2))
    )
    lloop_cal = (c.n + 1.0) / c.n * c.mu0 * h_tsv / (2.0 * math.pi) * spacing_log
    cliner_cal = 2.0 * math.pi * c.epsr_SiO2 * c.eps0 * h_sub / math.log(1.0 + tr)
    csub_cal = common_fraction * 2.0 * math.pi * c.epsr_SI * c.eps0 * h_sub / substrate_log
    gsub_cal = common_fraction * 2.0 * math.pi * c.sigma_SI * h_sub / substrate_log
    cimd1_cal = (
        common_fraction * 2.0 * math.pi * c.epsr_PI * c.eps0 * c.h_pi / spacing_log
        + common_fraction * 2.0 * math.pi * c.epsr_SiO2 * c.eps0 * c.hsio2_1 / spacing_log
    )
    cimd2_cal = (
        common_fraction * 2.0 * math.pi * c.epsr_SiO2 * c.eps0 * c.hsio2_2 / spacing_log
    )
    return {
        "R0": rloop_cal * 1e3 * coefficients["KR"],
        "L0": lloop_cal * 1e12 * coefficients["KL"],
        "Cox": cliner_cal * 1e15 * coefficients["KCo"],
        "Csub": csub_cal * 1e15 * coefficients["KCsub"],
        "Gsub": gsub_cal * coefficients["KG"],
        "Cimd1": cimd1_cal * 1e15 * coefficients["KCimd1"],
        "Cimd2": cimd2_cal * 1e15 * coefficients["KCimd2"],
    }


def _calculate_bga_parameters(
    inputs: GeometryInputs, coefficients: dict[str, float]
) -> dict[str, float]:
    c = _CONSTANTS
    r_bga = inputs.BGA_r
    h_bga = 0.8 * (2.0 * r_bga)
    p_bga = inputs.BGA_p
    rho_bga = c.rho_Soder
    kn = _calculate_kn(c.n)
    w_bga = max(1.0 - logistic_factor(), coefficients["eps_sw"])
    rdc = rho_bga * h_bga / (math.pi * r_bga**2)
    delta_skin = math.sqrt(rho_bga / (math.pi * c.f * c.mu0 * c.mu_r_Soder))
    rac = rho_bga * h_bga / (2.0 * math.pi * r_bga * delta_skin)
    return {
        "Rbga1": math.sqrt(rdc**2 + rac**2) * coefficients["KRbga"] / w_bga,
        "Lbga1": (
            c.mu0 * c.mu_r_Soder * h_bga / (2.0 * math.pi)
            * math.log(p_bga / r_bga) * 1e12 * coefficients["KLbga"] / w_bga
        ),
        "Cbga1": (
            c.n / (c.n + 1.0) * 2.0 * math.pi * c.eps0 * h_bga
            / math.log(kn * p_bga / (2.0 * r_bga))
            * 1e12 * coefficients["KCbga"] / w_bga
        ),
    }


def _calculate_crack_parameters(
    inputs: GeometryInputs, coefficients: dict[str, float]
) -> dict[str, float]:
    c = _CONSTANTS
    r_bga = inputs.BGA_r
    rho_bga = c.rho_Soder
    alpha = 1.0 + (0.0 - 1.0) * logistic_factor()
    alpha_eff = max(alpha, 1e-6)
    del alpha_eff
    area_0 = math.pi * r_bga**2
    area_open = max((1.0 - alpha) * area_0, 1e-6 * area_0)
    w_crack = max(1.0 - alpha, coefficients["eps_sw"])
    return {
        "Clf1": (
            c.eps0 * c.eps_r_crack * area_open / c.g_crack
            * 1e12 * coefficients["KClf"] * w_crack
        ),
        "Rlf1": rho_bga * area_open / c.g_crack * coefficients["KRlf"] / w_crack,
    }


def calculate_component_parameters(inputs: GeometryInputs) -> ComponentParameters:
    """计算全部唯一的最终元器件参数。

    参数：
        inputs：严格包含九项外部几何参数的输入对象。

    返回：
        包含每个唯一最终元器件参数的不可变结果对象。

    异常：
        TypeError：当 ``inputs`` 不是 :class:`GeometryInputs` 时抛出。
        ValueError：当几何参数超出数学定义域时抛出。
        RuntimeError：当子模型定义了重复或非预期输出时抛出。
    """

    validate_geometry_inputs(inputs)
    coefficients = _calculate_correction_coefficients()
    groups = (
        _calculate_rdl_parameters(inputs, coefficients),
        _calculate_tsv_parameters(inputs, coefficients),
        _calculate_bga_parameters(inputs, coefficients),
        _calculate_crack_parameters(inputs, coefficients),
    )
    merged: dict[str, float] = {}
    duplicate_keys: set[str] = set()
    for group in groups:
        duplicate_keys.update(merged.keys() & group.keys())
        merged.update(group)
    if duplicate_keys:
        raise RuntimeError(
            "检测到重复的最终元器件参数名称："
            + ", ".join(sorted(duplicate_keys))
        )

    expected_names = {item.name for item in fields(ComponentParameters)}
    if merged.keys() != expected_names:
        missing = sorted(expected_names - merged.keys())
        unexpected = sorted(merged.keys() - expected_names)
        raise RuntimeError(
            f"最终参数结构不匹配；缺少={missing}，意外出现={unexpected}"
        )
    return ComponentParameters(**merged)


def parameters_to_dict(parameters: ComponentParameters) -> dict[str, float]:
    """把最终参数转换为顺序稳定且名称唯一的字典。

    参数：
        parameters：已经计算出的最终元器件参数。

    返回：
        按 :class:`ComponentParameters` 字段顺序排列的字典。

    异常：
        TypeError：当 ``parameters`` 不是 :class:`ComponentParameters` 时抛出。
    """

    if not isinstance(parameters, ComponentParameters):
        raise TypeError("parameters 必须是 ComponentParameters 实例")
    return {item.name: getattr(parameters, item.name) for item in fields(parameters)}


def calculate_parameter(name: str, inputs: GeometryInputs) -> float:
    """在不使用动态表达式求值的情况下计算一个指定名称的最终参数。

    参数：
        name：与 :class:`ComponentParameters` 字段完全一致的名称。
        inputs：严格包含九项外部几何参数的输入对象。

    返回：
        指定的最终参数值。

    异常：
        KeyError：当 ``name`` 不是最终参数名称时抛出。
        TypeError：当 ``inputs`` 不是 :class:`GeometryInputs` 时抛出。
        ValueError：当几何参数超出数学定义域时抛出。
    """

    values = parameters_to_dict(calculate_component_parameters(inputs))
    if name not in values:
        raise KeyError(f"未知的元器件参数 {name!r}；应为以下名称之一：{tuple(values)}")
    return values[name]


def _main() -> None:
    inputs = GeometryInputs()
    parameters = calculate_component_parameters(inputs)

    input_descriptions = {
        "sub_h": "衬底厚度",
        "TSV_r": "TSV 半径",
        "TSV_p": "TSV 间距",
        "BGA_r": "BGA 半径",
        "BGA_p": "BGA 间距",
        "RDL_w_layer1": "上层 RDL 线宽",
        "RDL_d_layer1": "上层 RDL 线距",
        "RDL_w_layer2": "下层 RDL 线宽",
        "RDL_d_layer2": "下层 RDL 线距",
    }
    parameter_units = {
        "R1_1": "Ω",
        "L1_1": "pH",
        "Crdl_pi_1": "fF",
        "R1_2": "Ω",
        "L1_2": "pH",
        "Crdl_pi_2": "fF",
        "R1_3": "Ω",
        "L1_3": "pH",
        "Crdl_pi_3": "fF",
        "C2": "pF",
        "L2": "pH",
        "R0": "mΩ",
        "L0": "pH",
        "Cox": "fF",
        "Csub": "fF",
        "Gsub": "kS",
        "Cimd1": "fF",
        "Cimd2": "fF",
        "Rbga1": "Ω",
        "Lbga1": "pH",
        "Cbga1": "pF",
        "Clf1": "pF",
        "Rlf1": "Ω",
    }

    print("=== 输入几何参数 ===")
    for item in fields(inputs):
        description = input_descriptions[item.name]
        print(f"{description}（{item.name}）= {getattr(inputs, item.name):.6e} m")

    print("\n=== 唯一元器件参数 ===")
    for name, value in parameters_to_dict(parameters).items():
        print(f"{name} = {value:.12g} {parameter_units[name]}")


if __name__ == "__main__":
    _main()

"""V2 优化框架与现有九参数电代理模型之间的窄接口。

配置层负责把 parameters.csv 中便于用户阅读的单位（当前为 um）乘以
``scale_to_model`` 转为模型单位（当前为 m）；本文件只接收转换后的数值，
按代理模型固定参数名调用 ``simulate_from_geometry``，再统一包装为二端口
``SParameterResponse``。以后更换电代理模型时，应尽量只改这个适配层。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np

from models.electrical_equivalent.simulation_pipeline import simulate_from_geometry


# 这九个名称是当前 ``simulation_pipeline.simulate_from_geometry`` 的接口合同。
# 顺序用于稳定地构造关键字参数，但 evaluate 还会校验集合完全相等：既不允许
# 缺参，也不忽略多余参数。若新结构参数数量不同，应新增适配器而非伪造九参数。
EXPECTED_PARAMETERS = (
    "sub_h",
    "TSV_r",
    "TSV_p",
    "BGA_r",
    "BGA_p",
    "RDL_w_layer1",
    "RDL_d_layer1",
    "RDL_w_layer2",
    "RDL_d_layer2",
)


@dataclass(frozen=True, slots=True)
class SParameterResponse:
    """统一的二端口频域响应：频率为 Hz，S 矩阵形状为 ``(N, 2, 2)``。"""

    frequencies_hz: np.ndarray
    s_parameters: np.ndarray
    source: str = "surrogate"

    def __post_init__(self) -> None:
        frequencies = np.asarray(self.frequencies_hz, dtype=np.float64)
        s_parameters = np.asarray(self.s_parameters, dtype=np.complex128)
        if frequencies.ndim != 1 or frequencies.size < 2:
            raise ValueError("frequencies_hz 必须是一维数组，且至少有两个频点")
        if s_parameters.shape != (frequencies.size, 2, 2):
            raise ValueError("s_parameters 必须为 (频点数, 2, 2) 复数矩阵")
        if not np.all(np.diff(frequencies) > 0.0):
            raise ValueError("频率必须严格递增")
        if not np.all(np.isfinite(s_parameters)):
            raise ValueError("S 参数包含 NaN 或无穷大")
        object.__setattr__(self, "frequencies_hz", frequencies)
        object.__setattr__(self, "s_parameters", s_parameters)


# 当前结构专用适配器：若以后接入另一个结构或不同输入数量的代理模型，应实现
# 新适配器并在 model_registry 中注册，不要在这里堆叠结构判断分支。
class SurrogateAdapter:
    """V2 与当前九参数代理模型之间唯一的连接点。

    将来更换代理模型时，优先只修改本文件并保持 ``evaluate`` 的返回格式。
    """

    def __init__(
        self,
        *,
        reference_impedance_ohm: float = 50.0,
        shunt_regularization: float = 1e-8,
    ) -> None:
        self.reference_impedance_ohm = float(reference_impedance_ohm)
        self.shunt_regularization = float(shunt_regularization)
        if self.reference_impedance_ohm <= 0.0:
            raise ValueError("reference_impedance_ohm 必须大于 0")
        if self.shunt_regularization <= 0.0:
            raise ValueError("shunt_regularization 必须大于 0")

    def evaluate(
        self,
        parameters_in_model_units: Mapping[str, float],
        frequencies_hz: np.ndarray,
    ) -> SParameterResponse:
        """用一组已换算到模型单位的九参数预测指定频率网格。

        这里故意执行精确参数集合校验，使 parameters.csv、适配器和实际代理
        模型任何一处接口漂移都能立即失败，而不是悄悄采用默认值产生错误结果。
        """

        supplied = set(parameters_in_model_units)
        expected = set(EXPECTED_PARAMETERS)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise ValueError(f"当前代理模型固定接收九参数；缺少={missing}，多余={extra}")
        result = simulate_from_geometry(
            **{name: float(parameters_in_model_units[name]) for name in EXPECTED_PARAMETERS},
            frequencies_hz=np.asarray(frequencies_hz, dtype=np.float64),
            reference_impedance=self.reference_impedance_ohm,
            shunt_regularization=self.shunt_regularization,
        )
        return SParameterResponse(result.frequencies_hz, result.s_parameters)


# 组合摘要用于报告中追踪“本次优化实际调用的是哪一版模型源码”。它只解决
# 可追溯性问题，不代表模型精度，也不能替代候选点的 HFSS 回代验证。
def surrogate_model_sha256() -> str:
    """计算交付包内五个代理源码文件的组合校验值。"""

    model_directory = (
        Path(__file__).resolve().parent.parent / "models" / "electrical_equivalent"
    )
    digest = hashlib.sha256()
    for path in sorted(model_directory.glob("*.py"), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest().upper()

"""模型目录、适配器注册和多学科统一输出。

``config/models.csv`` 只描述“某结构启用了哪些模型”，模型源码放在顶层
``models/`` 下；本模块把两者连接起来。当前主电模型返回完整二端口 S 参数，
热/可靠性等附加学科只需返回标量 metrics。所有已连接模型的 metrics 会在一次
候选点评估中合并，供同一套目标表达式和 post 约束使用。
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

import numpy as np

from .surrogate_adapter import SParameterResponse, SurrogateAdapter


# models.csv 的字段和顺序属于交付接口，严格校验可阻止错列配置静默生效。
_COLUMNS = (
    "model_id",
    "enabled",
    "structure",
    "discipline",
    "adapter",
    "parameters_file",
    "status",
    "description",
)
_DISCIPLINES = {"electrical", "thermal", "reliability"}
_STATUSES = {"connected", "not_connected"}
# ``status=connected`` 只有在适配器已注册时才合法；这能防止前端把占位行
# 误报成真实可计算模型。集合与下面的工厂表保持同步。
_REGISTERED_ADAPTERS = {("electrical", "surrogate")}
_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class ModelCatalogError(ValueError):
    """An actionable error in models.csv."""


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ModelCatalogError(f"enabled 必须是 true/false，实际为 {value!r}")


@dataclass(frozen=True, slots=True)
class ModelBinding:
    """models.csv 的一行：结构、学科、适配器和参数表之间的静态绑定。"""

    model_id: str
    enabled: bool
    structure: str
    discipline: str
    adapter: str
    parameters_file: str
    status: str
    description: str

    @property
    def available(self) -> bool:
        return self.status == "connected"


@dataclass(frozen=True, slots=True)
class ModelOutput:
    """电、热、可靠性模型共用的输出信封。

    ``metrics`` 是可在 objectives/constraints 表达式中引用的有限标量；
    ``response`` 只允许主电模型携带，用于绘制 S11/S12/S21/S22 曲线。
    未接入或失败的模型不得附带伪造指标，避免用户误以为结果已被验证。
    """

    model_id: str
    structure: str
    discipline: str
    status: str
    metrics: Mapping[str, float]
    response: SParameterResponse | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"connected", "not_connected", "failed"}:
            raise ValueError(f"未知模型输出状态 {self.status!r}")
        if self.status != "connected" and (self.metrics or self.response is not None):
            raise ValueError("未接入或失败的模型不得返回伪造指标/响应")
        if self.status == "connected" and not self.metrics and self.response is None:
            raise ValueError("connected 模型必须返回真实指标或响应")
        normalized: dict[str, float] = {}
        for name, value in self.metrics.items():
            numeric = float(value)
            if not name or not math.isfinite(numeric):
                raise ValueError("模型指标名称和值必须有效且有限")
            normalized[str(name)] = numeric
        object.__setattr__(self, "metrics", normalized)


@dataclass(frozen=True, slots=True)
class SuiteEvaluation:
    """一次多学科联合计算结果：主 S 参数、合并指标及各模型原始输出。"""

    primary_response: SParameterResponse
    metrics: Mapping[str, float]
    outputs: tuple[ModelOutput, ...]


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """完整且已校验的模型清单；``source_path`` 用于解析相对参数表路径。"""

    bindings: tuple[ModelBinding, ...]
    source_path: Path

    def primary_electrical(self) -> ModelBinding:
        """返回唯一启用且已接入的主电模型；多于或少于一个均视为配置错误。"""

        selected = [
            item
            for item in self.bindings
            if item.enabled
            and item.discipline == "electrical"
            and item.status == "connected"
        ]
        if len(selected) != 1:
            raise ModelCatalogError(
                "models.csv 必须且只能启用一个 connected electrical 模型"
            )
        return selected[0]

    def capabilities(self) -> list[dict[str, object]]:
        return [
            {
                "model_id": item.model_id,
                "enabled": item.enabled,
                "structure": item.structure,
                "discipline": item.discipline,
                "adapter": item.adapter or None,
                "parameters_file": item.parameters_file,
                "status": item.status,
                "available": item.available,
                "description": item.description,
            }
            for item in self.bindings
        ]

    def unavailable_outputs(self) -> list[ModelOutput]:
        return [
            ModelOutput(
                model_id=item.model_id,
                structure=item.structure,
                discipline=item.discipline,
                status="not_connected",
                metrics={},
                message=item.description or "模型尚未接入",
            )
            for item in self.bindings
            if item.status == "not_connected"
        ]


class ElectricalModelRuntime:
    """主电代理模型的兼容门面，把 S 参数包装成统一 ``ModelOutput``。"""

    def __init__(self, binding: ModelBinding, adapter: SurrogateAdapter) -> None:
        self.binding = binding
        self.adapter = adapter

    def evaluate(
        self,
        parameters_in_model_units: Mapping[str, float],
        frequencies_hz: np.ndarray,
    ) -> SParameterResponse:
        return self.adapter.evaluate(parameters_in_model_units, frequencies_hz)

    def evaluate_output(
        self,
        parameters_in_model_units: Mapping[str, float],
        frequencies_hz: np.ndarray,
        *,
        metric_builder: Callable[[SParameterResponse], Mapping[str, float]] | None = None,
    ) -> ModelOutput:
        response = self.evaluate(parameters_in_model_units, frequencies_hz)
        metrics = {} if metric_builder is None else dict(metric_builder(response))
        return ModelOutput(
            model_id=self.binding.model_id,
            structure=self.binding.structure,
            discipline=self.binding.discipline,
            status="connected",
            metrics=metrics,
            response=response,
        )


class DisciplineRuntime(Protocol):
    """二次开发模型必须满足的最小运行时接口（结构化鸭子类型）。

    新的 thermal/reliability 类不必继承基类，只要有 ``binding``，并实现完全
    相同签名的 ``evaluate_output``，返回合法 ``ModelOutput`` 即可。
    """

    binding: ModelBinding

    def evaluate_output(
        self,
        parameters_in_model_units: Mapping[str, float],
        frequencies_hz: np.ndarray,
        *,
        metric_builder: Callable[[SParameterResponse], Mapping[str, float]] | None = None,
    ) -> ModelOutput: ...


# 工厂隔离“如何从全局设置构造模型”与“如何执行模型”，便于按学科插件化扩展。
AdapterFactory = Callable[[ModelBinding, Mapping[str, object]], DisciplineRuntime]


def _surrogate_factory(
    binding: ModelBinding,
    settings: Mapping[str, object],
) -> DisciplineRuntime:
    return ElectricalModelRuntime(
        binding,
        SurrogateAdapter(
            reference_impedance_ohm=float(settings["reference_impedance_ohm"]),
            shunt_regularization=float(settings["shunt_regularization"]),
        ),
    )


_ADAPTER_FACTORIES: dict[tuple[str, str], AdapterFactory] = {
    ("electrical", "surrogate"): _surrogate_factory,
}


def register_adapter(
    discipline: str,
    adapter: str,
    factory: AdapterFactory,
    *,
    replace: bool = False,
) -> None:
    """为二次开发注册一个受控适配器工厂。

    新增热/可靠性模型的建议步骤：

    1. 在 ``models/<模型目录>/`` 放模型源码和固定资源，不把算法逻辑散入前端；
    2. 实现 ``DisciplineRuntime.evaluate_output``，返回真实且有限的 metrics；
    3. 用本函数注册 ``("thermal" 或 "reliability", adapter名, factory)``；
    4. 在 ``config/models.csv`` 增加/修改对应行，确认可运行后再设为
       ``status=connected, enabled=true``；
    5. 将新指标名加入上层可用指标清单，再在 objectives.csv 或
       constraints.csv 中引用，并为接口、单位和异常路径补测试。

    附加学科的指标名必须全局唯一，推荐使用 ``thermal_``、``reliability_``
    前缀；它们不应返回 S 参数 response。
    """
    key = (discipline.strip().lower(), adapter.strip().lower())
    if key[0] not in _DISCIPLINES or not key[1]:
        raise ValueError("adapter 注册必须提供有效 discipline 和名称")
    if key in _ADAPTER_FACTORIES and not replace:
        raise ValueError(f"adapter {key!r} 已注册")
    _ADAPTER_FACTORIES[key] = factory
    _REGISTERED_ADAPTERS.add(key)


def unregister_adapter(discipline: str, adapter: str) -> None:
    """Remove a non-built-in adapter; mainly useful for isolated tests/plugins."""
    key = (discipline.strip().lower(), adapter.strip().lower())
    if key == ("electrical", "surrogate"):
        raise ValueError("内置 electrical/surrogate adapter 不能注销")
    _ADAPTER_FACTORIES.pop(key, None)
    _REGISTERED_ADAPTERS.discard(key)


@dataclass(frozen=True, slots=True)
class ModelSuite:
    """同一结构当前启用的模型集合，负责按候选点组织一次联合求值。"""

    catalog: ModelCatalog
    runtimes: tuple[DisciplineRuntime, ...]

    @property
    def primary_electrical(self) -> DisciplineRuntime:
        model_id = self.catalog.primary_electrical().model_id
        for runtime in self.runtimes:
            if runtime.binding.model_id == model_id:
                return runtime
        raise ModelCatalogError("已启用电模型没有对应 runtime")

    def evaluate(
        self,
        parameters_in_model_units: Mapping[str, float],
        frequencies_hz: np.ndarray,
        *,
        electrical_metric_builder: Callable[
            [SParameterResponse], Mapping[str, float]
        ],
    ) -> SuiteEvaluation:
        """运行全部已启用模型并合并跨学科 metrics。

        主电模型使用 ``electrical_metric_builder`` 从 S 参数生成电性能指标；
        热/可靠性运行时直接返回自己的标量指标。合并时发现同名立即报错，
        因为静默覆盖会使目标函数引用到错误学科的数据。
        """

        outputs: list[ModelOutput] = []
        merged: dict[str, float] = {}
        primary_response: SParameterResponse | None = None
        primary_id = self.catalog.primary_electrical().model_id
        for runtime in self.runtimes:
            builder = (
                electrical_metric_builder
                if runtime.binding.model_id == primary_id
                else None
            )
            output = runtime.evaluate_output(
                parameters_in_model_units,
                frequencies_hz,
                metric_builder=builder,
            )
            if (
                output.model_id != runtime.binding.model_id
                or output.discipline != runtime.binding.discipline
                or output.status != "connected"
            ):
                raise ValueError(
                    f"模型 {runtime.binding.model_id!r} 返回了不匹配的统一输出"
                )
            if output.response is not None:
                if output.model_id != primary_id:
                    raise ValueError("只有 primary electrical 模型可以返回 S 参数响应")
                primary_response = output.response
            duplicate = sorted(set(merged).intersection(output.metrics))
            if duplicate:
                raise ValueError(
                    f"模型 {output.model_id!r} 的指标与其他学科重名：{duplicate}"
                )
            merged.update(output.metrics)
            outputs.append(output)
        if primary_response is None:
            raise ValueError("primary electrical 模型没有返回 S 参数响应")
        return SuiteEvaluation(primary_response, merged, tuple(outputs))


def build_model_suite(
    catalog: ModelCatalog,
    model_settings: Mapping[str, object],
) -> ModelSuite:
    """根据目录中启用且 connected 的行调用注册工厂，构建可执行模型套件。"""

    runtimes: list[DisciplineRuntime] = []
    for binding in catalog.bindings:
        if not binding.enabled or not binding.available:
            continue
        key = (binding.discipline, binding.adapter)
        try:
            factory = _ADAPTER_FACTORIES[key]
        except KeyError as exc:
            raise ModelCatalogError(f"尚未注册 adapter={key!r}") from exc
        runtimes.append(factory(binding, model_settings))
    suite = ModelSuite(catalog, tuple(runtimes))
    suite.primary_electrical
    return suite


def load_model_catalog(path: str | Path) -> ModelCatalog:
    """读取并严格校验 ``models.csv`` 及其参数表路径。

    参数表必须存在且位于 models.csv 所在目录之内，避免 ``../`` 路径逃逸；
    connected 行必须填写已注册 adapter，not_connected 行必须留空 adapter，
    未接入模型也不能 enabled。最后还会验证恰好一个主电模型处于启用状态。
    """

    source = Path(path).resolve()
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ModelCatalogError(
                "models.csv 表头必须严格为：" + ",".join(_COLUMNS)
            )
        rows = list(reader)
    if not rows:
        raise ModelCatalogError("models.csv 没有模型绑定")

    bindings: list[ModelBinding] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            model_id = (row["model_id"] or "").strip()
            structure = (row["structure"] or "").strip()
            discipline = (row["discipline"] or "").strip().lower()
            adapter = (row["adapter"] or "").strip().lower()
            parameters_file = (row["parameters_file"] or "").strip()
            status = (row["status"] or "").strip().lower()
            enabled = _parse_bool(row["enabled"] or "")
            if not _ID_PATTERN.fullmatch(model_id):
                raise ModelCatalogError("model_id 只能使用字母、数字、下划线和连字符")
            if not structure:
                raise ModelCatalogError("structure 不能为空")
            if discipline not in _DISCIPLINES:
                raise ModelCatalogError("discipline 只能是 electrical/thermal/reliability")
            if status not in _STATUSES:
                raise ModelCatalogError("status 只能是 connected/not_connected")
            if not parameters_file:
                raise ModelCatalogError("parameters_file 不能为空")
            catalog_directory = source.parent.resolve()
            parameter_path = (catalog_directory / parameters_file).resolve()
            try:
                parameter_path.relative_to(catalog_directory)
            except ValueError as exc:
                raise ModelCatalogError("parameters_file 不能越出 models.csv 所在目录") from exc
            if not parameter_path.is_file():
                raise ModelCatalogError(f"参数表不存在：{parameters_file}")
            if status == "connected" and not adapter:
                raise ModelCatalogError("connected 模型必须填写 adapter")
            if status == "connected" and (discipline, adapter) not in _REGISTERED_ADAPTERS:
                raise ModelCatalogError(
                    f"尚未实现 {discipline} adapter={adapter!r}，不能标记为 connected"
                )
            if status == "not_connected" and adapter:
                raise ModelCatalogError("not_connected 模型的 adapter 必须留空")
            if enabled and status != "connected":
                raise ModelCatalogError("未接入模型不能设置 enabled=true")
            bindings.append(
                ModelBinding(
                    model_id=model_id,
                    enabled=enabled,
                    structure=structure,
                    discipline=discipline,
                    adapter=adapter,
                    parameters_file=parameters_file,
                    status=status,
                    description=(row["description"] or "").strip(),
                )
            )
        except Exception as exc:
            error = exc if isinstance(exc, ModelCatalogError) else ModelCatalogError(str(exc))
            raise ModelCatalogError(f"models.csv 第 {row_number} 行无效：{error}") from exc

    identifiers = [item.model_id.casefold() for item in bindings]
    if len(set(identifiers)) != len(identifiers):
        raise ModelCatalogError("models.csv 中 model_id 重复（忽略大小写）")
    catalog = ModelCatalog(tuple(bindings), source)
    catalog.primary_electrical()
    return catalog


def build_electrical_runtime(
    binding: ModelBinding,
    *,
    reference_impedance_ohm: float,
    shunt_regularization: float,
) -> ElectricalModelRuntime:
    """兼容旧调用方的主电运行时构造入口；新多学科流程优先用 ModelSuite。"""

    if binding.discipline != "electrical" or not binding.enabled or not binding.available:
        raise ModelCatalogError("只能构建已启用且已接入的 electrical 模型")
    if binding.adapter != "surrogate":
        raise ModelCatalogError(f"尚未实现 electrical adapter={binding.adapter!r}")
    return ElectricalModelRuntime(
        binding,
        SurrogateAdapter(
            reference_impedance_ohm=reference_impedance_ohm,
            shunt_regularization=shunt_regularization,
        ),
    )

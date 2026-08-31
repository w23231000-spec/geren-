"""目标函数配置、校验与求值。

开发者只需在 ``config/objectives.csv`` 中配置目标；本模块负责把 CSV 表达式
编译成受限 AST、计算工程量，并统一转换为优化器使用的最小化目标 ``F``。
这里不会使用 Python ``eval``，也不会允许访问任意对象或调用任意函数。
"""

from __future__ import annotations

import ast
import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

import numpy as np


# CSV 列顺序是接口合同的一部分。严格校验能尽早发现 WPS/Excel 增删列、
# 错位逗号或旧版本配置，避免优化跑很久后才暴露配置错误。
_CSV_COLUMNS = (
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
_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DIRECTIONS = {"min", "max", "target"}
# 表达式安全边界：名称只能来自模型输出 metric、几何输入 parameter，或下面
# 明确列出的常量/纯数学函数。扩展函数时应在白名单中显式登记并补充测试。
_NAMESPACES = {"metric", "parameter"}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_UNARY_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "abs": abs,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
}
_VARIADIC_FUNCTIONS: dict[str, Callable[..., float]] = {
    "min": min,
    "max": max,
}


class ObjectiveConfigError(ValueError):
    """An actionable error in objectives.csv."""


@dataclass(frozen=True, slots=True)
class _SafeExpression:
    """已通过白名单校验的只读数学表达式。

    允许：有限数值、已登记指标/参数、``+ - * / **``、正负号，以及白名单
    数学函数。禁止：赋值、导入、推导式、lambda、任意属性链、关键字参数等。
    ``**`` 的指数还必须是 -8～8 的字面量，以限制异常大数和复杂计算。
    """

    source: str
    tree: ast.Expression
    metric_names: frozenset[str]
    parameter_names: frozenset[str]

    @classmethod
    def compile(
        cls,
        source: str,
        *,
        metric_names: Iterable[str],
        parameter_names: Iterable[str],
    ) -> _SafeExpression:
        """解析一次并递归验证 AST；后续批量候选点只复用已验证语法树。"""

        text = source.strip()
        if not text:
            raise ObjectiveConfigError("expression 不能为空")
        if len(text) > 512:
            raise ObjectiveConfigError("expression 不能超过 512 个字符")
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise ObjectiveConfigError(f"expression 语法错误：{exc.msg}") from exc
        if sum(1 for _ in ast.walk(tree)) > 128:
            raise ObjectiveConfigError("expression 过于复杂（最多 128 个语法节点）")

        expression = cls(
            source=text,
            tree=tree,
            metric_names=frozenset(metric_names),
            parameter_names=frozenset(parameter_names),
        )
        expression._validate(tree.body)
        return expression

    def evaluate(
        self,
        metrics: Mapping[str, float],
        parameters: Mapping[str, float],
    ) -> float:
        """从本次模型指标和参数映射中读取标量并计算，结果必须为有限数。"""

        value = float(self._evaluate_node(self.tree.body, metrics, parameters))
        if not math.isfinite(value):
            raise ValueError(f"表达式 {self.source!r} 的结果不是有限数")
        return value

    def _validate(self, node: ast.AST) -> None:
        """递归执行 AST 节点白名单；未在分支中明确接受的节点一律拒绝。"""

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ObjectiveConfigError("expression 中只允许数值常量")
            if not math.isfinite(float(node.value)):
                raise ObjectiveConfigError("expression 中不允许 NaN 或无穷大")
            return

        if isinstance(node, ast.Name):
            if node.id in _CONSTANTS:
                return
            in_metrics = node.id in self.metric_names
            in_parameters = node.id in self.parameter_names
            if in_metrics and in_parameters:
                raise ObjectiveConfigError(
                    f"{node.id!r} 同时是指标和参数，请写 metric.{node.id} "
                    f"或 parameter.{node.id}"
                )
            if not in_metrics and not in_parameters:
                raise ObjectiveConfigError(f"未知名称 {node.id!r}")
            return

        if isinstance(node, ast.Attribute):
            namespace, name = self._attribute_parts(node)
            self._validate_qualified_name(namespace, name)
            return

        if isinstance(node, ast.Subscript):
            namespace, name = self._subscript_parts(node)
            self._validate_qualified_name(namespace, name)
            return

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            self._validate(node.operand)
            return

        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            if isinstance(node.op, ast.Pow):
                exponent = self._literal_number(node.right)
                if exponent is None:
                    raise ObjectiveConfigError("幂运算的指数必须是 -8 到 8 的数值常量")
                if not math.isfinite(exponent) or abs(exponent) > 8.0:
                    raise ObjectiveConfigError("幂运算的指数必须是 -8 到 8 的数值常量")
            self._validate(node.left)
            self._validate(node.right)
            return

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ObjectiveConfigError("函数只能直接使用白名单中的函数名")
            name = node.func.id
            if node.keywords:
                raise ObjectiveConfigError("函数不允许关键字参数")
            if name in _UNARY_FUNCTIONS:
                if len(node.args) != 1:
                    raise ObjectiveConfigError(f"函数 {name} 只能接收 1 个参数")
            elif name in _VARIADIC_FUNCTIONS:
                if not node.args:
                    raise ObjectiveConfigError(f"函数 {name} 至少需要 1 个参数")
            else:
                allowed = sorted([*_UNARY_FUNCTIONS, *_VARIADIC_FUNCTIONS])
                raise ObjectiveConfigError(
                    f"不允许函数 {name!r}；可用函数：{', '.join(allowed)}"
                )
            for argument in node.args:
                self._validate(argument)
            return

        raise ObjectiveConfigError(
            f"expression 不允许语法 {type(node).__name__}；"
            "只允许指标/参数、数值、四则运算、有限幂运算和白名单函数"
        )

    @staticmethod
    def _literal_number(node: ast.AST) -> float | None:
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool) and isinstance(
            node.value, (int, float)
        ):
            return float(node.value)
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant)
            and not isinstance(node.operand.value, bool)
            and isinstance(node.operand.value, (int, float))
        ):
            value = float(node.operand.value)
            return value if isinstance(node.op, ast.UAdd) else -value
        return None

    @staticmethod
    def _attribute_parts(node: ast.Attribute) -> tuple[str, str]:
        if not isinstance(node.value, ast.Name) or node.value.id not in _NAMESPACES:
            raise ObjectiveConfigError("属性引用只能写成 metric.名称 或 parameter.名称")
        if node.attr.startswith("_"):
            raise ObjectiveConfigError("不允许访问下划线属性")
        return node.value.id, node.attr

    @staticmethod
    def _subscript_parts(node: ast.Subscript) -> tuple[str, str]:
        if not isinstance(node.value, ast.Name) or node.value.id not in _NAMESPACES:
            raise ObjectiveConfigError(
                '下标引用只能写成 metric["名称"] 或 parameter["名称"]'
            )
        if not isinstance(node.slice, ast.Constant) or not isinstance(
            node.slice.value, str
        ):
            raise ObjectiveConfigError("指标或参数的下标必须是固定字符串")
        return node.value.id, node.slice.value

    def _validate_qualified_name(self, namespace: str, name: str) -> None:
        allowed = self.metric_names if namespace == "metric" else self.parameter_names
        if name not in allowed:
            label = "指标" if namespace == "metric" else "参数"
            raise ObjectiveConfigError(f"未知{label} {name!r}")

    def _evaluate_node(
        self,
        node: ast.AST,
        metrics: Mapping[str, float],
        parameters: Mapping[str, float],
    ) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            if node.id in self.metric_names:
                return self._mapping_value(metrics, node.id, "指标")
            return self._mapping_value(parameters, node.id, "参数")
        if isinstance(node, ast.Attribute):
            namespace, name = self._attribute_parts(node)
            mapping = metrics if namespace == "metric" else parameters
            label = "指标" if namespace == "metric" else "参数"
            return self._mapping_value(mapping, name, label)
        if isinstance(node, ast.Subscript):
            namespace, name = self._subscript_parts(node)
            mapping = metrics if namespace == "metric" else parameters
            label = "指标" if namespace == "metric" else "参数"
            return self._mapping_value(mapping, name, label)
        if isinstance(node, ast.UnaryOp):
            value = self._evaluate_node(node.operand, metrics, parameters)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = self._evaluate_node(node.left, metrics, parameters)
            right = self._evaluate_node(node.right, metrics, parameters)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            return left**right
        if isinstance(node, ast.Call):
            function_name = node.func.id  # type: ignore[union-attr]
            arguments = [
                self._evaluate_node(argument, metrics, parameters)
                for argument in node.args
            ]
            function = _UNARY_FUNCTIONS.get(function_name) or _VARIADIC_FUNCTIONS[
                function_name
            ]
            return float(function(*arguments))
        raise AssertionError(f"未经验证的表达式节点：{type(node).__name__}")

    @staticmethod
    def _mapping_value(
        mapping: Mapping[str, float],
        name: str,
        label: str,
    ) -> float:
        if name not in mapping:
            raise ValueError(f"本次计算缺少{label} {name!r}")
        try:
            value = float(mapping[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} {name!r} 不是标量数值") from exc
        if not math.isfinite(value):
            raise ValueError(f"{label} {name!r} 不是有限数")
        return value


@dataclass(frozen=True, slots=True)
class ObjectiveSpec:
    """一行已校验的目标配置，以及对应的预编译安全表达式。"""

    name: str
    active: bool
    expression: str
    direction: str
    target: float | None
    recommendation_weight: float
    start_ghz: float | None
    stop_ghz: float | None
    unit: str
    description: str
    _compiled: _SafeExpression = field(repr=False, compare=False)

    @property
    def band_ghz(self) -> tuple[float, float] | None:
        """Configured local band, or ``None`` when the full band is used."""
        if self.start_ghz is None:
            return None
        assert self.stop_ghz is not None
        return (self.start_ghz, self.stop_ghz)

    def to_minimization(self, raw_value: float) -> float:
        """把工程值转换成所有算法共用的最小化目标 ``F``。

        转换规则固定为：``min -> F=raw``、``max -> F=-raw``、
        ``target -> F=abs(raw-target)``。因此优化器始终只需最小化 ``F``，
        而前端和报告仍展示更易理解的原始工程值。
        """
        if self.direction == "min":
            result = raw_value
        elif self.direction == "max":
            result = -raw_value
        else:
            assert self.target is not None
            result = abs(raw_value - self.target)
        if not math.isfinite(result):
            raise ValueError(f"目标 {self.name!r} 的内部值不是有限数")
        return result


@dataclass(frozen=True, slots=True)
class ObjectiveEvaluation:
    """同一次求值的工程原值与 canonical（统一最小化）F 向量。"""

    names: tuple[str, ...]
    raw_values: np.ndarray
    minimization_values: np.ndarray

    def raw_by_name(self) -> dict[str, float]:
        return {
            name: float(value)
            for name, value in zip(self.names, self.raw_values, strict=True)
        }


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ObjectiveConfigError(f"active 必须是 true/false，实际为 {value!r}")


def _finite_float(value: str, field_name: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ObjectiveConfigError(f"{field_name} 必须是数字") from exc
    if not math.isfinite(result):
        raise ObjectiveConfigError(f"{field_name} 必须是有限数")
    return result


def load_objective_specs(
    path: str | Path,
    *,
    metric_names: Iterable[str],
    parameter_names: Iterable[str],
) -> list[ObjectiveSpec]:
    """读取并完整校验用户可编辑的 ``objectives.csv``。

    校验覆盖：固定表头及列顺序、合法且不重名的 name、active 布尔值、
    min/max/target 与 target 的搭配、非负推荐权重、局部频段成对填写，以及
    表达式 AST 白名单。文件使用 ``utf-8-sig``，因此带 BOM 的 CSV 也可读取。
    """
    metric_names = tuple(metric_names)
    parameter_names = tuple(parameter_names)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != _CSV_COLUMNS:
            raise ObjectiveConfigError(
                "objectives.csv 表头必须严格为：" + ",".join(_CSV_COLUMNS)
            )
        rows = list(reader)

    specs: list[ObjectiveSpec] = []
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            raise ObjectiveConfigError(
                f"objectives.csv 第 {row_number} 行列数超过表头，"
                "请检查逗号或英文双引号"
            )
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            name = (row["name"] or "").strip()
            if not _NAME_PATTERN.fullmatch(name):
                raise ObjectiveConfigError(
                    "name 只能使用英文字母、数字和下划线，且不能以数字开头"
                )
            active = _parse_bool(row["active"] or "")
            direction = (row["direction"] or "").strip().lower()
            if direction not in _DIRECTIONS:
                raise ObjectiveConfigError("direction 只能是 min、max 或 target")
            target_text = (row["target"] or "").strip()
            target = _finite_float(target_text, "target") if target_text else None
            if direction == "target" and target is None:
                raise ObjectiveConfigError("direction=target 时必须填写 target")
            if direction != "target" and target is not None:
                raise ObjectiveConfigError("只有 direction=target 时才能填写 target")
            weight = _finite_float(
                (row["recommendation_weight"] or "").strip(),
                "recommendation_weight",
            )
            if weight < 0.0:
                raise ObjectiveConfigError("recommendation_weight 不能小于 0")
            start_text = (row["start_ghz"] or "").strip()
            stop_text = (row["stop_ghz"] or "").strip()
            if bool(start_text) != bool(stop_text):
                raise ObjectiveConfigError("start_ghz 和 stop_ghz 必须同时填写或同时留空")
            start_ghz = _finite_float(start_text, "start_ghz") if start_text else None
            stop_ghz = _finite_float(stop_text, "stop_ghz") if stop_text else None
            if start_ghz is not None and not 0.0 < start_ghz < stop_ghz:  # type: ignore[operator]
                raise ObjectiveConfigError("局部频段必须满足 0 < start_ghz < stop_ghz")
            expression = (row["expression"] or "").strip()
            compiled = _SafeExpression.compile(
                expression,
                metric_names=metric_names,
                parameter_names=parameter_names,
            )
            specs.append(
                ObjectiveSpec(
                    name=name,
                    active=active,
                    expression=expression,
                    direction=direction,
                    target=target,
                    recommendation_weight=weight,
                    start_ghz=start_ghz,
                    stop_ghz=stop_ghz,
                    unit=(row["unit"] or "").strip(),
                    description=(row["description"] or "").strip(),
                    _compiled=compiled,
                )
            )
        except Exception as exc:
            if isinstance(exc, ObjectiveConfigError):
                error = exc
            else:
                error = ObjectiveConfigError(str(exc))
            raise ObjectiveConfigError(
                f"objectives.csv 第 {row_number} 行无效：{error}"
            ) from exc

    if not specs:
        raise ObjectiveConfigError("objectives.csv 没有目标")
    normalized_names = [item.name.casefold() for item in specs]
    if len(set(normalized_names)) != len(normalized_names):
        raise ObjectiveConfigError("objectives.csv 中目标 name 重复（忽略大小写）")
    active = [item for item in specs if item.active]
    if not active:
        raise ObjectiveConfigError("objectives.csv 至少需要启用一个目标")
    if sum(item.recommendation_weight for item in active) <= 0.0:
        raise ObjectiveConfigError("已启用目标的 recommendation_weight 总和必须大于 0")
    return specs


def validate_objective_bands(
    specs: Iterable[ObjectiveSpec],
    frequencies_hz: np.ndarray,
) -> None:
    """用实际全局频率网格检查局部目标频段，且保证至少覆盖两个频点。"""
    frequency = np.asarray(frequencies_hz, dtype=np.float64)
    if frequency.ndim != 1 or frequency.size < 2 or not np.all(np.diff(frequency) > 0.0):
        raise ValueError("全局频率网格必须严格递增且至少包含 2 个频点")
    global_start_ghz = float(frequency[0] / 1e9)
    global_stop_ghz = float(frequency[-1] / 1e9)
    tolerance = max(abs(global_start_ghz), abs(global_stop_ghz), 1.0) * 1e-12
    for spec in specs:
        if spec.band_ghz is None:
            continue
        start_ghz, stop_ghz = spec.band_ghz
        if start_ghz < global_start_ghz - tolerance or stop_ghz > global_stop_ghz + tolerance:
            raise ObjectiveConfigError(
                f"目标 {spec.name!r} 的频段 [{start_ghz:g}, {stop_ghz:g}] GHz "
                f"超出全局范围 [{global_start_ghz:g}, {global_stop_ghz:g}] GHz"
            )
        selected = (frequency >= start_ghz * 1e9) & (frequency <= stop_ghz * 1e9)
        if int(np.count_nonzero(selected)) < 2:
            raise ObjectiveConfigError(
                f"目标 {spec.name!r} 的频段 [{start_ghz:g}, {stop_ghz:g}] GHz "
                "在当前频率网格上至少需要覆盖 2 个频点"
            )


def active_objectives(specs: Iterable[ObjectiveSpec]) -> list[ObjectiveSpec]:
    """保持 CSV 顺序返回启用目标；该顺序也是 F 向量和 Pareto 坐标顺序。"""

    return [item for item in specs if item.active]


def evaluate_objectives(
    specs: Iterable[ObjectiveSpec],
    *,
    metrics: Mapping[str, float],
    parameters: Mapping[str, float],
) -> ObjectiveEvaluation:
    """计算启用目标的工程原值，并生成优化器使用的 canonical F 向量。"""

    enabled = active_objectives(specs)
    if not enabled:
        raise ValueError("没有启用的目标")
    raw = np.asarray(
        [item._compiled.evaluate(metrics, parameters) for item in enabled],
        dtype=np.float64,
    )
    minimization = np.asarray(
        [
            item.to_minimization(float(value))
            for item, value in zip(enabled, raw, strict=True)
        ],
        dtype=np.float64,
    )
    return ObjectiveEvaluation(
        names=tuple(item.name for item in enabled),
        raw_values=raw,
        minimization_values=minimization,
    )


def recommendation_weights(specs: Iterable[ObjectiveSpec]) -> np.ndarray:
    """按 ``evaluate_objectives`` 的顺序返回归一化推荐权重。

    权重只用于从 Pareto 解集中推荐一个折中点，不改变 Pareto 支配关系。
    """
    enabled = active_objectives(specs)
    weights = np.asarray(
        [item.recommendation_weight for item in enabled], dtype=np.float64
    )
    total = float(np.sum(weights))
    if total <= 0.0 or not np.all(np.isfinite(weights)):
        raise ValueError("已启用目标的推荐权重必须非负，且总和大于 0")
    return weights / total

"""通用约束配置、阶段划分与 ``G <= 0`` 形式的求值。

约束来自 ``config/constraints.csv``。只引用 parameter 的约束可在模型调用前
（pre）快速筛掉无效几何；引用 metric 的约束必须在代理模型/HFSS 返回后
（post）判断。两类约束最终都转换成统一的违反量 ``G``：``G <= 0`` 可行，
``G > 0`` 表示违反，便于 NSGA-III、MOPSO、MOSA 共用同一接口。
"""

from __future__ import annotations

import ast
import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from .objectives import ObjectiveConfigError, _SafeExpression


# 与 objectives.csv 一样，约束 CSV 的表头和列顺序是稳定的用户配置合同。
_CSV_COLUMNS = (
    "name",
    "active",
    "left_expression",
    "operator",
    "right_expression",
    "tolerance",
    "unit",
    "description",
)
_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPERATORS = {"<=", ">=", "<", ">", "=="}


class ConstraintConfigError(ValueError):
    """An actionable error in constraints.csv."""


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    """一条已校验约束；可行性的统一判据始终是 ``violation <= 0``。

    ``tolerance`` 对 ``<=``/``>=`` 表示允许的数值松弛，对 ``==`` 表示允许
    的等式误差带，对严格 ``<``/``>`` 则表示两侧必须保留的最小间隔。
    """

    name: str
    active: bool
    left_expression: str
    operator: str
    right_expression: str
    tolerance: float
    unit: str
    description: str
    metric_references: frozenset[str]
    parameter_references: frozenset[str]
    _left: _SafeExpression = field(repr=False, compare=False)
    _right: _SafeExpression = field(repr=False, compare=False)

    @property
    def requires_metrics(self) -> bool:
        """Whether this constraint must be evaluated after model prediction."""

        return bool(self.metric_references)

    def violation(
        self,
        *,
        metrics: Mapping[str, float],
        parameters: Mapping[str, float],
    ) -> float:
        """计算 canonical 违反量 G；返回值不大于 0 即满足约束。

        例如 ``left <= right`` 转为 ``G=left-right-tolerance``；其他运算符
        同样调整方向，使所有算法都只判断一个固定规则，不必理解原始符号。
        """

        left = self._left.evaluate(metrics, parameters)
        right = self._right.evaluate(metrics, parameters)

        if self.operator == "<=":
            result = left - right - self.tolerance
        elif self.operator == ">=":
            result = right - left - self.tolerance
        elif self.operator == "<":
            result = left - right + self.tolerance
        elif self.operator == ">":
            result = right - left + self.tolerance
        else:
            result = abs(left - right) - self.tolerance

        if not math.isfinite(result):
            raise ValueError(f"约束 {self.name!r} 的 G 值不是有限数")
        return result


@dataclass(frozen=True, slots=True)
class ConstraintEvaluation:
    """一批启用约束的名称与 G 向量，二者按 CSV 顺序一一对应。"""

    names: tuple[str, ...]
    violations: np.ndarray

    @property
    def feasible(self) -> bool:
        return bool(np.all(self.violations <= 0.0))

    def by_name(self) -> dict[str, float]:
        return {
            name: float(value)
            for name, value in zip(self.names, self.violations, strict=True)
        }


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ConstraintConfigError(f"active 必须是 true/false，实际为 {value!r}")


def _finite_nonnegative(value: str, field_name: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ConstraintConfigError(f"{field_name} 必须是数字") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ConstraintConfigError(f"{field_name} 必须是大于等于 0 的有限数")
    return result


def _validated_symbols(values: Iterable[str], label: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ConstraintConfigError(f"{label}名称必须是非空字符串")
    if len(set(result)) != len(result):
        raise ConstraintConfigError(f"{label}名称重复")
    return result


class _ReferenceVisitor(ast.NodeVisitor):
    """收集表达式引用，用来判断约束属于 pre 还是 post 阶段。

    AST 的安全性已由 ``_SafeExpression`` 保证；此访问器只做依赖分析，
    不执行表达式。裸名称与 ``metric.x``/``parameter.x`` 两种写法均支持。
    """

    def __init__(
        self,
        metric_names: frozenset[str],
        parameter_names: frozenset[str],
    ) -> None:
        self.metric_names = metric_names
        self.parameter_names = parameter_names
        self.metrics: set[str] = set()
        self.parameters: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            if node.value.id == "metric":
                self.metrics.add(node.attr)
                return
            if node.value.id == "parameter":
                self.parameters.add(node.attr)
                return
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in {"metric", "parameter"}
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            target = self.metrics if node.value.id == "metric" else self.parameters
            target.add(node.slice.value)
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Function names are not metric/parameter references.
        for argument in node.args:
            self.visit(argument)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.metric_names:
            self.metrics.add(node.id)
        if node.id in self.parameter_names:
            self.parameters.add(node.id)


def _references(
    expression: _SafeExpression,
    *,
    metric_names: frozenset[str],
    parameter_names: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    visitor = _ReferenceVisitor(metric_names, parameter_names)
    visitor.visit(expression.tree.body)
    return frozenset(visitor.metrics), frozenset(visitor.parameters)


def load_constraint_specs(
    path: str | Path,
    *,
    metric_names: Iterable[str],
    parameter_names: Iterable[str],
) -> list[ConstraintSpec]:
    """读取并完整校验用户可编辑的 ``constraints.csv``。

    除固定表头、名称、布尔值和运算符外，还会检查 tolerance 为有限非负数、
    严格不等式具有正间隔、两侧表达式通过 AST 白名单，以及引用的指标/参数
    确实存在。每条错误都附带 CSV 行号，便于非开发用户定位修改位置。
    """

    metric_names_tuple = _validated_symbols(metric_names, "指标")
    parameter_names_tuple = _validated_symbols(parameter_names, "参数")
    metric_names_set = frozenset(metric_names_tuple)
    parameter_names_set = frozenset(parameter_names_tuple)

    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != _CSV_COLUMNS:
            raise ConstraintConfigError(
                "constraints.csv 表头必须严格为：" + ",".join(_CSV_COLUMNS)
            )
        rows = list(reader)

    specs: list[ConstraintSpec] = []
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            raise ConstraintConfigError(
                f"constraints.csv 第 {row_number} 行列数超过表头，请检查逗号或引号"
            )
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            name = (row["name"] or "").strip()
            if not _NAME_PATTERN.fullmatch(name):
                raise ConstraintConfigError(
                    "name 只能使用英文字母、数字和下划线，且不能以数字开头"
                )
            active = _parse_bool(row["active"] or "")
            operator = (row["operator"] or "").strip()
            if operator not in _OPERATORS:
                raise ConstraintConfigError(
                    "operator 只能是 <=、>=、<、> 或 =="
                )
            tolerance = _finite_nonnegative(
                (row["tolerance"] or "").strip(), "tolerance"
            )
            if operator in {"<", ">"} and tolerance <= 0.0:
                raise ConstraintConfigError(
                    "严格小于/大于必须设置 tolerance > 0，表示必须保留的间隔"
                )

            left_text = (row["left_expression"] or "").strip()
            right_text = (row["right_expression"] or "").strip()
            left = _SafeExpression.compile(
                left_text,
                metric_names=metric_names_tuple,
                parameter_names=parameter_names_tuple,
            )
            right = _SafeExpression.compile(
                right_text,
                metric_names=metric_names_tuple,
                parameter_names=parameter_names_tuple,
            )
            left_metrics, left_parameters = _references(
                left,
                metric_names=metric_names_set,
                parameter_names=parameter_names_set,
            )
            right_metrics, right_parameters = _references(
                right,
                metric_names=metric_names_set,
                parameter_names=parameter_names_set,
            )
            specs.append(
                ConstraintSpec(
                    name=name,
                    active=active,
                    left_expression=left_text,
                    operator=operator,
                    right_expression=right_text,
                    tolerance=tolerance,
                    unit=(row["unit"] or "").strip(),
                    description=(row["description"] or "").strip(),
                    metric_references=left_metrics | right_metrics,
                    parameter_references=left_parameters | right_parameters,
                    _left=left,
                    _right=right,
                )
            )
        except Exception as exc:
            if isinstance(exc, ConstraintConfigError):
                error = exc
            elif isinstance(exc, ObjectiveConfigError):
                error = ConstraintConfigError(str(exc))
            else:
                error = ConstraintConfigError(str(exc))
            raise ConstraintConfigError(
                f"constraints.csv 第 {row_number} 行无效：{error}"
            ) from exc

    normalized_names = [item.name.casefold() for item in specs]
    if len(set(normalized_names)) != len(normalized_names):
        raise ConstraintConfigError(
            "constraints.csv 中约束 name 重复（忽略大小写）"
        )
    return specs


def active_constraints(specs: Iterable[ConstraintSpec]) -> list[ConstraintSpec]:
    """按 CSV 原顺序返回启用的约束。"""

    return [item for item in specs if item.active]


def split_constraints(
    specs: Iterable[ConstraintSpec],
) -> tuple[list[ConstraintSpec], list[ConstraintSpec]]:
    """把启用约束拆成 ``(pre, post)`` 两组。

    ``pre`` 仅依赖几何参数，可在昂贵的模型预测之前检查；``post`` 至少引用
    一个模型指标，必须等电/热/可靠性模型的 metrics 合并完成后再检查。
    """

    enabled = active_constraints(specs)
    parameter_only = [item for item in enabled if not item.requires_metrics]
    metric_dependent = [item for item in enabled if item.requires_metrics]
    return parameter_only, metric_dependent


def constraint_names(specs: Iterable[ConstraintSpec]) -> list[str]:
    """返回启用约束名称，顺序与后续 G 向量一致。"""

    return [item.name for item in specs if item.active]


def evaluate_constraints(
    specs: Iterable[ConstraintSpec],
    *,
    parameters: Mapping[str, float],
    metrics: Mapping[str, float] | None = None,
) -> ConstraintEvaluation:
    """计算启用约束，返回名称和所有算法共用的 ``G <= 0`` 向量。

    pre 阶段可以不传 metrics；post 阶段应传入模型套件合并后的完整 metrics。
    本函数本身不决定阶段，调用方应先用 ``split_constraints`` 分组。
    """

    enabled = active_constraints(specs)
    metric_values: Mapping[str, float] = {} if metrics is None else metrics
    violations = np.asarray(
        [
            item.violation(metrics=metric_values, parameters=parameters)
            for item in enabled
        ],
        dtype=np.float64,
    )
    return ConstraintEvaluation(
        names=tuple(item.name for item in enabled),
        violations=violations,
    )

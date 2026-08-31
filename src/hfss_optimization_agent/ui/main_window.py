"""Tkinter desktop UI for configuring REAL HFSS optimization tasks.

This first GUI stage intentionally does not create an authorization and does
not launch AEDT/HFSS.  The "Check Configuration" action only builds an
OptimizationRequest and calls the application-level validate_task() service.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from ..application.events import RunEvent
from ..application.real_hfss_service import (
    run_real_hfss_task,
    validate_task,
)
from ..core.models import FrequencyPlan
from ..task_request import (
    OPTIMIZATION_REQUEST_SCHEMA_VERSION,
    OptimizationRequest,
    OptimizationRuleRequest,
    optimization_request_from_evaluation_contract,
)


MODEL_ID = "interposer_temple4"


@dataclass(frozen=True, slots=True)
class OptimizationFormData:
    model_id: str

    lower_start_ghz: str
    core_start_ghz: str
    core_stop_ghz: str
    upper_stop_ghz: str

    core_s21_operator: str
    core_s21_threshold: str
    core_s11_operator: str
    core_s11_threshold: str

    lower_s21_operator: str
    lower_s21_threshold: str
    lower_s11_operator: str
    lower_s11_threshold: str

    upper_s21_operator: str
    upper_s21_threshold: str
    upper_s11_operator: str
    upper_s11_threshold: str

    max_optimization_rounds: str


def load_default_request(root: Path) -> OptimizationRequest:
    root = Path(root).resolve()

    runtime = json.loads(
        (root / "runtime_config.json").read_text(encoding="utf-8")
    )

    rounds = int(
        runtime["real_hfss_execution"]["max_candidate_hfss_calls"]
    )

    return optimization_request_from_evaluation_contract(
        root / "config" / "evaluation_contract.production_v1.json",
        max_optimization_rounds=rounds,
    )


def _rule_index(
    request: OptimizationRequest,
) -> dict[tuple[str, str], OptimizationRuleRequest]:
    result: dict[tuple[str, str], OptimizationRuleRequest] = {}
    plan = request.frequency_plan

    for rule in request.rules:
        if rule.hard_constraint:
            side = "core"
        elif tuple(rule.frequency_band) == tuple(
            plan.lower_margin_band
        ):
            side = "lower"
        else:
            side = "upper"

        result[(side, rule.parameter)] = rule

    return result


def request_to_form_data(
    request: OptimizationRequest,
) -> OptimizationFormData:
    plan = request.frequency_plan
    rules = _rule_index(request)

    def item(side: str, parameter: str) -> OptimizationRuleRequest:
        return rules[(side, parameter)]

    return OptimizationFormData(
        model_id=request.model_id,

        lower_start_ghz=f"{plan.lower_margin_band[0]:g}",
        core_start_ghz=f"{plan.core_band[0]:g}",
        core_stop_ghz=f"{plan.core_band[1]:g}",
        upper_stop_ghz=f"{plan.upper_margin_band[1]:g}",

        core_s21_operator=item("core", "S21").operator,
        core_s21_threshold=f"{item('core', 'S21').threshold:g}",
        core_s11_operator=item("core", "S11").operator,
        core_s11_threshold=f"{item('core', 'S11').threshold:g}",

        lower_s21_operator=item("lower", "S21").operator,
        lower_s21_threshold=f"{item('lower', 'S21').threshold:g}",
        lower_s11_operator=item("lower", "S11").operator,
        lower_s11_threshold=f"{item('lower', 'S11').threshold:g}",

        upper_s21_operator=item("upper", "S21").operator,
        upper_s21_threshold=f"{item('upper', 'S21').threshold:g}",
        upper_s11_operator=item("upper", "S11").operator,
        upper_s11_threshold=f"{item('upper', 'S11').threshold:g}",

        max_optimization_rounds=str(
            request.max_optimization_rounds
        ),
    )


def _float(value: str, label: str) -> float:
    try:
        return float(value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是数字") from exc


def _operator(value: str, label: str) -> str:
    token = value.strip()

    if token not in {"<=", ">="}:
        raise ValueError(f"{label} 只允许 <= 或 >=")

    return token


def _rounds(value: str) -> int:
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("最大优化轮数必须是整数") from exc

    if not 1 <= parsed <= 100:
        raise ValueError("最大优化轮数必须在 1 到 100 之间")

    return parsed


def build_optimization_request(
    form: OptimizationFormData,
    *,
    tolerance_ghz: float,
) -> OptimizationRequest:
    if form.model_id != MODEL_ID:
        raise ValueError(
            f"当前只支持模型 {MODEL_ID}"
        )

    lower_start = _float(
        form.lower_start_ghz,
        "低频扩展起点",
    )
    core_start = _float(
        form.core_start_ghz,
        "核心频段起点",
    )
    core_stop = _float(
        form.core_stop_ghz,
        "核心频段终点",
    )
    upper_stop = _float(
        form.upper_stop_ghz,
        "高频扩展终点",
    )

    plan = FrequencyPlan(
        core_band=(core_start, core_stop),
        lower_margin_band=(lower_start, core_start),
        upper_margin_band=(core_stop, upper_stop),
        tolerance_ghz=tolerance_ghz,
    )

    if not plan.is_valid:
        raise ValueError(plan.validation_error)

    def rule(
        rule_id: str,
        parameter: str,
        side: str,
        hard: bool,
        operator: str,
        threshold: str,
    ) -> OptimizationRuleRequest:
        if side == "core":
            band = plan.core_band
        elif side == "lower":
            band = plan.lower_margin_band
        else:
            band = plan.upper_margin_band

        return OptimizationRuleRequest(
            rule_id=rule_id,
            parameter=parameter,
            frequency_band=band,
            operator=_operator(
                operator,
                f"{side} {parameter} 比较符",
            ),
            threshold=_float(
                threshold,
                f"{side} {parameter} 阈值",
            ),
            hard_constraint=hard,
            frequency_unit="GHz",
        )

    rules = (
        rule(
            "task_core_s21",
            "S21",
            "core",
            True,
            form.core_s21_operator,
            form.core_s21_threshold,
        ),
        rule(
            "task_core_s11",
            "S11",
            "core",
            True,
            form.core_s11_operator,
            form.core_s11_threshold,
        ),
        rule(
            "task_lower_s21",
            "S21",
            "lower",
            False,
            form.lower_s21_operator,
            form.lower_s21_threshold,
        ),
        rule(
            "task_lower_s11",
            "S11",
            "lower",
            False,
            form.lower_s11_operator,
            form.lower_s11_threshold,
        ),
        rule(
            "task_upper_s21",
            "S21",
            "upper",
            False,
            form.upper_s21_operator,
            form.upper_s21_threshold,
        ),
        rule(
            "task_upper_s11",
            "S11",
            "upper",
            False,
            form.upper_s11_operator,
            form.upper_s11_threshold,
        ),
    )

    return OptimizationRequest(
        schema_version=OPTIMIZATION_REQUEST_SCHEMA_VERSION,
        model_id=MODEL_ID,
        frequency_plan=plan,
        rules=rules,
        max_optimization_rounds=_rounds(
            form.max_optimization_rounds
        ),
    )


def budget_summary(
    request: OptimizationRequest,
) -> dict[str, int]:
    rounds = request.max_optimization_rounds

    return {
        "max_candidate_hfss_calls": rounds,
        "max_hfss_solve_launches": rounds + 1,
        "automatic_solve_retries": 0,
    }


class HFSSOptimizationWindow:
    def __init__(
        self,
        root: tk.Tk,
        *,
        project_root: Path,
    ) -> None:
        self.root = root
        self.project_root = Path(project_root).resolve()

        self.default_request = load_default_request(
            self.project_root
        )
        defaults = request_to_form_data(
            self.default_request
        )

        self.root.title("HFSS Optimization Agent")
        self.root.geometry("940x780")
        self.root.minsize(900, 720)

        self.variables: dict[str, tk.StringVar] = {
            name: tk.StringVar(
                value=str(getattr(defaults, name))
            )
            for name in defaults.__dataclass_fields__
        }

        self.budget_candidate = tk.StringVar()
        self.budget_total = tk.StringVar()
        self.budget_retry = tk.StringVar()

        self._event_queue: queue.Queue[RunEvent] = queue.Queue()
        self._run_active = False
        self._checked_request_digest: str | None = None
        self._worker_thread: threading.Thread | None = None

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

        self._build_layout()
        self._refresh_budget()

        self.variables[
            "max_optimization_rounds"
        ].trace_add(
            "write",
            lambda *_: self._refresh_budget(),
        )

        for variable in self.variables.values():
            variable.trace_add(
                "write",
                lambda *_: self._invalidate_checked_request(),
            )

        self.root.after(
            100,
            self._drain_events,
        )

    def _build_layout(self) -> None:
        container = ttk.Frame(
            self.root,
            padding=14,
        )
        container.pack(
            fill="both",
            expand=True,
        )

        title = ttk.Label(
            container,
            text="REAL HFSS Optimization Agent",
            font=("Microsoft YaHei UI", 16, "bold"),
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            container,
            text=(
                "当前阶段：任务参数配置与运行前检查。"
                "检查配置不会启动 AEDT/HFSS。"
            ),
        )
        subtitle.pack(
            anchor="w",
            pady=(2, 12),
        )

        task = ttk.LabelFrame(
            container,
            text="1. 优化任务",
            padding=12,
        )
        task.pack(
            fill="x",
            pady=(0, 10),
        )

        ttk.Label(
            task,
            text="模型",
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )

        model = ttk.Combobox(
            task,
            textvariable=self.variables["model_id"],
            values=(MODEL_ID,),
            state="readonly",
            width=28,
        )
        model.grid(
            row=0,
            column=1,
            columnspan=3,
            sticky="w",
            pady=4,
        )

        band = ttk.LabelFrame(
            container,
            text="2. 频段设置（GHz）",
            padding=12,
        )
        band.pack(
            fill="x",
            pady=(0, 10),
        )

        band_items = (
            ("低频扩展起点", "lower_start_ghz"),
            ("核心频段起点", "core_start_ghz"),
            ("核心频段终点", "core_stop_ghz"),
            ("高频扩展终点", "upper_stop_ghz"),
        )

        for index, (label, key) in enumerate(band_items):
            ttk.Label(
                band,
                text=label,
            ).grid(
                row=0,
                column=index * 2,
                sticky="w",
                padx=(0, 5),
                pady=4,
            )

            ttk.Entry(
                band,
                textvariable=self.variables[key],
                width=10,
            ).grid(
                row=0,
                column=index * 2 + 1,
                sticky="w",
                padx=(0, 14),
                pady=4,
            )

        rules = ttk.LabelFrame(
            container,
            text="3. 优化指标",
            padding=12,
        )
        rules.pack(
            fill="x",
            pady=(0, 10),
        )

        headings = (
            "区域",
            "参数",
            "比较符",
            "阈值 (dB)",
            "类型",
        )

        for column, text in enumerate(headings):
            ttk.Label(
                rules,
                text=text,
                font=("Microsoft YaHei UI", 9, "bold"),
            ).grid(
                row=0,
                column=column,
                sticky="w",
                padx=8,
                pady=(0, 5),
            )

        rows = (
            (
                "Core",
                "S21",
                "core_s21_operator",
                "core_s21_threshold",
                "HARD",
            ),
            (
                "Core",
                "S11",
                "core_s11_operator",
                "core_s11_threshold",
                "HARD",
            ),
            (
                "Lower",
                "S21",
                "lower_s21_operator",
                "lower_s21_threshold",
                "SOFT",
            ),
            (
                "Lower",
                "S11",
                "lower_s11_operator",
                "lower_s11_threshold",
                "SOFT",
            ),
            (
                "Upper",
                "S21",
                "upper_s21_operator",
                "upper_s21_threshold",
                "SOFT",
            ),
            (
                "Upper",
                "S11",
                "upper_s11_operator",
                "upper_s11_threshold",
                "SOFT",
            ),
        )

        for row_index, row in enumerate(rows, start=1):
            side, parameter, operator_key, threshold_key, level = row

            ttk.Label(
                rules,
                text=side,
            ).grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=8,
                pady=3,
            )

            ttk.Label(
                rules,
                text=parameter,
            ).grid(
                row=row_index,
                column=1,
                sticky="w",
                padx=8,
                pady=3,
            )

            ttk.Combobox(
                rules,
                textvariable=self.variables[operator_key],
                values=("<=", ">="),
                state="readonly",
                width=7,
            ).grid(
                row=row_index,
                column=2,
                sticky="w",
                padx=8,
                pady=3,
            )

            ttk.Entry(
                rules,
                textvariable=self.variables[threshold_key],
                width=12,
            ).grid(
                row=row_index,
                column=3,
                sticky="w",
                padx=8,
                pady=3,
            )

            ttk.Label(
                rules,
                text=level,
            ).grid(
                row=row_index,
                column=4,
                sticky="w",
                padx=8,
                pady=3,
            )

        budget = ttk.LabelFrame(
            container,
            text="4. 执行预算",
            padding=12,
        )
        budget.pack(
            fill="x",
            pady=(0, 10),
        )

        ttk.Label(
            budget,
            text="最大优化轮数",
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 6),
        )

        ttk.Entry(
            budget,
            textvariable=self.variables[
                "max_optimization_rounds"
            ],
            width=10,
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 24),
        )

        ttk.Label(
            budget,
            text="Candidate HFSS 最大次数：",
        ).grid(
            row=0,
            column=2,
            sticky="e",
        )

        ttk.Label(
            budget,
            textvariable=self.budget_candidate,
        ).grid(
            row=0,
            column=3,
            sticky="w",
            padx=(0, 18),
        )

        ttk.Label(
            budget,
            text="REAL HFSS 总上限：",
        ).grid(
            row=0,
            column=4,
            sticky="e",
        )

        ttk.Label(
            budget,
            textvariable=self.budget_total,
        ).grid(
            row=0,
            column=5,
            sticky="w",
            padx=(0, 18),
        )

        ttk.Label(
            budget,
            text="自动求解重试：",
        ).grid(
            row=0,
            column=6,
            sticky="e",
        )

        ttk.Label(
            budget,
            textvariable=self.budget_retry,
        ).grid(
            row=0,
            column=7,
            sticky="w",
        )

        actions = ttk.Frame(container)
        actions.pack(
            fill="x",
            pady=(0, 10),
        )

        self.check_button = ttk.Button(
            actions,
            text="检查配置",
            command=self._check_configuration,
        )
        self.check_button.pack(
            side="left",
            padx=(0, 8),
        )

        self.restore_button = ttk.Button(
            actions,
            text="恢复默认值",
            command=self._restore_defaults,
        )
        self.restore_button.pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            actions,
            text="打开运行结果目录",
            command=self._open_runs,
        ).pack(
            side="left",
            padx=(0, 8),
        )

        self.start_button = ttk.Button(
            actions,
            text="开始 REAL HFSS 优化",
            command=self._start_real_hfss,
            state="disabled",
        )
        self.start_button.pack(
            side="right",
        )

        status_frame = ttk.LabelFrame(
            container,
            text="5. 状态",
            padding=8,
        )
        status_frame.pack(
            fill="both",
            expand=True,
        )

        self.status = scrolledtext.ScrolledText(
            status_frame,
            height=12,
            wrap="word",
            font=("Consolas", 10),
        )
        self.status.pack(
            fill="both",
            expand=True,
        )

        self._write_status(
            "GUI 已启动。\n"
            "当前只开放“检查配置”，不会生成授权或启动 HFSS。\n"
        )

    def _form_data(self) -> OptimizationFormData:
        return OptimizationFormData(
            **{
                name: variable.get()
                for name, variable in self.variables.items()
            }
        )

    def _request(self) -> OptimizationRequest:
        return build_optimization_request(
            self._form_data(),
            tolerance_ghz=(
                self.default_request.frequency_plan.tolerance_ghz
            ),
        )

    def _refresh_budget(self) -> None:
        try:
            rounds = _rounds(
                self.variables[
                    "max_optimization_rounds"
                ].get()
            )
        except ValueError:
            self.budget_candidate.set("-")
            self.budget_total.set("-")
            self.budget_retry.set("0")
            return

        self.budget_candidate.set(str(rounds))
        self.budget_total.set(str(rounds + 1))
        self.budget_retry.set("0")

    def _write_status(self, message: str) -> None:
        self.status.insert("end", message)
        self.status.see("end")

    def _clear_status(self) -> None:
        self.status.delete("1.0", "end")

    def _check_configuration(self) -> None:
        self._clear_status()
        self._write_status("正在检查配置...\n")

        try:
            request = self._request()
            configuration = validate_task(
                self.project_root,
                request,
            )

            budget = budget_summary(request)

            self._write_status("\n【任务参数】PASS\n")
            self._write_status(
                f"模型：{request.model_id}\n"
            )
            self._write_status(
                "OptimizationRequest SHA256："
                f"{request.digest}\n"
            )
            self._write_status(
                "最大 Candidate HFSS："
                f"{budget['max_candidate_hfss_calls']}\n"
            )
            self._write_status(
                "最大 REAL HFSS："
                f"{budget['max_hfss_solve_launches']}\n"
            )
            self._write_status(
                "自动求解重试："
                f"{budget['automatic_solve_retries']}\n"
            )

            self._write_status("\n【运行配置】PASS\n")
            self._write_status(
                "运行模式："
                f"{configuration.get('real_hfss_mode')}\n"
            )
            self._write_status(
                "PyAEDT Python："
                f"{configuration.get('pyaedt_python')}\n"
            )

            self._checked_request_digest = request.digest
            self.start_button.configure(state="normal")

            self._write_status(
                "\n检查完成：未生成 Authorization，"
                "未启动 AEDT/HFSS。\n"
            )
            self._write_status(
                "当前参数已通过检查，可以启动 REAL HFSS。\n"
            )

            messagebox.showinfo(
                "检查配置",
                "配置检查通过。\n\n"
                "本次检查没有启动 AEDT/HFSS。",
            )

        except Exception as exc:
            self._checked_request_digest = None
            self.start_button.configure(state="disabled")

            self._write_status(
                f"\n【检查失败】{type(exc).__name__}: {exc}\n"
            )

            messagebox.showerror(
                "检查配置失败",
                f"{type(exc).__name__}: {exc}",
            )

    def _restore_defaults(self) -> None:
        defaults = request_to_form_data(
            self.default_request
        )

        for name in defaults.__dataclass_fields__:
            self.variables[name].set(
                str(getattr(defaults, name))
            )

        self._refresh_budget()
        self._clear_status()
        self._write_status("已恢复默认任务参数。\n")

    def _invalidate_checked_request(self) -> None:
        if self._run_active:
            return

        self._checked_request_digest = None

        if hasattr(self, "start_button"):
            self.start_button.configure(
                state="disabled"
            )

    def _set_running(self, running: bool) -> None:
        self._run_active = running

        if running:
            self.check_button.configure(state="disabled")
            self.restore_button.configure(state="disabled")
            self.start_button.configure(state="disabled")
            return

        self.check_button.configure(state="normal")
        self.restore_button.configure(state="normal")

        try:
            request = self._request()
        except Exception:
            self.start_button.configure(state="disabled")
            return

        if request.digest == self._checked_request_digest:
            self.start_button.configure(state="normal")
        else:
            self.start_button.configure(state="disabled")

    def _start_real_hfss(self) -> None:
        if self._run_active:
            return

        try:
            request = self._request()
        except Exception as exc:
            messagebox.showerror(
                "任务参数错误",
                f"{type(exc).__name__}: {exc}",
            )
            return

        if request.digest != self._checked_request_digest:
            self.start_button.configure(state="disabled")
            messagebox.showwarning(
                "请重新检查配置",
                "当前参数自上次检查后已经发生变化。\n\n"
                "请先点击“检查配置”。",
            )
            return

        budget = budget_summary(request)

        confirmed = messagebox.askyesno(
            "确认启动 REAL HFSS",
            (
                "即将启动真实 HFSS 优化。\n\n"
                f"模型：{request.model_id}\n"
                f"Candidate HFSS 最大次数："
                f"{budget['max_candidate_hfss_calls']}\n"
                f"REAL HFSS 总上限："
                f"{budget['max_hfss_solve_launches']}\n"
                "自动求解重试：0\n\n"
                "确认后将真正启动 AEDT/HFSS。\n\n"
                "是否继续？"
            ),
        )

        if not confirmed:
            return

        self._set_running(True)

        self._write_status(
            "\n========================================\n"
        )
        self._write_status(
            "【REAL HFSS】用户已确认启动真实优化任务。\n"
        )
        self._write_status(
            f"OptimizationRequest SHA256：{request.digest}\n"
        )
        self._write_status(
            "任务将在后台线程运行，GUI 将保持响应。\n"
        )
        self._write_status(
            "当前版本运行期间不提供强制停止按钮。\n"
        )

        self._worker_thread = threading.Thread(
            target=self._run_real_hfss_worker,
            args=(request,),
            name="real-hfss-workflow",
            daemon=False,
        )

        self._worker_thread.start()

    def _run_real_hfss_worker(
        self,
        request: OptimizationRequest,
    ) -> None:
        try:
            result = run_real_hfss_task(
                self.project_root,
                request,
                on_event=self._event_queue.put,
            )

            self._event_queue.put(
                RunEvent(
                    event_type="worker_done",
                    stage="gui",
                    message="后台 REAL HFSS 任务已经结束",
                    detail=result.status,
                    payload={
                        "task_id": result.task_id,
                        "status": result.status,
                        "request_path": str(
                            result.request_path
                        ),
                    },
                )
            )

        except Exception as exc:
            self._event_queue.put(
                RunEvent(
                    event_type="worker_error",
                    stage="gui",
                    message="后台 REAL HFSS 任务异常结束",
                    detail=(
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            )

    def _drain_events(self) -> None:
        try:
            while True:
                event = self._event_queue.get_nowait()
                self._handle_run_event(event)
        except queue.Empty:
            pass

        try:
            self.root.after(
                100,
                self._drain_events,
            )
        except tk.TclError:
            pass

    def _handle_run_event(
        self,
        event: RunEvent,
    ) -> None:
        labels = {
            "stage": "运行",
            "success": "通过",
            "complete": "完成",
            "error": "错误",
        }

        if event.event_type == "worker_done":
            self._set_running(False)

            payload = event.payload or {}
            task_id = payload.get("task_id", "-")
            status = payload.get("status", event.detail or "-")

            self._write_status(
                "\n【任务结束】"
                f"status={status} | task={task_id}\n"
            )

            messagebox.showinfo(
                "REAL HFSS 任务结束",
                (
                    f"Task ID：{task_id}\n"
                    f"Status：{status}\n\n"
                    "详细结果请查看 runs 目录。"
                ),
            )
            return

        if event.event_type == "worker_error":
            self._set_running(False)

            self._write_status(
                "\n【后台任务异常】"
                f"{event.detail or event.message}\n"
            )

            messagebox.showerror(
                "REAL HFSS 任务失败",
                event.detail or event.message,
            )
            return

        label = labels.get(
            event.event_type,
            event.event_type,
        )

        self._write_status(
            f"\n【{label} / {event.stage}】"
            f"{event.message}\n"
        )

        if event.detail:
            self._write_status(
                f"  {event.detail}\n"
            )

    def _on_close(self) -> None:
        if self._run_active:
            messagebox.showwarning(
                "REAL HFSS 正在运行",
                (
                    "当前 REAL HFSS 任务仍在运行。\n\n"
                    "为了避免留下失控的 HFSS Worker，"
                    "运行期间暂不允许直接关闭 GUI。"
                ),
            )
            return

        self.root.destroy()

    def _open_runs(self) -> None:
        path = self.project_root / "runs"
        path.mkdir(parents=True, exist_ok=True)

        try:
            os.startfile(path)
        except AttributeError:
            messagebox.showinfo(
                "运行结果目录",
                str(path),
            )


def main(
    project_root: Path | None = None,
) -> int:
    if project_root is None:
        project_root = Path(__file__).resolve().parents[3]

    root = tk.Tk()

    HFSSOptimizationWindow(
        root,
        project_root=project_root,
    )

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

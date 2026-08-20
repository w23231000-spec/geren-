# VS Code 使用说明

## 打开工程

在 VS Code 中选择“文件 -> 打开文件夹”，只打开本文件所在的 `HFSS_Optimization_Agent_VSCode` 文件夹，不要打开它的上级目录。

VS Code 会自动选择工程内的 `.venv\\Scripts\\python.exe`。若右下角提示安装扩展，安装 Microsoft Python 与 Python Debugger。

## 验证顺序

打开左侧“运行和调试”，依次运行：

1. `0 - Presentation Preflight`：只读检查环境，不启动 AEDT；
2. `1 - Run Offline Agent`：完全离线验证 LangGraph 闭环；
3. `2 - Run Bundled Optimizer with MockHFSS`：验证工程内置的优化与等效 S 参数模块；
4. `4 - Run All Tests`：运行精简后的主流程自动测试；
5. `3 - REAL HFSS Full Workflow (Visible AEDT)`：显示 AEDT 界面，执行两次建模、求解和导出。

除第 5 项外都不会启动 AEDT。真实流程会占用许可证，必须保证没有其他 HFSS 任务并确保电脑不会休眠。

## 真实工作流

真实入口是 `RUN_REAL_HFSS.py`。它自动生成唯一 Task ID，调用工程内的：

- `vendor/optimizer`；
- `vendor/hfss_builder`；
- `config/hfss_contract.pa_multi_2025_1.json`。

只创建并求解 `interposer_temple4`，不再创建 `huitu`。真实运行产物默认写到 `D:\\Agent_Workspace\\HFSS_Optimization_Agent_VSCode\\runs`。每个 Task、Baseline 和 Candidate 使用独立目录，不覆盖已有工程。

PyAEDT 解释器、输出目录和超时可以在 `runtime_config.json` 中修改。

真实入口会等待完整求解与导出结束，不会在“刚进入 Solve”时自动停止。

## 建模阶段怎么看是否正常

Builder 会创建大量阵列并逐次执行布尔运算，完整建模需要数分钟是正常现象。终端会用中文编号显示当前阶段，例如 `【主流程 03/14】仿真初始模型`、`【HFSS 建模 07/13】目标设计 interposer_temple4：生成阵列结构`。阶段编号发生变化就表示任务仍在推进；首个实体生成后程序会自动执行 `Fit All`。

PyAEDT 的大量底层 `INFO` 屏幕输出默认收起，避免淹没阶段信息；PyAEDT 日志文件和任务目录中的 `build_progress.json`、`run_journal.json` 仍保留，可用于详细排错。

如果上一次运行被强制停止，预检可能提示 stale PID。这不是许可证仍被占用；下次真实运行会在确认原 PID 已不存在后自动回收该 Agent 锁。若预检提示 active Agent process，则不要并行启动第二次真实任务。

工程内保留 `tools/probe_hfss_builder.py` 作为开发诊断工具，可只构建、保存并关闭测试工程而不求解；正常展示无需运行它。

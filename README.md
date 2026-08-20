# 面向复杂电磁结构优化的闭环 Agent 演示工程

这是一个可直接在 VS Code 中打开的单 Supervisor、统一 State、可恢复 LangGraph 工程。它集成用户提供的九参数 HFSS Builder、优化算法和等效 S 参数模块，并通过隔离的 PyAEDT Worker 执行真实 HFSS。

## 给老师展示时的运行顺序

在“运行和调试”中依次选择：

1. `0 - Presentation Preflight`：只读检查环境，不启动 AEDT；
2. `1 - Run Offline Agent`：展示完整 LangGraph 流程和产物；
3. `2 - Run Bundled Optimizer with MockHFSS`：展示真实优化/S 参数模块；
4. `3 - REAL HFSS Full Workflow`：显示 AEDT 界面并执行真实两次 HFSS；
5. `4 - Run All Tests`：展示自动测试。

真实流程只创建并求解 `interposer_temple4`，不再创建 `huitu`。Baseline 与 Candidate 各使用独立工程，不覆盖用户原工程。

## 当前可信度边界

软件流程、参数合同和目标设计 Builder 已建立；完整 Solve、Touchstone 导出和第二次真实 Solve 尚待首次完整实机验收。物理设置仍未校准，演示时应明确区分“自动化流程成立”和“模型物理结论已验证”。

真实 Builder 包含大量阵列与布尔运算，建模可能持续数分钟。终端统一使用 UTF-8 中文输出：主流程显示 14 个编号阶段，HFSS 运行显示 5 个编号阶段，目标 Design Builder 显示 13 个编号阶段。PyAEDT 底层屏幕日志默认收起，完整日志文件仍保留用于排错；模型创建首个实体后会自动执行 `Fit All`。

详见：

- `docs/ARCHITECTURE.md`；
- `docs/MODEL_RISKS.md`；
- `VSCode_使用说明.md`。

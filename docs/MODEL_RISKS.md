# 尚未解决但已保留修改入口的模型问题

以下问题不阻止软件流程演示，但会限制物理结论可信度。Agent 不自行猜测答案。

1. **PI 相对介电常数**：HFSS Builder 当前为 3.5，等效模型当前为 3.9。修改入口分别位于 `vendor/hfss_builder/pa_multi_builder/materials.py` 与 `vendor/optimizer/models/electrical_equivalent/`。
2. **SiO2 厚度定义**：两侧层厚定义尚未形成一份双方共享合同。HFSS 几何参数位于 Builder，等效模型参数计算位于 `parameter_calculator.py`。
3. **宽频元件参数**：部分等效元件在 10 GHz 计算后用于 0.1–20 GHz，需要作者确认是否应改为频变模型。
4. **Gsub 单位**：公式输出的物理量解释和单位尚待模型作者确认。
5. **Rlf1 量纲**：当前公式存在量纲疑点，不能由 Agent 自动修正。
6. **alpha_eff 未使用**：需确认它应进入哪一个损耗或传播常数公式，或者应删除。
7. **缺少校准数据**：目前没有 surrogate-vs-HFSS 或实测配对数据，因此结果明确标记为 `uncalibrated`。

保留的修改/验证机制：

- `config/model_alignment.example.json`：物理设置确认表；
- `config/hfss_contract.pa_multi_2025_1.json`：Design/Setup/Sweep/Port/材料合同；
- `evaluation/calibration.py`：频点、端口、阻抗和比较上下文一致性检查，以及复数 RMSE、dB RMSE、排序一致率；
- 完整复数 S11/S12/S21/S22 导出，避免仅用图表或 dB 标量校准。

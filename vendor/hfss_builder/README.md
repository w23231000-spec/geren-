# PA_MULTI PyAEDT 全脚本重建器

本目录可从零生成两个 HFSS Modal Design：

- `interposer_temple4`：直接创建目标设计，包括 `RadiatingSurface` 和 `AutoOpen1` Radiation 边界，共 39 个对象；Agent 流程不再创建重复的 `huitu`。

## 已实现范围

- 56 个设计变量及表达式，按依赖顺序写入。
- 自定义 `pi` 材料及系统材料引用。
- Global + 4 个 Relative Coordinate System。
- interposer1、16 点 UBM/焊球阵列、interposer2、89 点 TSV 阵列和全部层叠结构。
- 端口/PEC 命名面及开窗布尔。
- `PerfE3`、`PerfE4`、Lumped Port `3`/`4`；端口积分线使用显式坐标，不引用 Edge ID。
- `Setup1`：10 GHz、MaxDeltaS 0.02、最多 6 Pass、30% refinement、BasisOrder 1。
- Fast `Sweep`：0.1–20 GHz，步长 0.1 GHz，保存场。
- Candidate 参数由 Agent 优化器逐轮注入；HFSS 工程不再创建重复且禁用的 Optimetrics 参数扫描。
- 三张源工程同名 S 参数报告。
- 第二个 Design 的真空 Region 和 Radiation 边界。

源工程没有网格操作、输出变量或外部 CAD/3D Component 依赖，因此脚本不额外创建这些内容。

## 九参数建模入口

`nine_parameter_builder.py` 只负责接收九个外部尺寸并建立完整 AEDT 工程，不包含优化算法，也不会启动仿真。输入数值单位统一为 m：

```powershell
& 'C:\Users\82074\Documents\Codex\2026-08-12\wo\work\pyaedt-venv\Scripts\python.exe' `
  'C:\Users\82074\Documents\Codex\2026-08-12\wo\outputs\PA_MULTI_9parametric_builder\nine_parameter_builder.py' `
  --input 'C:\path\nine_parameters.json' `
  --output 'C:\path\PA_MULTI_new_model.aedt'
```

Python 上游模块也可以直接调用：

```python
from nine_parameter_builder import build_from_nine_parameters

result = build_from_nine_parameters(parameters, output_path)
```

九参数输入示例见 `nine_parameters.example.json`，精确联动关系见 `九参数联动关系.md`。

## 原始入口

环境要求：Ansys Electronics Desktop 2025 R1（脚本中的 PyAEDT 版本为 0.18.1）。

```powershell
& 'C:\Users\82074\Documents\Codex\2026-08-12\wo\work\pyaedt-venv\Scripts\python.exe' `
  'C:\Users\82074\Documents\Codex\2026-08-12\wo\outputs\PA_MULTI_9parametric_builder\build_project.py' `
  --output 'C:\path\to\PA_MULTI_scripted.aedt'
```

只做参数、材料和坐标系冒烟测试：

```powershell
& 'C:\Users\82074\Documents\Codex\2026-08-12\wo\work\pyaedt-venv\Scripts\python.exe' `
  'C:\Users\82074\Documents\Codex\2026-08-12\wo\outputs\PA_MULTI_9parametric_builder\build_project.py' `
  --output 'C:\path\to\PA_MULTI_smoke.aedt' --framework-only
```

可用 `--milestone` 生成阶段工程：`interposer1_foundation`、`bga_transition`、`interposer2`、`geometry_complete`。

## 验证证据

- `huitu_geometry_validation.json`：仅为最初供应模型审计记录；当前 Agent 运行不会构建该设计。
- `full_project_validation.json`：重新打开最终工程后，两套 Design 的对象、变量、坐标系、边界、端口、Setup、Sweep 和报告审计结果。
- `inter2_overlap_validation.json`：修复前/后的 A/B 求交测试；修复前交叠体积约 `1.72565e-4 mm³`，修复后为零。
- `overlap_fixed_full_validation.json`：两套 Design 的零交叠检查与 AEDT Design Validation，结果均为 PASS。
- `interposer1_foundation_validation.json`、`bga_transition_validation.json`、`interposer2_validation.json`：逐阶段回归记录。

频率 Sweep 属于 HFSS 求解合同；Candidate 参数扫描则由 Agent 优化器统一管理，避免形成两个相互冲突的优化状态来源。

完整依赖关系和历史审计位于相邻的 `PA_MULTI_construction_graph` 目录。

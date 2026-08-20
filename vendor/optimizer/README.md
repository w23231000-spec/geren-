# V2 多目标代理优化模块

本模块把“几何参数 → 代理模型预测 → 多目标搜索 → Pareto 解集 → HFSS 回代验证”串成一条流程。当前已接入的是 TSV–BGA–RDL 九参数二端口电学代理模型；热与可靠性接口已经预留，但没有真实模型时不会生成虚构指标。

普通使用者只需要修改 `config/` 中的表格，不需要进入算法源码。建议始终按“保存配置 → 基准检查 → 快速试跑 → 正式优化 → HFSS 复核”的顺序操作。

## 1. 目录设计

V2 采用“入口、配置、程序、模型、测试、结果”分离的设计。交给别人二次开发时，先让对方看本 README 和 `config/` 即可。

```text
V2/
├─ README.md                    本说明书
├─ frontend.py                  网页启动入口
├─ run.py                       命令行启动入口
├─ requirements.txt             Python 依赖
├─ config/                      日常修改区
│  ├─ parameters.csv            几何参数、基准值和搜索范围
│  ├─ objectives.csv            优化目标及全频/局部频段
│  ├─ constraints.csv           物理、性能和可靠性约束
│  ├─ models.csv                结构与代理模型绑定
│  └─ config.toml               频率、算法规模和数值设置
├─ app/                         优化器、指标、约束和前端后端源码
├─ models/
│  └─ electrical_equivalent/    当前九参数电学代理模型源码
├─ tests/                       自动测试
└─ results/                     每次运行自动生成的报告
```

设计原则：

- 只改参数、目标、约束或算法规模：改 `config/`。
- 接入新的电、热或可靠性模型：改 `models/`，并由开发者在 `app/` 注册适配器。
- 不要把用户配置写进 `app/`，也不要把生成结果放进 `config/`。
- 根目录只保留启动入口和说明，降低交接难度。

## 2. 快速开始

在 V2 根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动本地网页
.\.venv\Scripts\python.exe frontend.py
```

浏览器打开 `http://127.0.0.1:8765/`。也可以直接使用命令行：

```powershell
# 只检查模型、参数、目标、约束和基准点，不开始优化
.\.venv\Scripts\python.exe run.py --check

# 小规模联调，先确认整个流程可以跑通
.\.venv\Scripts\python.exe run.py --quick

# 二次开发后运行全部自动测试
.\.venv\Scripts\python.exe -m unittest -v tests.test_v2

# 使用 config/config.toml 中的正式规模运行
.\.venv\Scripts\python.exe run.py
```

如果 CSV 正被 WPS 或 Excel 占用，网页可能无法保存。请先保存并关闭表格，再执行检查。

## 3. 想改什么，就改哪里

| 想做的事 | 修改位置 | 是否需要开发代码 |
|---|---|---|
| 改九个几何参数的基准值、上下界、是否优化 | `config/parameters.csv` | 否 |
| 选择 S11、S21、相位等目标 | `config/objectives.csv` 或网页“优化目标” | 否 |
| 选择全频或局部频段目标 | `config/objectives.csv` 的 `start_ghz/stop_ghz` | 否 |
| 增加“参数 A 小于参数 B”等物理约束 | `config/constraints.csv` | 否 |
| 增加已有指标的性能门槛 | `config/constraints.csv` | 否 |
| 改 NSGA-III、MOPSO、MOSA 及运行规模 | `config/config.toml` 或网页“算法与运行” | 否 |
| 选择另一个已经接入的结构/模型 | `config/models.csv` | 否 |
| 新增第十个真实模型输入 | 参数表 + 模型适配器 | 是 |
| 新增温度、应力、寿命或失效概率指标 | 新模型 + 模型适配器 + `config/models.csv` | 是 |
| 改 Pareto 图 X/Y 轴 | 结果页下拉框 | 否，也不会重新优化 |

最重要的边界：当前电学代理模型真实接收且只接收下面九个参数。仅在 CSV 末尾增加一行，不能让模型凭空认识新参数。

## 4. 九个可修改几何参数

### 4.1 当前参数字典

当前九项的显示单位全部是 `um`（微米），模型内部单位全部是 `m`（米），因此 `scale_to_model=1e-6`。以下“影响”描述的是当前等效电路公式中主要被改变的部分，不表示参数增大后 S11 一定单调变好；最终方向随频率和其他参数共同变化，必须由代理搜索并经 HFSS 验证。

| 模型参数名 | 中文含义 | 基准值 | 当前下界～上界 | 在当前模型中的主要影响 | 约束与注意事项 |
|---|---|---:|---:|---|---|
| `sub_h` | 衬底厚度 | 200 um | 100～300 um | 改变 TSV 有效高度、回路电阻/电感，以及衬底相关电容和电导 | 使用HFSS建模代码的保守搜索范围 |
| `TSV_r` | TSV 半径 | 15 um | 7.5～22.5 um | 改变 TSV 趋肤电阻、回路电感、氧化层电容及衬底耦合 | 与固定35 um金属帽及`TSV_p`联合约束 |
| `TSV_p` | TSV 中心间距 | 260 um | 130～390 um | 通过间距/半径的对数项改变 TSV 回路电感和耦合电容/电导 | 与固定120 um阵列步距联合约束 |
| `BGA_r` | BGA 焊球半径 | 125 um | 62.5～187.5 um | 改变焊球 R/L/C，并影响当前裂纹支路的 R/C 参数 | 必须大于25 um，并与`BGA_p`联合约束 |
| `BGA_p` | BGA 中心间距 | 660 um | 330～990 um | 改变 BGA 电感和相邻焊球耦合电容 | 不能与`BGA_r`任意组合，由`bga_geometry_spacing`筛选 |
| `RDL_w_layer1` | 上层 RDL 线宽 | 100 um | 50～150 um | 主要改变上层 RDL 电阻、电感和对地/耦合电容；通常加宽会降电阻并增电容 | 与固定190 um圆形避空联合约束 |
| `RDL_d_layer1` | 上层 RDL 线距 | 50 um | 25～75 um | 在当前公式中作为上层 RDL 电容距离项，距离增大通常使该电容减小 | 与上层线宽联合约束 |
| `RDL_w_layer2` | 下层 RDL 线宽 | 80 um | 40～120 um | 同时作用于当前模型的第 2、3 段 RDL，并影响对应 R/L/C、`C2` 和 `L2` | 受固定190 um转弯避空约束 |
| `RDL_d_layer2` | 下层 RDL 线距 | 50 um | 25～75 um | 同时改变当前模型第 2、3 段的 RDL 电容距离项 | 与下层走线及避空同步变化 |

当前上下界来自配套HFSS模型和参数化建模代码的几何分析；联合可行域由 `constraints.csv` 中的参数约束继续筛选。它们是建模拓扑范围，不表示该范围内电性能一定满足设计指标。

### 4.2 `config/parameters.csv` 每一列怎么改

表头必须保留为：

```text
name,display_name,active,unit,model_unit,baseline,lower,upper,scale_to_model
```

| 列名 | 含义 | 普通用户是否建议修改 |
|---|---|---|
| `name` | 传给代理模型的精确参数名 | 当前九参数模型中不要改名 |
| `display_name` | 网页显示的中文名称 | 可以改，只影响说明 |
| `active` | `true` 表示参与优化；`false` 表示固定为 `baseline` | 可以改 |
| `unit` | CSV 中 `baseline/lower/upper` 使用的显示单位 | 当前保持 `um` |
| `model_unit` | 代理模型接收的单位 | 当前保持 `m` |
| `baseline` | 原始方案/初始点，也是结果页灰色 `BASELINE` | 可以改，但必须落在上下界内 |
| `lower` | 搜索下界 | 可以改，必须小于 `upper` |
| `upper` | 搜索上界 | 可以改，必须大于 `lower` |
| `scale_to_model` | 显示值换成模型值的倍率 | `um → m` 必须保持 `1e-6` |

即使 `active=false`，该行仍必须满足 `lower < upper` 且 `lower <= baseline <= upper`。

冻结一个参数的示例：把 BGA 中心距固定在 660 um，只改该行的 `active`：

```csv
BGA_p,BGA中心间距,false,um,m,660,594,726,1e-6
```

缩小搜索范围的示例：

```csv
TSV_r,TSV半径,true,um,m,15,14,16,1e-6
```

不要用 `lower=upper` 来固定参数；应使用 `active=false`。

## 5. 优化目标和可用指标

### 5.1 先理解四个最常用概念

设目标频段为 `[f1,f2]`，频率加权平均记为：

```text
band_mean(x) = ∫[f1,f2] x(f) df / (f2 - f1)
```

程序使用梯形积分，因此即使频率网格不等间隔，带宽平均仍有明确含义。

- 反射幅值：`|S11|` 或 `|S22|`，越小越好。
- 反射功率比：`|S11|²` 或 `|S22|²`，例如 `0.04` 表示 4%，CSV 中不要写成 `4%`。
- 回波损耗：`-20 log10|S11|`，数值越大越好。
- 插入损耗：`-20 log10|S21|`，对普通低损耗互连通常越小越好。

### 5.2 全部 18 个电学 `metric.*`

网页内置了 10 个常用预设；其余指标可以由开发者或熟悉公式的使用者直接写入 `config/objectives.csv`。表中的“典型方向”是互连优化的常见选择，不会覆盖 CSV 中显式填写的 `direction`。

| 指标表达式 | 工程公式 | 典型方向 | 单位 | 用途 | 网页预设 |
|---|---|---|---|---|---|
| `metric.worst_s11_magnitude` | `max_f |S11(f)|` | `min` | linear magnitude | 控制输入端全段/局部频段最差匹配点 | 是 |
| `metric.mean_reflected_power` | `band_mean(|S11|²)` | `min` | ratio | 让输入端反射功率在整段总体下降 | 是 |
| `metric.minimum_s11_return_loss_db` | `min_f[-20log10|S11|]` | `max` | dB | 提高输入端最差回波损耗 | 是 |
| `metric.worst_s22_magnitude` | `max_f |S22(f)|` | `min` | linear magnitude | 控制输出端最差匹配点 | 是 |
| `metric.mean_s22_reflected_power` | `band_mean(|S22|²)` | `min` | ratio | 降低输出端平均反射功率 | 否 |
| `metric.minimum_s22_return_loss_db` | `min_f[-20log10|S22|]` | `max` | dB | 提高输出端最差回波损耗 | 否 |
| `metric.mean_s21_insertion_loss_db` | `band_mean(-20log10|S21|)` | `min` | dB | 降低平均正向插入损耗 | 是 |
| `metric.worst_s21_insertion_loss_db` | `max_f[-20log10|S21|]` | `min` | dB | 控制最差正向传输频点 | 是 |
| `metric.mean_s21_transmission_power` | `band_mean(|S21|²)` | `max` | ratio | 提高平均正向传输功率 | 是 |
| `metric.mean_s12_insertion_loss_db` | `band_mean(-20log10|S12|)` | `min` | dB | 对互易互连检查/改善平均反向传输 | 是 |
| `metric.worst_s12_insertion_loss_db` | `max_f[-20log10|S12|]` | `min` | dB | 控制最差反向传输频点 | 否 |
| `metric.reciprocity_error` | `max_f |S21-S12|` | `min` | linear magnitude | 检查二端口互易性误差 | 否 |
| `metric.phase_weighted_rms_deg` | `sqrt(∫|S11_base|²·Δφ²df / ∫|S11_base|²df)` | `min` | deg | 让候选 S11 相位整体接近原始方案 | 是 |
| `metric.phase_reliable_max_deg` | 可信频点内 `max|Δφ|` | `min` | deg | 控制有意义频点的最大相位偏差 | 是 |
| `metric.phase_reliable_fraction` | 可信频点数 / 总频点数 | `max` | ratio | 诊断有多少频点适合比较相位，不建议单独作为主目标 | 否 |
| `metric.worse_frequency_fraction` | `count(|S11_candidate|>|S11_base|)/N` | `min` | ratio | 限制 S11 比原始方案更差的频点比例 | 否 |
| `metric.maximum_singular_value` | 全频段 `max σmax(S)` | `min` 或约束 | dimensionless | 被动性诊断，通常用作约束而非主目标 | 否 |
| `metric.passivity_violation` | `maximum_singular_value-(1+passivity_tolerance)` | `min` 或 `<=0` | dimensionless | 直接判断是否超过被动性门槛，建议写约束 | 否 |

相位差采用圆周差：

```text
Δφ = angle(S11_candidate × conj(S11_base))，范围为 [-180°, 180°]
```

“可信频点”要求原始方案和候选方案的 S11 幅度 dB 都不低于 `phase_reliable_floor_db`；当前门槛为 `-30 dB`。这样会排除深零点附近物理意义很弱、容易跳变的相位。

### 5.3 网页内置的 10 个目标预设

网页“优化目标”下拉框直接提供：

1. 最坏 S11 幅值
2. 平均反射功率
3. 最小 S11 回波损耗
4. 平均 S21 插入损耗
5. 最坏 S21 插入损耗
6. 平均 S21 传输功率
7. 最坏 S22 幅值
8. 平均 S12 插入损耗
9. S11 加权相位 RMS
10. S11 最大可信相位差

优先使用这些预设，因为方向、单位和表达式会自动填写。自定义表达式在网页中只读保留，应直接编辑 `config/objectives.csv`，再执行 `run.py --check`。

### 5.4 `config/objectives.csv` 每一列怎么改

表头必须严格保持：

```text
name,active,expression,direction,target,recommendation_weight,start_ghz,stop_ghz,unit,description
```

| 列名 | 含义和规则 |
|---|---|
| `name` | 该目标的唯一英文 ID；只能用字母、数字、下划线，且不能以数字开头 |
| `active` | `true` 参与优化，`false` 保留但不使用 |
| `expression` | 指标表达式，推荐写成 `metric.指标名` |
| `direction` | `min` 越小越好；`max` 越大越好；`target` 越接近目标值越好 |
| `target` | 仅 `direction=target` 时填写数字；其他方向必须留空 |
| `recommendation_weight` | 只用于从 Pareto 解中挑选平衡推荐点；不改变 Pareto 搜索本身 |
| `start_ghz` | 局部频段起点；全频时留空 |
| `stop_ghz` | 局部频段终点；全频时留空 |
| `unit` | 报告显示单位，不会自动换算表达式结果 |
| `description` | 给下一位开发者看的中文备注，建议写清“优化什么、哪个频段、为何使用” |

规则：

- 程序要求至少启用 2 个目标，才能形成多目标 Pareto 权衡。
- 所有已启用目标的权重之和必须大于 0，但不必手工加到 1，程序会归一化。
- `start_ghz` 与 `stop_ghz` 必须同时填写或同时留空。
- 局部频段必须落在 `config/config.toml` 的总扫描范围内，并至少覆盖 2 个频点。
- 两行可以使用同一个 `metric` 但设置不同频段；每行 `name` 必须不同。

当前配置的三个目标是：全频最坏 S11、全频 S11 相位保持、全频平均反射功率。它们会共同形成 Pareto 解，不是简单相加成一个分数。

示例一：优化 8～12 GHz 的最坏 S11，同时保持全频相位：

```csv
name,active,expression,direction,target,recommendation_weight,start_ghz,stop_ghz,unit,description
s11_8_12,true,metric.worst_s11_magnitude,min,,0.6,8,12,linear magnitude,降低8到12GHz内最坏S11
phase_full,true,metric.phase_weighted_rms_deg,min,,0.4,,,deg,保持全频S11相位接近原始方案
```

示例二：用回波损耗表达同一类匹配问题。注意回波损耗是越大越好：

```csv
s11_return_loss,true,metric.minimum_s11_return_loss_db,max,,1.0,,,dB,提高全频最差S11回波损耗
```

示例三：目标值模式：

```csv
s21_il_target,true,metric.mean_s21_insertion_loss_db,target,1.0,1.0,8,12,dB,让8到12GHz平均S21插损接近1dB
```

不要同时把 `worst_s11_magnitude` 设为 `min`、又把 `minimum_s11_return_loss_db` 设为 `min`；二者物理方向相反，后者应使用 `max`。

## 6. 物理、性能与可靠性约束

### 6.1 约束写在哪里

所有约束统一写在 `config/constraints.csv`。表头必须严格保持：

```text
name,active,left_expression,operator,right_expression,tolerance,unit,description
```

支持 `<=`、`>=`、`<`、`>`、`==`。参数写成 `parameter.参数名`，模型指标写成 `metric.指标名`。

| 列名 | 含义和规则 |
|---|---|
| `name` | 唯一英文约束 ID；只能用字母、数字、下划线，且不能以数字开头 |
| `active` | 是否启用该硬约束 |
| `left_expression` | 左侧参数、指标、常数或安全数学表达式 |
| `operator` | 比较关系 |
| `right_expression` | 右侧参数、指标、常数或安全数学表达式 |
| `tolerance` | 非负容差；`<=`/`>=` 时表示允许的数值松弛，`==` 时表示允许误差带 |
| `unit` | 备注/报告单位，不负责自动换算 |
| `description` | 必须写清物理来源、标准编号或工程含义，便于复核 |

严格 `<` 或 `>` 必须设置 `tolerance>0`，表示必须保留的实际间隔。普通工程门槛更建议使用 `<=` 或 `>=`，含义更直观。

只引用 `parameter.*` 的约束会在调用代理模型前检查，可以减少无效预测；引用 `metric.*` 的约束会在代理预测后检查。当前 `config/constraints.csv` 没有局部频段列，因此电学 `metric.*` 约束使用 `config/config.toml` 定义的完整频率扫描；局部频段只对 `config/objectives.csv` 中的目标生效。

### 6.2 当前启用的约束

| 约束名 | 当前规则 | 作用 |
|---|---|---|
| `tsv_formula_domain` | `TSV_p >= 1.260*TSV_r + 1.260` | 保持当前 TSV 代理公式定义域 |
| `bga_formula_domain` | `BGA_p >= 2.520*BGA_r` | 保持当前 BGA 代理公式定义域 |
| `tsv_geometry_pitch_min` | `TSV_p > 2.61312593*max(TSV_r,35)` | 防止TSV及固定35 um金属帽发生中心距重叠 |
| `tsv_geometry_pitch_max` | `sqrt(2)*TSV_p+2*max(TSV_r,35) < 720` | 防止移动TSV分支与固定阵列分支相交 |
| `tsv_fixed_pitch_clearance` | `2*max(TSV_r,35) < 120` | 保持固定120 um重复步距内的间隙 |
| `bga_positive_clip_height` | `BGA_r > 25` | 保持截球高度为正 |
| `bga_geometry_spacing` | `BGA_p > 2.61312593*max(BGA_r,100)` | 同时考虑焊球和固定100 um UBM半径 |
| `bga_substrate_edge` | `BGA_p+BGA_r < 1560` | 防止最高BGA越过interposer边界 |
| `bga_fixed_grid_clearance` | `2*max(BGA_r,100) < 583.095189` | 保持固定BGA阵列最小中心距 |
| `rdl_layer1_round_clearance` | `abs(RDL_w_layer1/2-RDL_d_layer1)+50 < 190` | 保持上层RDL末端位于圆形避空内 |
| `rdl_layer2_round_clearance` | `RDL_w_layer2/2 < 190` | 保持下层RDL转弯位于圆形避空内 |
| `phase_weighted_rms` | `phase_weighted_rms_deg <= 1.0` | 将 S11 加权相位 RMS 限制在 1° 内 |
| `phase_reliable_max` | `phase_reliable_max_deg <= 5.0` | 将可信频点最大 S11 相位差限制在 5° 内 |
| `worse_frequency_fraction` | `worse_frequency_fraction <= 0.10` | 最多允许 10% 频点的 S11 幅值比基准更差 |
| `passivity` | `passivity_violation <= 0` | 要求 S 参数不超过当前被动性容差 |

如果约束过严，可能没有任何可行 Pareto 点。先运行基准检查，再逐项看哪条约束未通过；不要只靠增加迭代次数解决不可行约束。

### 6.3 常用约束示例

一个参数小于常数：

```csv
sub_h_limit,true,parameter.sub_h,<=,210,0,um,衬底厚度不超过210um
```

一个参数小于另一个参数：

```csv
rdl_width_order,true,parameter.RDL_w_layer2,<=,parameter.RDL_w_layer1,0,um,下层RDL线宽不大于上层
```

设置真实边缘间隙：

```csv
tsv_edge_clearance,true,parameter.TSV_p,>=,2*parameter.TSV_r+20,0,um,TSV边缘间隙至少20um
```

限制全频最坏 S11 线性幅值：

```csv
s11_limit,true,metric.worst_s11_magnitude,<=,0.1,0,linear magnitude,全频最坏S11幅值不超过0.1
```

可靠性示例——前提是可靠性模型已经真实输出 `failure_probability`：

```csv
failure_probability_limit,true,metric.failure_probability,<=,0.001,0,ratio,任务周期内预测失效概率不超过0.1%
```

如果模型没有输出这个指标，`run.py --check` 会直接提示“未知指标”。不能仅靠在 CSV 中写名字来创造可靠性能力。

### 6.4 表达式允许什么

目标和约束表达式可使用：

- `metric.*`、`parameter.*`
- 数字和常数 `pi`、`e`
- `+ - * / **`，其中幂指数必须是 -8～8 的数值常量
- `abs`、`sqrt`、`log`、`log10`、`exp`、`min`、`max`

不允许导入模块、访问文件、执行系统命令或调用任意 Python 函数。表达式最长 512 个字符。未知参数或指标会在检查阶段报错。

CSV 不支持随意插入 `#` 注释行；备注请写入 `description` 列，避免被程序当成数据。

## 7. 算法和频率配置

`config/config.toml` 分为四组。

### 7.1 `[frequency]`

| 配置 | 当前值 | 含义 |
|---|---:|---|
| `start_ghz` | 0.1 | 总扫描起点，必须大于 0 |
| `stop_ghz` | 20.0 | 总扫描终点，必须大于起点 |
| `points` | 800 | 频点数，至少 2；越多越精细，也越慢、结果文件越大 |

### 7.2 `[optimizer]`

当前支持：

- `NSGA-III`：主要规模约为 `population × generations`。
- `MOPSO`：主要规模约为 `particles × mopso_iterations`。
- `MOSA`：主要规模约为 `chains × mosa_iterations`。

当前正式配置大致对应：NSGA-III `64×100`、MOPSO `64×100`、MOSA `24×240`。候选次数增大后耗时近似成比例增加；从 100 次改到 1000 次，通常不是“只多一点”，而是约十倍工作量。

| 配置 | 给谁用 | 说明 |
|---|---|---|
| `algorithm` | 普通用户 | 选择 `NSGA-III`、`MOPSO` 或 `MOSA` |
| `population/generations` | 普通用户 | NSGA-III 的种群和代数 |
| `particles/mopso_iterations` | 普通用户 | MOPSO 的粒子数和迭代次数 |
| `chains/mosa_iterations` | 普通用户 | MOSA 的并行链数和温度迭代数 |
| `seed` | 普通用户 | 随机种子；配置相同且种子相同有利于复现 |
| `archive_size` | 进阶用户 | MOPSO/MOSA 外部 Pareto 档案上限；太小会减少保留的多样解 |
| `neighborhood_samples` | 进阶用户 | 初始种群中放在基准点附近的样本数，必须小于当前算法初始数量 |
| `neighborhood_fraction` | 进阶用户 | 邻域扰动占每个参数搜索跨度的比例，范围 `(0,1]` |
| `inertia_start/end` | MOPSO 进阶项 | 粒子惯性权重的起止值 |
| `cognitive/social` | MOPSO 进阶项 | 个体学习和群体学习系数 |
| `velocity_limit` | MOPSO 进阶项 | 单步速度相对参数跨度的上限，范围 `(0,1]` |
| `initial_temperature/final_temperature` | MOSA 进阶项 | 起止温度，必须满足起始温度 ≥ 终止温度 > 0 |
| `step_start/step_end` | MOSA 进阶项 | 起止扰动步长，必须满足起始步长 ≥ 终止步长 > 0 |
| `leader_pull` | MOSA 进阶项 | 向 Pareto 引导点靠拢的强度，不能小于 0 |
| `iterations` | 兼容项 | 仅在算法专属迭代字段缺失时作为旧配置回退；日常应改专属字段 |

`--quick` 会使用内置小规模覆盖正式规模，目的是检查流程，不用于评价最终 Pareto 质量。

### 7.3 `[model]`

- `reference_impedance_ohm=50.0`：S 参数参考阻抗。
- `shunt_regularization=1e-8`：节点矩阵数值稳定项。

这两项属于模型定义。除非模型开发者确认，否则不要当作普通优化旋钮修改。

### 7.4 `[electrical_constraints]`

- `phase_reliable_floor_db=-30.0`：相位可信频点的 S11 幅度门槛。
- `passivity_tolerance=0.0001`：计算 `passivity_violation` 时允许的数值容差。

它们定义指标怎样计算，不等于自动启用硬约束；是否约束仍由 `config/constraints.csv` 决定。

## 8. 结构与模型注册表

`config/models.csv` 的表头必须严格保持：

```text
model_id,enabled,structure,discipline,adapter,parameters_file,status,description
```

| 列名 | 含义 | 修改注意 |
|---|---|---|
| `model_id` | 唯一模型 ID | 已接入模型不要随意改名 |
| `enabled` | 是否在本次运行中使用 | 只能启用 `connected` 模型 |
| `structure` | 结构名称 | 同一轮运行的启用模型必须服务于所选结构 |
| `discipline` | `electrical`、`thermal` 或 `reliability` | 只能使用这三类 |
| `adapter` | 程序中已注册的适配器名 | 不是随便填写的文本 |
| `parameters_file` | 相对于 `models.csv` 所在目录的参数表 | 当前保持 `parameters.csv`；不能跳出 `config/` |
| `status` | `connected` 或 `not_connected` | 代表真实接入状态，不是“希望启用”的开关 |
| `description` | 中文能力说明 | 建议注明版本、输入、输出和验证来源 |

硬规则：必须且只能启用一个 `connected` 的主电学模型。当前状态为：

- `tsv_bga_rdl_electrical`：已连接，当前九参数二端口电学代理模型。
- `tsv_bga_rdl_thermal`：未连接，不计算温度。
- `tsv_bga_rdl_reliability`：未连接，不计算寿命或失效概率。

不要把热/可靠性行直接从 `not_connected` 改成 `connected`。只有开发者已经实现并注册对应 adapter，而且模型返回可追溯的真实指标后，才可以更改状态。

## 9. 二次开发：新增结构、热模型或可靠性模型

新增结构和电模型的最短流程：

1. 在 `config/` 新建该结构的参数表，例如 `parameters_interposer.csv`。
2. 在 `models/` 新建独立模型目录，模型接收模型单位参数和频率数组。
3. 电模型必须返回频率数组以及形状为 `(N,2,2)` 的复数 S 参数。
4. 在 `app/model_registry.py` 通过 `register_adapter(...)` 注册受控工厂。
5. 在 `config/models.csv` 增加绑定，并确保只启用一个主电学模型。
6. 运行 `python run.py --check`，再运行自动测试和快速试跑。

热或可靠性模型统一返回标量指标，例如：

```python
ModelOutput(
    model_id="verified_reliability_v1",
    structure="TSV-BGA-RDL",
    discipline="reliability",
    status="connected",
    metrics={
        "failure_probability": real_result.failure_probability,
        "predicted_life_cycles": real_result.predicted_life_cycles,
    },
)
```

接入后，优化器无需改写，可直接在目标或约束中引用：

```text
metric.failure_probability
metric.predicted_life_cycles
```

不同模型输出的指标名不能重名。指标必须来自真实仿真、试验公式或经过验证的代理模型，不能用常数或猜测值伪装成可靠性结果。

## 10. 结果、Pareto 交互与 HFSS 复核

每次运行在 `results/run_时间/` 生成：

```text
00_summary.json           配置、模型能力、基准/推荐点、提升、哈希和警告
01_pareto.csv             Pareto点的参数、目标、约束和全部指标
02_sparameters.csv        BASELINE及全部Pareto点的完整复数S11/S12/S21/S22
03_pareto.png             固定报告版Pareto图
04_s11_magnitude.png      S11幅度：Baseline vs Recommended
05_s11_phase.png          S11相位：Baseline vs Recommended
06_s12_magnitude.png      S12幅度：Baseline vs Recommended
07_s12_phase.png          S12相位：Baseline vs Recommended
08_s21_magnitude.png      S21幅度：Baseline vs Recommended
09_s21_phase.png          S21相位：Baseline vs Recommended
10_s22_magnitude.png      S22幅度：Baseline vs Recommended
11_s22_phase.png          S22相位：Baseline vs Recommended
```

结果页的交互式 Pareto 图：

- X、Y 轴可以从已启用目标中自由选择；换轴只改变二维投影，不会重新优化。
- `BASELINE` 初始方案始终以灰色参考点显示，不属于 Pareto 解，也不计入 Pareto 点数。
- 推荐解使用红色星标，其他 Pareto 解使用蓝点。
- 点击 `BASELINE` 或任一 `Pxxxx`，九个参数、目标、约束及 S11/S12/S21/S22 幅度/相位曲线会同步切换。
- 下方 04～11 的八张固定 PNG 始终是 `Baseline vs Recommended` 的正式报告，不随临时点击改变。

最终工程结论不能只看代理结果。建议从 Pareto 前沿选择：

1. 平衡推荐点；
2. 每个目标的极端优选点；
3. 前沿拐点；
4. 接近约束边界的风险点；
5. 初始 `BASELINE`。

将这些点回代 HFSS，使用相同端口、材料、边界、网格和频率扫描，对比代理误差和真实性能提升。页面中的“代理通过”仅表示当前代理模型与 CSV 约束通过，不等于 HFSS、热仿真或可靠性最终达标。

## 11. 交接前检查清单

- [ ] 只在 `config/` 中改日常配置，未误改 `app/`。
- [ ] 九个参数名称、单位和 `scale_to_model` 与所选模型一致。
- [ ] 每个参数满足 `lower < upper` 且基准值位于范围内。
- [ ] 每个目标方向正确：幅值/功率通常 `min`，回波损耗通常 `max`。
- [ ] 局部频段位于总频率范围内。
- [ ] 每条约束的 `description` 写明工程来源，而不是只写“限制”。
- [ ] 新热/可靠性指标确实由已接入模型输出。
- [ ] 已运行 `python run.py --check`。
- [ ] 已运行快速试跑并检查 Pareto 点数、约束和曲线。
- [ ] 正式候选点已经回代 HFSS 或其他高保真模型验证。

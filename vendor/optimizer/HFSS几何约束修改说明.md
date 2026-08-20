# HFSS九参数几何约束修改说明

本版本在原优化模块上只修改了九参数搜索范围和参数级几何约束，没有修改代理模型、目标函数或优化算法。

## 搜索范围

单位为 µm：

- `sub_h`: 100–300
- `TSV_r`: 7.5–22.5
- `TSV_p`: 130–390
- `BGA_r`: 62.5–187.5
- `BGA_p`: 330–990
- `RDL_w_layer1`: 50–150
- `RDL_d_layer1`: 25–75
- `RDL_w_layer2`: 40–120
- `RDL_d_layer2`: 25–75

## 联合约束

联合约束写在 `config/constraints.csv`，并且全部只引用 `parameter.*`，因此在调用代理模型前执行。重点是：

```text
BGA_p > 2.61312593 * max(BGA_r, 100)
TSV_p > 2.61312593 * max(TSV_r, 35)
sqrt(2) * TSV_p + 2 * max(TSV_r, 35) < 720
abs(RDL_w_layer1/2 - RDL_d_layer1) + 50 < 190
RDL_w_layer2/2 < 190
```

另外保留了原模块已有的TSV/BGA代理公式定义域约束和所有电性能约束。

## 验证

新增 `tests/test_hfss_geometry_limits.py`，验证：

- 九参数上下界正确加载；
- 基准参数通过全部参数级约束；
- `BGA_r=187.5 µm, BGA_p=330 µm`被判为不可行；
- `BGA_r=187.5 µm, BGA_p=500 µm`通过BGA几何间距约束。

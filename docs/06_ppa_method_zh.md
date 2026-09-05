# PPA 逐轮评估方法

SPDX-License-Identifier: Apache-2.0

本项目每次修改 RTL、约束、工艺/库、布局布线或分析方法，都应保存独立 PPA 记录。分析脚本只提取证据，不能授予流片资格。缺失值使用 `null`，不得补零。

## 当前入口

- [基线及本轮中文分析](../reports/ppa/20260905_review_zh.md)。
- [历史全芯片基线](../reports/ppa/croc-ppa-baseline-20260905-001.json)：原始 global-route 寄生估计报告。
- [本轮单 RC 模型提取](../reports/ppa/croc-ppa-rcx-20260905-001.json)：同一版图的 OpenRCX/SPEF 读回，尚未完成 RC corner/MMMC 资格确认。
- [CTS 同阶段 A/B](../reports/ppa/croc-ppa-cts-ab-20260905-001.json)：fanout 改善与面积/工具功耗代价。
- [最新分支 ECO 003](../reports/ppa/croc-ppa-cts-branch-eco-20260905-003.json)：fanout=0，NDR 继承和结构连接已验证；slew/cap 未闭环。历史 002 保留，不覆盖。
- [权威对照来源](../reports/ppa/comparison_sources_20260905.json)。

## 必须保留的比较条件

| 维度 | 每轮记录 | 可比较条件 |
|---|---|---|
| 设计范围 | top、RTL/配置版本、SRAM 实际容量、IP/IO 数量 | 功能和容量变化单独解释，CPU 核面积与整颗 SoC 面积不得相除 |
| 工艺 | PDK/标准单元/SRAM/IO 库版本、温度、电压 | 不以制程比例换算面积/频率/功耗；不跨工艺宣称优化百分比 |
| 面积 | die、物理 core、active standard-cell+macro、实例总面积 | 单位 µm²；除以 10^6 才是 mm²。Pad/Cover 是否包含必须明确 |
| 性能 | 请求时钟、每个 corner/mode 的时序、约束覆盖、工作负载性能 | `1000/period_ns` 仅为约束 MHz；不得由 WNS=0 或一条路径推导可保证 Fmax |
| 功耗 | internal/switching/leakage、clock/macro/pad 分组、VCD/SAIF、覆盖率、 workload、PVT、寄生模型 | 同活动、同频率、同 PVT、同寄生方法才可讨论设计优化；工具估算与硅后测量分列 |
| 验收 | DRC/LVS、电气违规、antenna/density/offgrid、IR/EM、DFT 与流片要求 | 面积/功耗降低不得掩盖功能、DRC/LVS 或可靠性退化 |

`core_area` 是标准单元行/宏单元所在的物理核心边界；`i_core_wrap` 是 CPU 包装层次的实例面积，两者不是同一个“核面积”。报告 hierarchy 的父层已包含子层，不能重复相加。

## 可复现命令

在 WSL 项目根目录运行，输出文件以独立名称创建，存在时拒绝覆盖。需要本地原始归档，GitHub 上的小型 JSON 不能替代 DEF/报告。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/collect_croc_ppa.py \
  --source-run runs/croc-sg13g2-baseline-20260827-001 \
  --report-id croc-ppa-review-NEW-ID \
  --signoff-summary runs/croc-sg13g2-baseline-20260827-001/signoff.attempt-2/signoff_summary.json \
  --previous reports/ppa/croc-ppa-baseline-20260905-001.json \
  --output reports/ppa/croc-ppa-review-NEW-ID.json
```

对于 `croc_postroute_probe.tcl` 生成的已完成、未改版图的提取实验，追加 `--probe-run runs/<independent-probe-id>`。适配器核对输入 ODB/SDC 和输出报告/SPEF 哈希，并要求 `layout_modified=false`、面积一致。它保留历史 DRC/LVS 的来源，无法把未重新运行的检查升级为通过。

`delta.metrics` 保存面积 before/after/delta/percent 和 comparable。工艺、PDK、设计范围或 SRAM 不同则拒绝面积百分比。`same_physical_report_reused` 表示该轮未产生新的全芯片物理数据；`new_analysis_report` 表示分析报告变化，不能单凭此状态认定版图改进。提取前后功耗的原始差值另存 `raw_tt_estimate_change_mw`，`power_delta_mw` 仍为 `null`，防止把分析口径改变称为功耗优化。

若一轮只修改某个 leaf 或执行 CTS，则记录该阶段的 A/B 数据和该轮全芯片 PPA 基线引用。CTS 的面积、功耗和电气违规不可与 final-route 的数字作直接优劣比较；须在同阶段、同输入 checkpoint、同工具/库/约束下比较。新布局最终应重新跑 RCX/STA、DRC/LVS，并生成新的全芯片记录。

## 下一步 PPA 优化原则

先修复可观察的后端违规，再验证 PPA 代价。当前 clock 与 sequential 功耗占比较大，可以研究合法的 CTS 拓扑、缓冲和单元选择；现有寄存器文件面积也值得审查。但缺少 workload 活动时，这些只是实验优先级，不能当成可保证的节能幅度。禁止为得到漂亮 PPA 而放宽真实 IO 负载、切掉合法时序路径、关闭 DRC/LVS 规则或减少既定功能。

与行业芯片的比较应先复现同架构、同工艺、同容量的结果；当前 MLEM 是最接近的真实流片参考，但 SRAM 和外围功能不同。达到公开规则 PASS 后，仍需实际代工/MPW 对接要求中的 PDK/deck、封装/IO、电源可靠性、DFT/测试及签核资料认可，才能称为可流片。

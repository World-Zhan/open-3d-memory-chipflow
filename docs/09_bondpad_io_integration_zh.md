# 官方焊盘、真实 IO 与封环集成实验

SPDX-License-Identifier: Apache-2.0

2026-09-05：**官方环形焊盘配匹配 LEF、4 µm 外接引线，可清除单 IO fixture 的 Pad.kR、Pad.fR 和 Pad.d1R；再将焊盘内移 17.4 µm、IO 内移 21.5 µm，可清除完整原封环 fixture 的 Pad.dR。** 所有 fixture 整体仍因密度违规失败，未替换整芯片。整芯片电气、DRC、LVS 未闭环，当前不能流片。

## 使用真实库并核对物理抽象

本次使用 Croc 自带的 sg13g2_IOPadIn GDS。它与固定官方 PDK 同名单元具有相同 bbox，但递归展开的 41 个非空 layer/datatype 中有 13 层几何不同，另有 4 层标签不同；不是仅文件时间或元数据差异。不能静默替换 IO 库。见[单元比较](../reports/bondpad/input-io-cell-comparison-20260905-001.json)。

官方 M2 square70 PCell 从中心原点平移 (+35,+35) µm，形成 bondpad70_m2_ring。M2–TopMetal1 为环形，TopMetal2 为完整 70×70 µm；下层每层 1073.3404 µm²。LEF 保留真实孔洞，使用保守金属障碍区。本次 OpenROAD 实际读回 21 个矩形，使用独立 KLayout 逐层对比 GDS，六层金属 XOR 面积均为 0。该检查证明引脚抽象几何匹配，不证明电气或签核。

[引脚访问 run003 审计](../reports/bondpad/pin-access-20260905-003.json)记录实际扫描两个宏实例，macroGenAp=3234、macroValidPlanarAp=480、macroValidViaAp=0、macroNoAp=0。尚未逐个确认两个已连接 pad 端子的访问点，也未做实际布线。工具报告不支持部分 LEF58_ENCLOSURE，因此路由器内部检查不能代替完整公开 DRC。失败 run001（MTerm API 不存在）与 run002（deprecated routing-layer 参数）及其脚本均保留；run003 使用 set_routing_layers 后调用 pin_access。

## 单 IO 的完整公开 DRC A/B

实际 IO 固定为规范化 R0 坐标 (0,0)，bondpad 位于 (5,-70-gap) µm；新引线只占外部间隔，不延伸进入其他 IO 金属。原 IO pad 每层已有 3 µm 退出长度，4 µm 引线补齐 7 µm。六层金属均验证 pad→lead→IO pin 区域连续，未宣称完整 LVS。

| 同一 fixture 范围 | 所有 marker | 密度 marker | Pad 类 marker | 整体 DRC |
|---|---:|---:|---:|---|
| 原宏，gap=0 | 159 | 6 | 153（kR=144，d1R=1，fR=8） | FAIL |
| 官方宏，gap=0 | 14 | 5 | 9（d1R=1，fR=8） | FAIL |
| 官方宏，gap=4 µm | 5 | 5 | 0 | FAIL |
| 官方宏，gap=10 µm | 5 | 5 | 0 | FAIL |

每臂均完成 40 项公开规则任务，包括 recommended、density、31 项 antenna 分类与 offgrid。见[输入/输出哈希复核和 DRC 结果](../reports/bondpad/pad-io-integration-audit-20260905-001.json)。不同 bbox 的密度数量不能外推为整芯片密度改善。

## 完整原封环的边距 A/B

从历史 filled GDS 提取完整 sealring_top 子树，保留全部层级和 2×2 mm 外边界；没有裁剪产生人为端点。只加入一个真实 IO 和官方焊盘，其他 IO、core、全芯片填充均未包含。这是封环边界实验，不是完整芯片实现。

| 同一完整封环范围 | 焊盘内移 | IO 内移 | 外接间隔 | Pad.dR | 所有 marker | 密度 marker |
|---|---:|---:|---:|---:|---:|---:|
| Control | 0 | 4 µm | 4 µm | 1 | 106 | 105 |
| Candidate | 17.4 µm | 21.5 µm | 4.1 µm | 0 | 105 | 105 |

候选开窗→选中 IO Active 间距 12.2 µm（要求 11.2），开窗→封环 Active 间距 25.1 µm（要求 25）；所有 Pad 类 marker 均为 0。两臂各 40 项规则任务完整执行，整体均 FAIL。

105 个密度 marker 分为 9 个全局与 96 个 800×800 µm 局部窗口违规：AFil.g2、M1Fil.h–M5Fil.h 各 16 个。原审计只检查 description 中的 density 单词，漏分类了描述为 coverage ratio 的局部密度；原审计保持不变，[追加审计](../reports/bondpad/pad-seal-integration-audit-20260905-001.json)依据真实 marker 的 Local Density Window Violation / Global Density Violation 分类，未减少违规总数或改变 FAIL。

## 整圈集成仍需解决的约束

实际纯输入 IO 有九个，都在左边；本实验由 pad_jtag_tdi_i 的 FW 方向规范化而来。其物理 GDS 比 LEF 两侧各多 0.62 µm。[邻域探针](../reports/bondpad/input-io-movement-constraints-20260905-001.json)证明：只移动选中 IO，未移动的邻居 Active 与新开窗距离仅 7.1 µm，仍违反 11.2 µm。因此单颗 fixture 的结果不能直接推广为整圈通过。

下一步需要整体重新布置相关 IO、filler、PG 轨道和角单元，验证相邻拼接与供电。原选中实例的 DEF 只观察到 iovdd/iovss 显式连接，LEF 中的 vdd/vss 是否由其他机制正确连接仍需独立检查。沿边现有输入 IO 间距 89 µm 与源代码中的 package pitch 建议也需核对，不能据此认定封装合格。

## 本轮 PPA 与行业对照

这次没有新增完整芯片实现或寄生提取，因此新增整芯片功耗、时延、面积结果均为未知。官方 bondpad 的 70×70 µm 外形未变；gap=4/4.1 时，每层新增外接引线面积 280/287 µm²。六层金属面积不能直接相加为芯片面积。内移 IO 会消耗内部布局和布线空间，实际 RC、时序、功耗代价需重新布局/布线后测量。

仍参考原整芯片：sealed GDS 4.000000 mm²，DEF electrical die 3.671056 mm²，4 KiB SRAM，100 MHz 为约束，TT 43.6 mW 为单 typ RC 下无工作负载活动的工具估算。最新独立 CTS 候选仍是 active 0.7208351136 mm²、TT 56.4 mW、slew/cap/fanout=71/135/0，未重新布线。

最接近的行业对照仍为 IHP 130 nm 的 ETH MLEM/Croc：24 KiB SRAM、4.995225 mm²、官方 typical 80 MHz/1.2 V；本地容量、边界、约束与签核成熟度不同，不报告性能或面积优胜比例。来源和 Ibex core 对照见[逐轮 PPA](../reports/ppa/20260905_review_zh.md)及[固定来源索引](../reports/ppa/comparison_sources_20260905.json)。

## 复现与剩余门槛

原始 run 与脚本哈希保持不变。大 GDS/ODB/lyrdb 留在本机 runs；Git 只归档脚本、小清单、审计、LEF 和最小 DEF。新 run 必须使用不同 ID。

```bash
python3 scripts/run_bondpad_io_fixture.py --run-id croc-bondpad-io-ab-<new-id>
python3 scripts/run_bondpad_seal_fixture.py --run-id croc-bondpad-seal-ab-<new-id>
python3 scripts/audit_bondpad_integration.py --run croc-bondpad-io-ab-20260905-001 --output /tmp/pad-io-audit-new.json
PYTHONDONTWRITEBYTECODE=1 make test validate-contracts report
```

这些初版 runner 尚无容器超时；后续重跑前需加独立的有界执行/回收封装。stdout 的 tool_completed 表示子进程返回，只有审计的 rule_execution_complete 证明规则任务完成，fixture_drc_passed 才表示零 DRC。

晋级顺序：相邻 IO/PG/封装边界 → 匹配物理抽象和真实路由 → 整圈及整芯片 density/antenna/offgrid/DRC → 提取 STA/电气 → 严格 LVS 与其他流片要求。LVS 继续遵循受支持的 leaf/最小父级修复路径，不启动未经前置验证的 full-chip attempt 3；不关闭规则或加入豁免。

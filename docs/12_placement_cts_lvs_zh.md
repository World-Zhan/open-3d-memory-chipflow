# 完整布局、CTS 与 LVS 阶段定位

SPDX-License-Identifier: Apache-2.0

更新：2026-09-09。新完整 IO 环候选已从 floorplan 推进到 placement 和 CTS。**CTS 的 setup/hold 为 0，但 slew/cap/fanout 为 71/135/4，电气验收仍 FAIL；没有新完整布线或 DRC/LVS 签核结果。** 本轮未改变 100 MHz 约束、15 pF IO 负载或严格签核规则。

## 本轮真实执行与结构边界

| 实验 | 实際结束 | 结论 |
|---|---|---|
| 完整 placement 001 | 249.41 秒、exit 0、无 OOM | 原运行于 9 月 5 日已完成；9 月 9 日恢复核实，未重复布局 |
| 独立 placement STA 读回 001 | baseline/candidate 均真实 exit 0、无 OOM | 复现 hold 1 与功耗异常，排除仅由旧进程缓存造成的解释 |
| 完整 CTS 001 | 47.55 秒、exit 0、无 OOM | cluster size 8，加原约束下 hold 修复，插入 1 个 hold buffer；未继承旧分支 ECO |
| 严格 DCN 单叶阶段观测 001 | 3.54 秒、exit 0、31 快照 | 观测前后库存不变，实际 LVS 仍 NoMatch/FAIL |

[placement 结构审计](../reports/placement/full-io-structure-20260909-001.json)保留 28,140 个非透明实例；88 个最终单元替换的完整逻辑/状态签名一致，92 个输入置换按真实标量 Liberty 真值表证明。buffer 从 2,436 增至 4,300，tie 从 26 增至 950。IO 192、SRAM 2、顶层端口 52、物理 pin box 64 及 die/core/供电/引线几何通过检查。这是限定结构证明，不是完整形式等价。

CTS 的通用 placement 检查首先拒绝了开路输出的 clkload 单元，此次拒绝记录保留。独立 [CTS 审计](../reports/placement/full-io-cts-extended-audit-20260909-001.json)逐项证明 533 个新增 clkload 的输出无连接、1 个 delay 单元的真实函数为 A、1 对 inverter 仅改名且端点等价；剩余 28,140 个功能实例得到核对。负载仍计入实际面积、时钟电容和 PG 检查。不能用 placement 的 PASS 自动通过 CTS。

CTS 导出 962 个 CLOCK net，其中 14 个带 NDR，保留 5 个 NDR 定义。200 个内部 buffer 分支和 743 个末级分支没有 NDR，完整覆盖清单已归档；metadata 一致性通过，但 routing NDR policy 的资格仍为 UNVERIFIED。此结构结论不证明时钟波形、最终布线策略或完整形式等价。

两个实际阶段的 `check_placement -verbose` 无错误；VDD/VSS 的普通 `check_power_grid` 均报告 All shapes connected，没有使用 `-floorplanning`。它们不证明 IO 电源混网、IR/EM 或电路 LVS。

## 同阶段 PPA 与行业对照

面积为 CORE+BLOCK，即标准单元加 SRAM，不含 IO/焊盘。TT 功耗均为工具默认活动估计；当前候选出现 SRAM 动态功耗为零，不能计算节能收益。

| 同阶段比较 | 原版 active mm² | 新候选 active mm² | 原版→候选 TT 原始 mW | 新候选 setup/hold/slew/cap/fanout |
|---|---:|---:|---:|---|
| placement 原阶段报告 | 0.671906 | 0.673076 | 37.5→5.47（异常） | 0/1/71/135/0 |
| fresh placement 读回 | 0.671906 | 0.673076 | 37.5→5.45（异常） | 0/1/71/135/0 |
| CTS | 0.685563 | 0.721601 | 43.6→5.46（异常） | 0/0/71/135/4 |

新 placement 最坏 max slack 为 +0.48 ns；新 CTS 为 +0.21 ns，二者 WNS/TNS 均 0。placement 的唯一 hold 路径从 debug master 地址寄存器到 bank 0 SRAM A_ADDR[3]，FF 角约 −0.01 ns；CTS 修复后 hold 计数为 0。以上使用放置寄生估计，不是提取后 MMMC，也不能将 100 MHz 目标换算成已实现 Fmax。CTS 原版同阶段 fanout 为 200，新候选仍剩 4；旧分支 ECO 的 fanout 0 不属于本候选。

新候选电气边界 3.896676 mm²，规划含封环 4.235364 mm²；还没有新完整 sealed GDS。placement active 面积较原版同阶段增加约 0.174%；CTS 增加约 5.257%。IO 环和 CTS 条件同时改变，这些比较不能分离单一参数的优化贡献。

| 对照项目 | 工艺 / SRAM | 芯片面积 | 频率证据 | 功耗与成熟度 |
|---|---|---|---|---|
| 本地新候选 | IHP 130 nm / 4 KiB | 电气 3.896676；封环规划 4.235364 mm² | 约束 100 MHz，Fmax 未知 | 功耗未合格，CTS 电气 FAIL，未流片 |
| ETH MLEM/Croc | IHP 130 nm / 24 KiB | 4.995225 mm² | 作者典型 80 MHz / 1.2 V | 上游已有流片/硅验证材料，无可比功耗 |

行业来源沿用 2026-09-05 的[固定版本索引](../reports/ppa/comparison_sources_20260905.json)。容量、外围和面积边界不同，不能据较小面积或 100 MHz 约束宣称优于同类芯片。本轮[机读 PPA](../reports/ppa/croc-ppa-placement-cts-20260909-001.json)保留未知值为 null。

## 功耗诊断与真实失败

fresh 读回确认新旧 SDC 除生成日期外一致。旧 bondpad master 的实际方向为 INPUT，新 master 为 INOUT，是待验证的时钟活动传播根因候选；未建立因果结论。两次受限探针均保留原候选：第一次已输出功耗和方向，随后对无 Liberty 焊盘调用 `is_clock` 属性发生 SIGSEGV/exit 139；第二次因固定版本缺少 `dbMTerm.setIoType` 而 exit 1，尚未改变方向或执行单因素功耗比较。两次均无 OOM，不能报告完整探针或 A/B 成功。

详见[功耗诊断](../reports/ppa/croc-power-direction-diagnostic-20260909-001.json)。当前保存 5.45/5.46 mW 仅为工具原始诊断数值；真实 workload 功耗、节能比例均未知。下一次需先用小型 API 能力检查确认安全接口，再独立建立方向/活动来源的有效 A/B。

## 严格 LVS 的具体问题

[31 阶段快照审计](../reports/lvs/dcn-stage-snapshots-20260909-001.json)与[源码/API 核对](../reports/lvs/dcn-reader-extraction-review-20260909-001.json)给出：

1. layout raw extraction 中 guard 孤立网已存在。普通 ntap/nwell 的真实物理路径不等于被标记的 ntap1 器件；此网没有器件端子，在 RF mapping 内无条件 `target_netlist.purge` 被删除。
2. schematic `XR0 anode sub! ptap1 A=141.253p P=47.54u` 被读成空参数化 PTAP1 子电路。当前 CustomReader 未定义 `wants_subcircuit`；writer 的 PREFIX_MAP 不会自动注册输入 X 器件。
3. align 删除空 tap 子电路；simplify 再删 ANODE/GUARD 并将两个 diode 合一。源 PDK 与清理行为均未修改。
4. 观测运行与历史控制的 LVSDB cross-reference、最终两侧文字网表完全一致。该一致性证明观测有效，严格 LVS 本身仍 FAIL。

下一步先做 reader-only 回归：仅识别 PTAP1/NTAP1，将 X 路径接到已有 CustomTap 实现，核对端子/单位/参数并保留其他未知子电路。提取 tap A/P=141.2964 µm²/221.76 µm 与 CDL 141.253 µm²/47.54 µm 的差异仍待解释；guard 的物理/器件模型问题与父级闭合的重复电极也各自保留。不得用禁用 purge、关闭严格端口或虚接掩盖差异。

没有新 parent/full-chip LVS attempt 3。旧 IO-only 131 个 density marker（8 全局、123 局部）仍为独立 FAIL，不是新完整芯片的 DRC 结果。

## 后续门槛与复现

继续处理本 CTS 的四个 fanout 端点，保持原功能连接、CLOCK/NDR 和 PG；电气剩余还需处理 71 个 IO slew 与 135 个 cap，保持 15 pF 和库限制。先修正功耗分析可信度及 LVS reader/模型，再决定受限 routing/fill/seal、提取 STA 与严格完整 DRC/LVS。真实流片还需要确认工艺版本/MPW 验收、封装、供电/活动、完整 corners/modes、IR/EM 和 DFT 输入。

用户无需修改长期目标或降低通过标准；目前不需要再提供大篇 skill。AI skill 搜索已经形成[分阶段筛选](04_ai_chip_skills_zh.md)，本轮继续使用本项目固定工具和证据门禁。工艺和产品输入将在对应门槛需要时提出，不能由 AI 假设为已确认。

```bash
cd /home/james_zhan/projects/open-3d-memory-chipflow
PYTHONDONTWRITEBYTECODE=1 make test validate-contracts
```

新 EDA runner 使用独立 run ID，已有 run ID 不可重跑覆盖：`scripts/run_croc_full_placement.py`、`scripts/run_croc_placement_readback.py`、`scripts/run_croc_full_cts.py`。CTS 显式要求源 placement 的结构审计；命令、输入/输出 SHA-256、实际容器退出/OOM 状态均在对应 manifest 中。大型 ODB/DEF/ZIP 留本地，发布小型可核查证据。

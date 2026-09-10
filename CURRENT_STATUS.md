# 当前芯片流程状态

SPDX-License-Identifier: Apache-2.0

更新：2026-09-10。**原版 Croc 已完成 RTL→综合→物理实现→GDS 的执行，但电气验收、DRC 和 LVS 尚未闭环；自研存储扩展现处于规格/验证计划阶段。** 验证贯穿全流程，不能只放在 GDS 之后。

## 各阶段实际进度

| 阶段 | A：Croc/IHP 基线 | B：Pin3D/ASAP7 研究 | C：自研存储扩展 |
|---|---|---|---|
| 架构分析 | 复用原 Croc；非新架构 PPA 达标证明 | GCD/F2F 研究；HBT 真实 pitch/容量合同已验证 | 最小 C1/C2/C3 规格与验收矩阵已建立 |
| RTL 与功能验证 | 原 Hello World RTL/门级仿真通过；不等于新增 IP 完整覆盖 | 复用 GCD；无自研 3D memory RTL | C1 OBI endpoint 尚未实现/仿真 |
| 综合 | 原版 Yosys+Slang 通过 | 研究 flow 的既有网表 | not_run |
| 后端 | 原 APR/GDS 电气 FAIL；新完整 placement/CTS 已执行，setup/hold=0，slew/cap/fanout=71/135/0；新 route 未执行 | strict pin access 已修复；旧 route DRC=642；新容量 A/B 未布线 | not_run |
| 验证/签核 | merged DRC=1585/12 类；maximal raw=652；LVS mismatch | research_only；route/3D closure 未完成 | 测试计划已写，RTL/综合/物理结果均未产生 |

## 2026-09-10 最新推进

**fanout 已清零，整体仍未签核。** 新增八颗时钟 buffer 后 setup/hold/slew/cap/fanout=0/0/71/135/0。独立结构、普通放置/核心 PG、完整 SDC 与原 CLOCK/NDR 元数据检查通过；43 条 15 pF 命令保持，NDR 布线政策仍 UNVERIFIED。

- 同 CTS 阶段 active 面积 0.7216007904→0.721789488 mm²（+188.6976 µm²）；原始 TT 仍为异常 5.46 mW。电气 die 3.896676 mm²、封环规划 4.235364 mm²。
- 功耗单因素 tiny/full 对照证实无库 bondpad 方向引发低功耗失真：同 placement 的 INOUT→INPUT 分析视图为 5.45198→37.47741 mW，SRAM 动态功耗恢复。但 GPIO slew 同时变化，未作为设计修复，workload 功耗仍未知。
- tap reader 已通过 20 用例/40 断言（12 负例），真实单叶中 tap/ANODE 得以保留；严格 LVS 两臂仍 FAIL，未配对器件 4→5，不称违规减少。周长和 guard 问题保留，无新 parent/full-chip LVS。
- IO 模型问题有官方推进路径：本地固定 PDK 已包含 IHP PR #1033，更新后的 Out16/InOut30 TT cap=20/40 pF；需 GDS/CDL/LEF/Verilog/Liberty 成套验证和迁移，未套用到旧 IO 版图。当前 SRAM 已是 0.064 pF，剩余 64 个 SRAM cap 需独立处理。
- 对照仍为 MLEM/Croc：24 KiB、4.995225 mm²、典型 80 MHz；本地 4 KiB、100 MHz 约束，不能宣称 PPA 优势。

详情：[本轮说明](docs/13_cts_reader_power_zh.md)、[PPA](reports/ppa/croc-ppa-cts-reader-power-20260910-001.json)。以下按日期保留此前阶段结果；15 pF 未降低，仍无 public/foundry signoff。

## 2026-09-09 推进记录

新完整 IO 环候选现已完成 placement 与 CTS，**电气仍 FAIL，尚不可流片**。placement 的结构审计通过；CTS 独立审计见下文链接，不能继承原 placement 或旧 ECO 的结果。原布局运行在 9 月 5 日已经正常结束，本轮只恢复核实，没有重复运行。

- **新 CTS：** setup/hold=0，WNS/TNS=0；slew/cap/fanout=71/135/4。以 cluster size 8 建树，另插入 1 个 hold buffer；普通放置/核心 PG 检查通过，未重新布线。
- **同阶段 PPA：** placement active 0.671906→0.673076 mm²；CTS 0.685563→0.721601 mm²。新 CTS TT 原始值 5.46 mW 存在 SRAM 动态功耗为零的异常，不能作为节能或 workload 功耗。电气 die 3.896676 mm²、封环规划 4.235364 mm²。
- **功耗诊断：** fresh 读回仍复现异常；旧 INPUT/新 INOUT 焊盘方向已确认，因果未证实。两个 API 探针分别 exit139/exit1，完整保留，未成功执行方向 A/B。
- **严格 LVS：** 31 个观测快照定位 layout guard 在 RF purge 删除、schematic 空 PTAP1 在 align 删除；最终结果与历史控制一致且仍 FAIL。下一步是 reader-only 支持与参数回归，无新 full-chip attempt 3。
- **行业对照：** MLEM/Croc 为 IHP130、24 KiB、4.995225 mm²、典型 80 MHz；本地为 4 KiB、100 MHz 约束，不能得出 PPA 优势。无需降低长期目标或先补大篇 skill。

完整报告：[布局/CTS/LVS 本轮说明](docs/12_placement_cts_lvs_zh.md)；[机读 PPA](reports/ppa/croc-ppa-placement-cts-20260909-001.json)；[CTS 独立审计](reports/placement/full-io-cts-extended-audit-20260909-001.json)。以下 9 月 5 日实验记录继续作为分阶段历史依据。

## 此前推进记录

用户当前目标是持续收敛到可流片状态，严格 DRC/LVS 等后端检查必须通过，每轮附 PPA 与同类芯片比较。当前优先推进 A 轨物理闭环；C1 仍可独立开发，但不能替代后端目标。

- **已对原始 routed ODB 实际执行 OpenRCX/SPEF 提取与读回。** [RCX 清单](runs/croc-postroute-rcx-20260905-001/manifest.json)绑定源哈希；原版图未更写。单 typ RC 配 TT/FF 库得到 WNS/TNS、setup/hold=0，但 slew/cap/fanout=71/96/200，仍 FAIL。TT/FF 工具功耗为 43.6/55.2 mW；不是完整 RC corner/MMMC 签核。
- **CTS 同阶段 A/B 与分支 ECO 完成。** 默认→cluster size 8 使 fanout 200→4，再插入八个 buffer 清为 0。最新 [ECO 003](runs/croc-cts-branch-eco-20260905-003/manifest.json)保留 CLOCK/NDR，且[结构校验](runs/croc-cts-branch-eco-20260905-003/structural_validation.json)通过。候选 slew/cap=71/135；未重新布线或做 DRC/LVS。
- **PPA 代价已量化。** 同 CTS 阶段 control→ECO 003：active 0.6855631776→0.7208351136 mm²，TT 工具功耗 43.6→56.4 mW；边界仍 3.671056 mm²。这是一项付出面积/功耗代价的电气候选，尚未成为最终实现。见[逐轮 PPA 与行业对照](reports/ppa/20260905_review_zh.md)及[实验复现说明](docs/08_backend_experiments_zh.md)。
- 保留失败 ECO 001（固定工具缺少 insert_buffer API）与被替代的 002（未继承 NDR）。不从另一版本源码推断本地二进制支持的 API。

- HBT 容量合同已提交并同步：`d3342a45d6aff33ad2b18f08d3b7cd5e16568015`。partition demand=62，floorplan core=14.58×14.31 µm，可用 90 个 site；本轮仅 partition/pre/floorplan，没有新 placement/CTS/route。见[容量 A/B](runs/pin3d-hbt-capacity-contract-20260903-001/stage_ab.json)。
- 新增[归档电气复核](runs/croc-acceptance-audit-20260905-001/summary.json)：WNS/TNS=0，setup/hold=0，但 **slew=76、capacitance=71、fanout=200**。修正 collector、signoff parser、JSON 合同；这些项缺失或非零均不再通过。历史 stage 记录保持原样。
- `make report` 显示独立复核，并选择最新 signoff attempt；较新 attempt 没有有效汇总时，不回退成旧结果通过。
- 建立[AI skill 筛选](docs/04_ai_chip_skills_zh.md)、[项目 skill](.agents/skills/chipflow-evidence/SKILL.md)和[最小存储规格/验证计划](docs/05_memory_spec_zh.md)。第三方工具尚未安装或本地复现。

## 最新完整 IO 环与严格 LVS A/B

- **完整功能 floorplan 已实现。** 新 [005 候选](runs/croc-full-io-floorplan-20260905-005/manifest.json)包含原 Croc 核心、两颗 SRAM 和完整真实 IO 环；30,474 个原实例、111,658 个非 PG 引脚、52 个顶层端口保留，61,334 个供电引脚显式连接。192 个 IO 环实例与已验证试件一致，64 条引线共 384 个金属矩形。此 floorplan 随后派生的新 placement/CTS 已完成，见本页 9 月 9 日更新；尚未信号布线，未继承旧 CTS ECO。
- **物理端子与 floorplanning PG 通过独立读回。** 64 个真实 TopMetal2 引脚 box 逐端口/net/几何与焊盘对应；VDD/VSS 均有实际 `PSM-0040 All shapes ... connected`。新增[纯读审计](reports/floorplan/full-io-readback-audit-20260905-001.json)验证 105 个唯一文件哈希。PG PASS 仅限定 `-floorplanning`，不覆盖放置后标准单元、完整混网短路、IR/EM 或 LVS。
- **时序诊断仍有问题。** floorplan 中已有布局前报告：reset endpoint 在两个组的 slack 为 −67.43/−70.35 ns，PG 类型修正前有四路供电端口延迟/未约束警告。重复打印不重复计数；完整 hold/slew/cap/fanout 未知。后续 placement/CTS 的放置寄生估计已执行且电气仍 FAIL；这里保留 floorplan 当时的诊断。
- **IO-only DRC 规则执行已补齐，整体仍 FAIL。** 同源 deep 单线程 maximal 实际 exit 0、0 marker、无 OOM；[v3 组合审计](reports/bondpad/io-ring-composite-drc-20260905-003.json)覆盖 39 项原健康任务 + 1 项独立 maximal，共 131 个 density marker（8 全局、123 局部），Pad/其他非密度为 0。原 Signal 11、flat exit 137 与 v1/v2 失败保持；该结果不属于新的完整功能 floorplan。
- **IO-only PG 金属/过孔连通性仍为限定 PASS。** 四路供电各一个独立分量，覆盖 128 宏 PG 区域与各自供电焊盘，混网 0；不含 well/substrate/contact、电路 LVS、IR/EM 或封装连接。
- **严格 LVS 根因更清楚，仍 FAIL。** 实际父级通过 M1→Via1→M2 接通两个 DCN cathode / DCP anode；guard 确有 288 contacts 与普通 ntap/nwell 路径。历史 strict-deep 父级整体 FAIL，3 个 NoMatch、2 个 Skipped；9 月 9 日阶段观测已定位具体删除点，下一步为 reader-only 回归；无虚接、无新 full-chip attempt 3。
- **同阶段 PPA：** CORE+BLOCK 为 0.6539563296 mm²，与原 floorplan 相同；PAD_SPACER 增加 0.010080 mm²。新电气边界 3.896676 mm²，规划含封环 4.235364 mm²（较历史 4.0 增加 5.8841%）；新完整 sealed GDS、功耗/Fmax 尚无结果。见[本轮完整说明](docs/11_full_floorplan_readback_zh.md)与[PPA JSON](reports/ppa/croc-ppa-full-floorplan-20260905-001.json)。

## 已归档焊盘局部诊断


- 固定官方 PCell 已生成独立候选；完整公开规则 40 项任务逐项复核完成，包含推荐规则、density、antenna、offgrid。原焊盘 fixture 为 153 markers（144 个 Pad.kR + 9 个全局密度），两个官方候选均为 9 markers（全部全局密度），**Pad.kR 144→0；fixture 整体仍 FAIL**。见[完整 DRC 复核](runs/croc-bondpad-drc-ab-20260905-002/audit.json)。
- 原整芯片开窗下的 9,216 颗 TopVia2 来自 64 个焊盘宏（每个 144），并非路由新加的 via。这个物理过孔数与历史 merged Pad.kR=576 是不同口径。官方宏的下层金属是环形，不能直接搭配原 LEF 的全 70×70 µm 引脚区域；坐标原点也需平移。见[焊盘诊断](docs/07_bondpad_diagnosis_zh.md)。
- **真实 IO 集成 A/B 完成。** 使用实际 Croc IOPadIn 与匹配 LEF 的官方焊盘；gap=0→4 µm 后 Pad 类 marker 9→0，候选剩余 5 个全局密度 marker，整体 FAIL。原宏 control 有 153 个 Pad marker。见[输入/输出哈希与完整规则审计](reports/bondpad/pad-io-integration-audit-20260905-001.json)。
- **完整原封环 A/B 完成。** 焊盘内移 17.4 µm、IO 内移 21.5 µm，使 Pad.dR 1→0；候选剩余 105 个密度 marker（9 全局、96 局部窗口），整体 FAIL。保留完整 2×2 mm sealring，仅放一个 IO，不含其他芯片实例和填充，不能作为整芯片密度结果。见[封环审计](reports/bondpad/pad-seal-integration-audit-20260905-001.json)。
- **引脚抽象已独立核对。** OpenDB 读回 21 个矩形，六层金属与官方 GDS 的 XOR 面积均为 0；严格 pin_access 实际完成，macroNoAp=0、有效 planar AP=480、via AP=0。未证明逐端子/跨层接入或真实布线，保留 LEF58 不支持警告和两个失败 API 尝试。见[访问审计](reports/bondpad/pin-access-20260905-003.json)。
- **此前单 IO 晋级的门槛。** 单独移动选中 IO 后，未移动邻居的 Active 距开窗仅 7.1 µm（要求 11.2）；需协同移动 IO/filler/PG 并验证角单元、封装间距和内部布线空间。实际 Croc 与固定官方 IOPadIn 有 13 层几何差异，不静默替换库。详见[集成实验与下一步](docs/09_bondpad_io_integration_zh.md)。
- 上述局部试件没有替换整芯片版图。原实际 filled GDS 含 sealring 的外边界为 2×2 mm=4.0 mm²，与 DEF 电气布局 3.671056 mm² 并列记录；这是边界口径补全，不是面积变化。

## 当前最需要改进的内容

1. **补齐验收质量。** 本次已堵住电气违规漏检。还需逐 corner/mode 审核时序约束、例外、未约束路径和寄生来源。历史 finishing 中 RCX/SPEF 被注释；本轮独立补做单 typ RC 提取/读回，但 TT/FF 库并不等于完整 MMMC。仍需验证真实 corner/mode、约束覆盖及 RC 模型资格。VDD/VSS connected 也不等于 IR-drop/EM 通过。
2. **按根因处理 A 轨。** 电气上保留 15 pF IO 负载：71 个 slew 违规集中在输出 pad，提取后还观察到 25 个 SRAM 输出 cap 违规；不能静默降低负载或放宽库限制。DRC 的 1585 merged 包含 1577 个 Pad 类 marker 和 8 个 density marker，先做独立焊盘几何/规则 fixture，再考虑整芯片重跑。 [IHP #1130](https://github.com/IHP-GmbH/IHP-Open-PDK/issues/1130)本次检索仍 open，无评论。现已证实叶重复电极依赖真实父级金属闭合；已定位 guard/tap 的提取与清理阶段，需先完成 tap reader/参数和 guard 模型回归，再用受支持、保留真实层次连接的最小 fixture 达到 strict exact，才考虑 full-chip attempt 3。历史 flat 的 52/135057 端口问题与 IO leaf mismatch 分别记录。未完成这些门槛前，不重跑 full-chip。
3. **推进 B 轨几何合法性。** 530/642 个 cut-spacing 已有逐对几何证据；容量扩展解决了可容纳数量的问题，但未证明 HBT 落在 1.6 µm legal lattice 和合法访问窗口。下一步做受限 lattice/window 检查，再决定 placement；不直接 full route/full smoke，剩余 112 个金属 marker 仍须独立处理。
4. **让 C 轨开始形成自己的功能证据。** 下一实施单元是 C1 OBI CSR endpoint，先独立测试与模块综合，再以 patch/新 run 集成。无需等 A/B 全部通过才能编写模块；物理整合仍受对应门槛约束。

## 是否需要额外 skill / 规范

目前可以独立推进受限后端修复实验、PPA 与验收器，不需要用户先准备庞大 skill 包。通用技能不能替代具体产品输入：目标 SRAM/DRAM、容量、带宽、延迟、面积/功耗、真实工艺和键合参数，在超出当前学习基线前需要确认。现有 100 MHz、4 KiB 系统 SRAM 与研究 HBT 参数分别属于不同轨道，不能拼成已达标的先进 3D 产品。

## 复核入口

```bash
cd /home/james_zhan/projects/open-3d-memory-chipflow
PYTHONDONTWRITEBYTECODE=1 make test validate-contracts report
python3 scripts/audit_croc_acceptance.py --source-run runs/croc-sg13g2-baseline-20260827-001 --require-pass
```

最后一条当前预期 exit 1，表示电气验收失败；不启动 EDA。历史详情见[基线里程碑](runs/croc-sg13g2-baseline-20260827-001/MILESTONE.md)。本页更新当前解释，不更写历史原始结果；本仓库仍无 `public_rule_signoff` 或 foundry signoff 成果。

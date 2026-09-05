# 当前芯片流程状态

SPDX-License-Identifier: Apache-2.0

更新：2026-09-05。**原版 Croc 已完成 RTL→综合→物理实现→GDS 的执行，但电气验收、DRC 和 LVS 尚未闭环；自研存储扩展现处于规格/验证计划阶段。** 验证贯穿全流程，不能只放在 GDS 之后。

## 各阶段实际进度

| 阶段 | A：Croc/IHP 基线 | B：Pin3D/ASAP7 研究 | C：自研存储扩展 |
|---|---|---|---|
| 架构分析 | 复用原 Croc；非新架构 PPA 达标证明 | GCD/F2F 研究；HBT 真实 pitch/容量合同已验证 | 最小 C1/C2/C3 规格与验收矩阵已建立 |
| RTL 与功能验证 | 原 Hello World RTL/门级仿真通过；不等于新增 IP 完整覆盖 | 复用 GCD；无自研 3D memory RTL | C1 OBI endpoint 尚未实现/仿真 |
| 综合 | 原版 Yosys+Slang 通过 | 研究 flow 的既有网表 | not_run |
| 后端 | APR/GDS 已生成；新复核电气 FAIL | strict pin access 已修复；旧 route DRC=642；新容量 A/B 未布线 | not_run |
| 验证/签核 | merged DRC=1585/12 类；maximal raw=652；LVS mismatch | research_only；route/3D closure 未完成 | 测试计划已写，RTL/综合/物理结果均未产生 |

## 本次推进

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

- **完整真实 IO 环 GDS 已生成并核验。** 192 个实例，64 IO/64 官方焊盘/60 filler/4 corner；90 µm pitch、4.2 µm 间隙与 384 个实际引线矩形均已核对。160 个原信号端子、512 个 PG 端子、64 个焊盘连接显式保留。候选不含核心逻辑/核心路线/密度填充。
- **DRC：** 原合并报告有 131 个密度 marker（8 全局、123 局部窗口），Pad/其他非密度为 0，但最大规则在报告 0 后 Signal 11 崩溃。相同输入/deck 的 flat/单线程重跑实际 exit 137，规则执行仍不完整；不能将该原合并计数当成完整 DRC 结果或 PASS。
- **PG 金属/过孔连通性 PASS：** 4095 个实际金属分量、6016 条过孔连接；四路供电各一个独立分量，覆盖全部 128 宏 PG 区域及各自 4 个供电焊盘，混网 0。没有以同名标签虚接；不包含核心 PDN、well/substrate/contact、电路 LVS、IR/EM 或封装连接。
- **严格 LVS：** 受支持 upstream purge 修复的两叶 × A/B 四次仍全部 FAIL，提取网表/匹配摘要未变。IO GDS/CDL 在 pinned/main/dev blob 相同。下一步追踪实际父级上层金属回路和 guard 推导，尚未启动 full-chip attempt 3。
- **本轮 PPA：** 候选电气边界 3.896676 mm²，含封环 4.235364 mm²（较原 4.0 增加 **5.8841%**）；IO+cover 实例面积增加 0.01008 mm²。无新整芯片功耗/Fmax/active。见[完整实现与证据](docs/10_io_ring_implementation_zh.md)及[本轮 PPA](reports/ppa/croc-ppa-io-ring-20260905-001.json)。

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
2. **按根因处理 A 轨。** 电气上保留 15 pF IO 负载：71 个 slew 违规集中在输出 pad，提取后还观察到 25 个 SRAM 输出 cap 违规；不能静默降低负载或放宽库限制。DRC 的 1585 merged 包含 1577 个 Pad 类 marker 和 8 个 density marker，先做独立焊盘几何/规则 fixture，再考虑整芯片重跑。 [IHP #1130](https://github.com/IHP-GmbH/IHP-Open-PDK/issues/1130)本次检索仍 open，无评论。需受支持修复使 DCN/DCP strict-deep leaf exact，再最小父级 fixture exact，才考虑 full-chip attempt 3。历史 flat 的 52/135057 端口问题与 IO leaf mismatch 分别记录。未完成这些门槛前，不重跑 full-chip。
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

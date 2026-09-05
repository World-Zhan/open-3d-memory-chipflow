# 完整功能设计 floorplan、供电读回与 DRC/LVS 证据

SPDX-License-Identifier: Apache-2.0

2026-09-05。**新 IO 环已集成到包含原 Croc 核心和两颗 SRAM 的独立 floorplan。结构、物理顶层端子及 floorplanning 模式的核心供电连接通过复核；新候选尚未完成标准单元布局、CTS、信号布线和签核。** 本轮没有修改原始 routed 基线或源 PDK。

## 实际实现与独立读回

实际运行：[完整 floorplan 005](../runs/croc-full-io-floorplan-20260905-005/manifest.json)、[fresh ODB readback](../runs/croc-full-io-floorplan-readback-20260905-001/manifest.json)。固定 OpenROAD `v2.0-27244-gfecb04286`，工具镜像由 manifest 的 SHA-256 锁定。005 实际退出 0；完整原网表来自历史已归档综合结果，未继承独立 CTS ECO 003。

| 检查 | 实际结果 | 验收范围 |
|---|---|---|
| 原功能结构 | 30,474 个原实例、111,658 个原非 PG 引脚、52 个顶层端口保留 | 实例/主单元/逐引脚网络检查，非完整形式等价 |
| PG 逻辑连接 | 61,334 个显式供电引脚逐项核验 | 不从逻辑同名推断物理连接 |
| 完整 IO 环 | 192 实例与已验证 IO-only 环的 TSV 哈希相同 | 64 IO、64 官方焊盘、60 filler、4 corner |
| 焊盘引线 | 64 条、M2–TM2 共 384 个实际金属矩形 | 保留 4.2 µm 间隙与 90 µm IO pitch |
| 物理顶层引脚 | 64 个 FIRM TopMetal2 box；每个 70×70 µm | 48 个信号端口各 1 个、4 路供电各 4 个；逐端口、逐 net、逐 box 与实际焊盘一致 |
| 核心 PG 几何 | PDN 实际生成；fresh ODB 上 VDD/VSS 均有 `PSM-0040 All shapes ... connected` | `check_power_grid -floorplanning`，不含放置后标准单元供电、完整混网短路证明、IR/EM 或 LVS |
| SRAM 空间 | 两颗 SRAM 均在核心内，左/右/上至少 20 µm；彼此间隔 396.32 µm | 已生成绕开宏的 rows；不证明后续布线拥塞可闭合 |

实际核心 bbox 为 `(352.32,355.32)–(1621.92,1621.62)` µm，面积 1.60769448 mm²；这是放置区域，不能与标准单元/SRAM 实例面积混用。

[新增纯读审计](../reports/floorplan/full-io-readback-audit-20260905-001.json)核验 105 个唯一文件哈希，除几何计数外还要求全部物理端口集合、port→net/type 绑定正确，以及日志中每路电源明确的连通成功消息。Tcl catch=0 或返回值 `1` 单独不足以通过。负向测试覆盖交换端口名、错误层/状态、漏 pin、重复 bondpad 和缺少正向 PG 消息。

## 时序诊断与失败尝试保持可见

005 脚本确实产生了[布局前时序诊断](../runs/croc-full-io-floorplan-20260905-005/work/openroad/reports/01-01_croc_checks.rpt)。因此原 summary 的 `placement_routing_sta_drc_lvs=not_run` 在当前解释中仅指**新候选布局/布线后的 STA 与 DRC/LVS 未执行**，不能解释为完全没有时序输出：

- 同一 reset endpoint 在 asynchronous / clk_sys 组分别有 −67.43 / −70.35 ns slack。脚本三次打印相同组，不能累计成六个独立违规。
- path-delay 与 JTAG 的所列 endpoint 分别为 +0.99 / +3.86 ns；这些局部 MET 行不代表设计时序通过。
- 四路 PG 端口各有 4 个缺失输入延迟、输出延迟和未约束端点警告；报告生成在其 SIGNAL→POWER/GROUND 分类修正之前。
- 没有完整 hold/min-delay、slew/cap/fanout 计数，没有寄生/RCX/MMMC。未知字段不记 0；应在真实候选上重审约束并在 placement 后重新分析。

001–004 的原 manifest/log 均保留：001 因无显示环境触发 GUI/Qt 失败；002 加入 offscreen 后在供电端口类型比较处失败；003 仅调整快照时机，未解决该问题；004 明确诊断出 VDD `INOUT SIGNAL` 与实际 `INOUT POWER` 的差异。历史 floorplan 的四路 PG 端口本就使用 POWER/GROUND。005 显式恢复正确类型，并在分离后的真实焊盘上补建物理 BPins；没有放松原端口/引脚比较。

## IO-only DRC 规则执行已补齐，结果仍 FAIL

[deep 单线程最大规则](../runs/croc-io-ring-maximal-deep1-20260905-001/manifest.json)实际运行约 352.4 秒、退出 0，报告 272 个预期类别、marker 0；终态为 exited、ExitCode=0、OOMKilled=false，13 次周期资源采样最大约 3.594 GiB。这是采样最大值，不是连续测得的峰值。

[组合审计 v3](../reports/bondpad/io-ring-composite-drc-20260905-003.json)重新验证同一 IO-only GDS、相同 deck/规则开关和 39 项原健康任务，加上该独立最大规则报告：**完整规则清单共 131 个 density marker，其中 8 全局、123 局部窗口；Pad 和其他非密度 marker 为 0，fixture 整体 FAIL。** 包含 recommended、density、antenna、offgrid，未关闭规则。

原 deep 多线程 Signal 11 和 flat replay exit 137 均保持失败；原报告 131 的历史解释仍是不完整执行。只有新的组合结果补齐规则清单。最大规则 Tcl 参数仅改变线程数及输出路径，但运行容器 CPU 配额、任务并发方式和 timeout 也不同，不能声称已孤立证明多线程就是原崩溃根因。

**该 DRC 不属于新的完整功能 floorplan。** 加入核心、PDN、信号路线、填充和实际封环后必须重新运行完整候选的规则检查；IO-only 缺少填充造成的密度计数不能直接继承为完整设计的计数。

## 严格 LVS：父级电极回路已定位，仍未闭合

[实际几何与历史父级复核](../reports/lvs/iopadin-electrode-guard-20260905-001.json)提供了新的根因证据：

- Croc 与官方 DCN 的两 cathode、DCP 的两 anode 在叶单元内确实分离，在实际 IOPadIn 父级通过 M1→Via1→M2→Via1→M1 接到同一 `pad` 分量。不能仅凭叶分裂就新增虚拟连接。
- DCN guard 确有 M1→288 个 contact→普通 ntap→nwell 路径；`ntap1` marker/tie 为 0。已排除“没有普通物理 tap/contact”的假设。
- 复用同输入/同工具的历史 strict-deep IOPadIn 运行，无重复 LVS。实际整体 FAIL；DCN/DCP/SecondaryProtection 为 3 个 NoMatch，IOPadIn/LevelDown 为 2 个 Skipped。不能称为父级已完成比较或匹配。
- 当前比较视图中 guard/器件已经变化，实际丢失发生在 reader、extraction、align、simplify 或内部 cleanup 的哪一步尚未定位。显式 purge 显示 SKIPPED，并不排除 simplify 内部的 purge/combine。

下一项是复制 deck 后仅增加阶段快照，追踪 guard、tap 和器件归并；保持 strict ports、deep、tap extraction 等默认验收。IOPadIn guard 的局部金属分量没有直接 PG 标签，父级 `iovss/iovss$1` 仍分裂，应结合真实相邻供电 IO/环结构核验，不能加入同名虚接。没有启动 full-chip LVS attempt 3。

## 本轮 PPA 与同类对照

详细输入哈希见[本轮 PPA JSON](../reports/ppa/croc-ppa-full-floorplan-20260905-001.json)。面积使用同一 floorplan 阶段和同一 Liberty/LEF master 类型；保持 15 pF IO 负载与原 100 MHz 时钟约束。

| 指标 | 原 floorplan | 新 full floorplan | 判断 |
|---|---:|---:|---|
| CORE 标准单元面积 | 0.4945165344 mm² | 0.4945165344 mm² | 原功能逻辑未优化 |
| BLOCK/SRAM 面积 | 0.1594397952 mm² | 0.1594397952 mm² | 两颗 SRAM 保留 |
| CORE+BLOCK 实例面积 | 0.6539563296 mm² | 0.6539563296 mm² | 不是旧 CTS/routed active 面积 |
| PAD_SPACER 面积 | 0.227520 mm² | 0.237600 mm² | 增加 0.010080 mm²，其他 pad/cover 类面积不变 |
| 电气边界 | 3.671056 mm² | 3.896676 mm² | 为合法 IO 几何留出空间 |
| 含封环边界 | 历史已生成 GDS 4.000000 mm² | 规划 4.235364 mm² | +5.8841%；新完整设计 sealed GDS 尚未生成 |
| 新功耗 / Fmax | — | null / null | 100 MHz 是约束；尚无新候选可比功耗或性能结果 |

[ETH MLEM/Croc](https://github.com/pulp-platform/croc) 是最近的真实流片参照：IHP 130 nm、24 KiB SRAM、4.995225 mm²、typical 80 MHz/1.2 V，并有硅后验证。本地为 4 KiB 学习基线，边界/容量/验证状态不同；没有可比测量功耗，不计算优胜比例。[固定来源](../reports/ppa/comparison_sources_20260905.json)保持不变。历史 routed TT 43.6 mW 和独立 CTS ECO TT 56.4 mW 均为默认活动工具估算，不能转填为本候选功耗。

## 下一阶段及复核入口

1. 在独立 run 中加载已核验 005 checkpoint，先复核供电类型后的约束，再执行有界 placement。检验宏/标准单元合法性、端口与网络保留、放置后 PG 和电气违规。
2. 在同一候选上处理 reset/IO/SRAM 电气问题及 CTS 策略；原 15 pF 负载不变。旧 ECO 结果不自动继承，结构、NDR、PPA 必须重新验证。
3. 完成信号布线、实际 GDS/封环/填充后重新做 RCX/STA 与严格 DRC；同时按受支持层次诊断推进 LVS。MMMC、真实活动、IR/EM、DFT 和实际 MPW 规范仍是流片门槛。

```bash
PYTHONDONTWRITEBYTECODE=1 make test validate-contracts
python3 scripts/audit_full_io_floorplan.py \
  --source-run croc-full-io-floorplan-20260905-005 \
  --readback-run croc-full-io-floorplan-readback-20260905-001 \
  --output reports/floorplan/full-io-readback-audit-NEW-ID.json
```

EDA 和审计输出均要求独立新 ID。Git 归档精确的小型原始证据和哈希；完整 hash replay 需要本地保留的 DEF/ODB/ZIP/GDS/PDK，大文件未随仓库发布。轻量测试通过不能证明芯片签核。

现有[AI skill 筛选](04_ai_chip_skills_zh.md)和项目规范足以继续这些工程步骤。真正需要用户提供的是目标产品指标、封装/负载依据以及最终工艺/MPW 验收输入；通用 skill 不替代它们。

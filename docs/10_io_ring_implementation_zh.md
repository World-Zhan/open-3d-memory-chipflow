# 完整 IO 环实现、DRC 执行与严格 LVS 复核

SPDX-License-Identifier: Apache-2.0

后续进展见[完整功能 floorplan 与 DRC v3](11_full_floorplan_readback_zh.md)。下文保留本轮 IO-only 实验当时的结果；新的独立 deep replay 已补齐规则清单，仍有 131 个 density marker、整体 FAIL。

2026-09-05。**已从单个 IO 试件推进到真实的完整 IO 环和封环 GDS，仍未达到可流片状态。** 本候选包含全部 64 个原 Croc IO 及其实际信号名，省略核心逻辑、核心路线和密度填充。不能把它的 DRC、面积或连通性直接推广到整芯片。

## 实际实现与验收范围

| 项目 | 实际结果 | 范围 |
|---|---|---|
| OpenROAD IO 环 | 64 IO + 64 官方 bondpad + 60 filler + 4 corner，共 192 实例 | 电气边界 1974×1974 µm；每边 16 IO，pitch 90 µm，1 µm site 对齐 |
| IO/焊盘间隙 | 4.2 µm；64 条引线，每条 M2–TM2 六层，共 384 个 SWire 金属矩形 | 每焊盘每层 294 µm²，不能把金属层面积相加作为芯片面积 |
| 实际版图核验 | 192 个 placement 与 GDS 变换一致；384 个矩形 XOR=0 | pad→lead→IO 外端口六层均几何连通；无引线侵入邻 IO 金属 |
| 实际连接 | 160 个原信号端子保留、512 个 PG 端子、64 个 bondpad 显式连接 | DEF/OpenDB 逻辑连接；不等于完整提取 LVS |
| 完整封环 | 实际 bbox 2058×2058 µm，IO 环平移 (42,42) µm | 源 PDK 和原芯片 GDS 未改 |

`sg13g2_Filler2000` 的实际 LEF 宽度是 **10 µm**。第一版几何检查器误按名称推断为 20 µm；最终检查器读取真实 LEF。物理候选未因此改动。保留原检查器以解释历史尝试，使用 `check_io_ring_geometry_lef.py` 作为最终几何审计。

第一次物理连接运行 `croc-io-ring-physical-20260905-001` 因 `Unconnected bondpad IO_BOND_pad_clk_i` 停止。独立 `002` 显式把 bondpad 接到对应 IO 的 pad/vdd/vss/iovdd/iovss 端口，再创建 OpenDB SWire；未使用 implicit nets。

## DRC 的真实终态

原合并报告有 131 个密度 marker（8 全局、123 局部窗口），Pad/其他非密度为 0，但最大规则在报告 0 后 Signal 11 崩溃。相同输入/deck 的 flat/单线程重跑实际 exit 137，规则执行仍不完整；不能将该原合并计数当成完整 DRC 结果或 PASS。

原 40 项任务均有完成文本，antenna 的 31 类也存在，但完成文本不替代进程正常终止。独立组合审计逐一核验原 39 项日志、失败任务集合、输入/deck/工具哈希、重跑真实退出及报告。重跑只改变 deep→flat、线程 4→1 和输出路径，规则开关不变。原 manifest、原 audit、原日志均保持原样。

密度试件没有核心与实际填充，131 不能与历史整芯片 1585 合并 marker 或 652 maximal raw 直接比较。密度、推荐规则、antenna、offgrid 均未关闭；不存在 wafer/MPW 接收证明。

## 电源环几何与严格 LVS

同层 PG 核验覆盖 128 个 IO/filler/corner 宏、512 个 PG pin、4484 个 LEF 矩形和 2328 个 pin-layer 区域。四路供电各自在 M3/M4/M5/TM1 形成覆盖全部 128 宏的连续同层金属；144 个可比较的角邻接层接触均接通，未观察到同层跨供电共用分量。M2/TM2 的多个同层分量，已通过下一项真实过孔检查追踪。

**跨层 PG 金属/过孔连通性 PASS。** 独立 `croc-io-ring-pg-vias-20260905-001` 仅从实际 PG pin 和 16 个供电焊盘区域出发，沿实际过孔建立 4095 个金属分量、6016 条连接的图。四路供电各恰好一个独立分量，分别覆盖全部 128 宏及各自 4 个供电焊盘；全部 2328+96 个 pin-layer 区域接通，混网 0。标签同名不创建连接，过孔必须对同一个切孔的两端金属都有正面积重叠；MIM TopVia1 排除按公开推导。固定 2 CPU/4 GB、内部 180 秒上限，实际 95.48 秒、exit 0，六个几何反例通过。

该 PASS 不包含 well/substrate/contact/器件网络、核心 PDN、bondwire/package、IR/EM 或 LVS。连通的供电金属仍须检查电阻、压降、电流密度和完整电路对应关系。

IHP main 已到 `5e6d592`，但官方 IO GDS/CDL 的 Git blob 在 pinned/main/dev 完全相同。本轮在复制的 deck 上应用受支持 [PR #1105](https://github.com/IHP-GmbH/IHP-Open-PDK/pull/1105) 的 purge 修复；两叶单元 × control/candidate 共四次真实 LVS 均 FAIL/NoMatch，提取网表及 cross-reference 字节/摘要一致。源 PDK 未改。

DCN 的 `guard` 仍缺失、`cathode$1` 仍分裂；DCP 的 `anode$1` 仍分裂。Croc 与官方 DCN/DCP 几何和标签相同，父 IOPadIn 的 13 层差异位于 LevelDown 区域，不能据此归因叶单元问题。下一项有界实验是实际父级 M1→Via1→M2+ 的电极回路和 DCN guard 的 nwell/ntap/contact 推导；没有支持证据前不启动 full-chip LVS attempt 3。

## 本轮 PPA 与同类对照

| 指标 | 原基线 | IO 环候选 | 解释 |
|---|---:|---:|---|
| 电气边界 | 3.671056 mm² | 3.896676 mm² | 候选没有核心逻辑，属于布局空间需求 |
| 含封环边界 | 4.000000 mm² | 4.235364 mm² | 增加 0.235364 mm²，**5.8841%** |
| IO + cover 实例面积 | 1.462720 mm² | 1.472800 mm² | 增加 0.010080 mm²；不等于核心 active 面积 |
| 新整芯片功耗 / Fmax / active | — | null / null / null | 尚无新完整布局、RCX 或真实活动分析 |

同类 [ETH MLEM/Croc](https://github.com/pulp-platform/croc) 使用 IHP 130 nm，官方实例 24 KiB、4.995225 mm²、typical 80 MHz/1.2 V，并有实际流片/硅后验证。本地原系统 4 KiB、100 MHz 是约束，最新 IO 环不含核心，不能计算面积或性能优胜比例。原 routed TT 43.6 mW 与独立 CTS ECO 56.4 mW 都是无 workload 活动的工具估算，并非本候选功耗。来源及逐轮输入哈希见 [PPA JSON](../reports/ppa/croc-ppa-io-ring-20260905-001.json)。

## 复核入口与下一轮

- [几何审计](../runs/croc-io-ring-physical-20260905-002/geometry_audit.json)、[placement/net/PPA 审计](../runs/croc-io-ring-physical-20260905-002/plan_audit.json)。
- [原 DRC 审计](../runs/croc-io-ring-drc-20260905-001/audit.json)、[独立组合审计](../reports/bondpad/io-ring-composite-drc-20260905-002.json)、[最大规则重跑](../runs/croc-io-ring-maximal-flat-20260905-001/manifest.json)。
- [同层 PG 摘要](../reports/bondpad/io-ring-pg-20260905-001.json)、[跨层 PG 摘要](../reports/bondpad/io-ring-pg-vias-20260905-001.json)、[严格 LVS A/B 与上游证据](../reports/lvs/strict-leaf-next-step-20260905-001.json)。
- 新增连接/间距与 DRC 审计测试；`PYTHONDONTWRITEBYTECODE=1 make test validate-contracts` 验证轻量审计器和 JSON 合同。轻量测试无需 GDS/ODB 或 Docker；所需小型 DEF/TSV/manifest 一并归档。PG 的六个几何反例在固定 KLayout 容器单独验证。

实际 EDA 脚本为 `run_io_ring_floorplan.py`、`run_io_ring_physical_connected.py`、`run_io_ring_drc.py`、`replay_io_ring_maximal.py`。脚本含固定工具、资源/时间上限与独立 run ID 要求；重现应使用新 ID，保留旧证据。审计可读本地大文件，Git 中以哈希和摘要归档，不宣称 fresh checkout 已包含全部原始版图。

下一轮优先解决最大规则的实际执行失败，并在独立完整设计上验证核心空间、显式核心 PG、密度填充与实际布线，再重做 RCX/STA/严格 DRC。15 pF IO 负载保持，输出 slew/电容违规和 CTS 功耗代价继续处理；LVS 按叶/父级根因门槛推进。完整 MMMC、真实活动、IR/EM、DFT 与实际 MPW 规范仍未完成。

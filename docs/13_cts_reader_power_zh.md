# CTS 扇出闭环、tap reader 修复与功耗根因

SPDX-License-Identifier: Apache-2.0

更新：2026-09-10。**新 CTS 候选的 fanout 从 4 清为 0，setup/hold 仍为 0；slew/cap 仍为 71/135，严格 LVS 仍 FAIL，尚不可流片。** 本轮还修复了 tap 的读取缺失，并用单因素实验证实此前低功耗是分析抽象造成的失真。原 15 pF 负载和严格规则保持。

## 实际改动及验收

在 `croc-full-io-cts-fanout-20260910-001`，对四条实际 fanout=16、limit=8 的时钟支路分别增加两颗 `sg13g2_buf_8`，每颗驱动八个原负载，共八颗。39.51 秒正常结束，真实容器 exit 0、无 OOM。

[独立审计](../reports/placement/full-io-cts-fanout-audit-20260910-001.json)验证新增 buffer 折叠后所有原连接和 master 保留；source/before 完整实例、ITerm、端口、几何一致，52 个端口、64 个物理 pin box、192 个 IO、两颗 SRAM 保持。43 条原 15 pF load 命令及其余 SDC 命令未改。普通 `check_placement`、VDD/VSS PG 检查通过，不等于全 IO 供电、IR/EM 或 LVS。

970 条 CLOCK net 中 22 条带 NDR，共五个定义；八条新支路继承 CTS_NDR_1。原 200 条内部、743 条末级无 NDR 分支保持，布线 NDR policy 资格仍 UNVERIFIED；本轮没有 route，不能声称时钟波形或提取后 MMMC 通过。

## 每轮 PPA 与同类对照

| 同 CTS 阶段 | 改前 9 月 9 日 | 改后 9 月 10 日 |
|---|---:|---:|
| CORE+BLOCK active 面积 mm² | 0.7216007904 | 0.7217894880 |
| setup / hold / fanout 违规 | 0 / 0 / 4 | 0 / 0 / 0 |
| slew / capacitance 违规 | 71 / 135 | 71 / 135 |
| WNS / TNS ns | 0 / 0 | 0 / 0 |
| TT 原始默认活动功耗 mW | 5.46（异常） | 5.46（异常） |

active 面积增加 188.6976 µm²，约 0.02615%。电气边界仍为 3.896676 mm²；含封环规划 4.235364 mm²，新完整 sealed GDS 尚无结果。100 MHz 是约束，Fmax、workload 功耗保持未知。见[机读 PPA](../reports/ppa/croc-ppa-cts-reader-power-20260910-001.json)。

行业参照继续采用[固定来源索引](../reports/ppa/comparison_sources_20260905.json)：ETH MLEM/Croc 为 IHP130、24 KiB SRAM、4.995225 mm²、作者典型 80 MHz/1.2 V，并有上游流片/硅验证材料。本地为 4 KiB、新候选未签核，没有可比实测功耗或性能，不能从面积/约束推断优于同类芯片。

## 功耗失真的单因素证据

[功耗方向 A/B](../reports/ppa/croc-power-direction-ab-20260910-001.json)包含四个真实独立 OpenROAD 进程，均正常结束、无 OOM。先以实际 IHP IO+DFF 小电路对照，再读回完整 placement 的同一 DEF/SDC，唯一输入差异为无 Liberty 的 bondpad master 引脚方向 INOUT→INPUT。两臂输出 DEF/Verilog 字节一致。

| 完整 placement 分析视图 | INOUT | INPUT |
|---|---:|---:|
| TT 总功耗 mW | 5.45198005 | 37.47740760 |
| SRAM internal mW | 0 | 8.46329983 |
| Sequential internal mW | 0.426756538 | 22.048519900 |

这已证实固定工具对该方向的功耗计算敏感，重现并去除了 SRAM 零动态/FF 异常低功耗；不等于直接观测了每个 pin 的 activity density。INOUT 的 DEF 读回也复现旧 ODB 约 5.45 mW，支持大幅差异由方向改变引起。

同时，32 个 GPIO pad slew 从 2.23 增至 2.72 ns（原限制 1.20 ns）。因此 INPUT 仍是独立分析视图，没有替换当前物理候选，不能将 37.477 mW 写作新 CTS 的功耗或真实 workload 功耗。下一步需要审查无库物理焊盘的 STA 抽象方法，并验证输入/输出/双向模式和时钟。

## tap reader 的实质修复及剩余 LVS

[reader/LVS A/B](../reports/lvs/tap-reader-ab-20260910-001.json)在独立复制 deck 上仅为 PTAP1/NTAP1 增加精确 X 元件 adapter，复用原 CustomTap 的 TIE/WELL 次序与面积/周长单位转换。真实 KLayout reader 回归覆盖 20 个用例、40 个语义断言，其中 12 个拒绝负例；普通 R、原 R tap 和未知子电路保留。

后续只做一组 DCN strict-deep 单叶 control/candidate A/B，每臂 31 个库存快照。候选中的 PTAP1 器件、ANODE 端口现能穿过 align/simplify 保留，layout 所有阶段库存不变。**两臂严格 LVS 均 FAIL，device Match=0，未配对器件 4→5**；这是恢复了原先被吞掉的器件，不是 LVS 违规减少。

当前 tap 的 layout A/P 为 141.2964 µm²/221.76 µm，schematic 为 141.253 µm²/47.54 µm，参数比较仍未合格。layout guard 仍在 RF purge 被删除，schematic guard 仍在 simplify 删除，重复 cathode 仍需要真实父级闭合。没有关闭严格端口、放宽容差或添加虚接。

交叉审查还识别出 adapter 的通用化边界：当前固定输入无异常，但乘积及单位换算后的数值尚未复查溢出/下溢。推广到任意 CDL 前须补最终有限正值检查和边界负例；本轮通过范围仅限已归档用例。

叶级输入来自固定官方 PDK `331c00484213b13414777eec1336ef5c29b969bd` 的历史独立导出。此前证据证明这个 DCN 叶的几何/标签与 actual Croc 对应叶相同；不能推广为整个 IO 库等同。本轮没有 parent/full-chip LVS，也没有改源 PDK。

## IO 负载不匹配与可推进的官方套件

[实际违规分类](../reports/ppa/croc-io-load-contract-20260910-001.json)将 135 个 cap 分为 32 个外部 GPIO 驱动、39 个芯片 IO 和 64 个 SRAM 输出；71 个 slew 分为 32 个外部 GPIO 驱动和 39 个芯片 IO。当前 SRAM 库已经是正确的 0.064 pF，不属于历史 farads/pF 单位错误。

当前 Croc 旧数字 IO 库的 TT 最大 cap 约 1.076–4.863 pF，FF 最大也仅 10.0761 pF，均不足以满足 15 pF 模型限制。把旧 IO 换成库内更大驱动版本不足以解决它。这里是模型验收边界，不是声称物理硅不能驱动 15 pF。

官方 [IHP #676](https://github.com/IHP-GmbH/IHP-Open-PDK/issues/676)维护者指出 [PR #1033](https://github.com/IHP-GmbH/IHP-Open-PDK/pull/1033)已更新负载模型。核查确认本地固定 PDK 已包含该 merge；[成套候选清单](../reports/ppa/ihp-io-suite-candidate-20260910-001.json)绑定 GDS/CDL/LEF/Verilog 及 TT/FF Liberty。新 Out16mA/ InOut30mA 的 TT cap 限值分别为 20/40 pF，具有保留 15 pF 的模型空间。

PR 同时改变输入接收电路、版图与多种视图，因此不能只将新 Liberty 套到旧 IO 版图。下一步是独立一致视图 fixture：核对接口/方向/PG/几何、RTL/电路行为、严格 DRC/LVS、15 pF STA，通过后才迁移完整 IO 环。两个已读角的 cap 兼容不等于完整角/模式、slew 或签核资格。官方原始记录见[来源缓存](../reports/ppa/ihp-io-update-source-20260910-001.json)。

15 pF 仍保持为参考约束；实际板级要求尚未确认。本轮推进不依赖降低此数值，也不需要先增加通用 skill。真实投片前仍须确认封装/板卡、MPW/工艺验收、完整 corners/modes、IR/EM、DFT 等输入。

## 下一轮门槛

1. 对官方 IO 更新进行成套视图 fixture 验证，不混用新时序与旧版图。
2. 单独处理 64 个 SRAM 输出 cap 的缓冲/放置，同时保持功能、供电与时序。
3. 继续 tap 周长/guard 物理模型定位；reader 通过不足以晋级 full-chip LVS attempt 3。
4. 审核物理焊盘 STA 抽象并建立可信活动，再给合格功耗；不沿用 5.46 mW 的假象。

新完整 route/fill/seal、提取后 STA、DRC/LVS 均尚未完成。旧 IO-only 131 个 density marker 与历史全芯片 DRC 继续单列，不能用于通过新候选。验证命令仍为 `PYTHONDONTWRITEBYTECODE=1 make test validate-contracts`；测试通过不授予芯片签核。

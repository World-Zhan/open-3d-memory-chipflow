# DCN 严格 LVS：guard 与 tap 丢失阶段定位

SPDX-License-Identifier: Apache-2.0

本轮只增加观测，没有修改版图、CDL、器件模型、提取连接或清理规则。单颗官方 `sg13g2_DCNDiode` 的真实 strict-deep LVS 在 3.54 秒内结束，最终仍 **FAIL**。31 个阶段快照完整枚举 circuit、net、pin、device 和 subcircuit；每次写出前后库存均相同。独立读取新旧 LVSDB 后，cross-reference 和最终两侧文本表示与历史 control 完全相同。

## 已确认的变化顺序

| 阶段 | Layout 提取侧 | Schematic 参考侧 |
|---|---|---|
| Reader / 原始 extraction | 5 个 net，其中 `guard` 存在但没有 device terminal、pin、subcircuit pin；另有 2 个彼此分离的 `cathode` net、`anode` 和内部 substrate net。器件为 2 个 dantenna、1 个 ptap1 | 两个 DANTENNA、ANODE/CATHODE/GUARD 端口；`XR0 ... ptap1 A=... P=...` 成为参数化空子电路 PTAP1，连接 ANODE 与 SUB! |
| RF model mapping | 上述库存不变 | 不执行这一步 |
| RF mapping 内 `purge_devices` | `guard` 仍存在，库存不变 | 不执行这一步 |
| RF mapping 内 `purge` | **删除孤立 `guard` net**，其余 4 个 net、3 个器件保留 | 不执行这一步 |
| `align` | 不改变这一叶的库存 | **空 PTAP1 子电路及实例消失**，剩两个 DANTENNA；ANODE/GUARD 此时仍有顶层端口 |
| 完整 `simplify` | 创建 3 个顶层端口：anode、cathode、cathode；两 cathode 仍未短接 | **孤立 ANODE/GUARD 端口与 net 消失，两个并联 DANTENNA 合为一个** |
| 后续显式 make_top_level_pins/combine_devices/purge/purge_nets | 所有项实际 SKIPPED，前后库存相同 | 所有项实际 SKIPPED，前后库存相同 |
| Strict comparison | 3 layout-only devices、4 layout-only nets | 1 schematic-only device、2 schematic-only nets；1 个 circuit pair 为 NoMatch |

这排除了“guard 根本没有提取”以及“日志中显式 purge=SKIPPED 就没有任何 purge”的解释。`Netlist#to_s` 和普通 SPICE 写出会遗漏孤立 net，所以不能只看文字网表判断提取阶段的 guard 是否存在；本次完整库存明确记录了它。

## Reader 缺口的确定源码

固定源 `rule_decks/custom_reader.lvs` 的 `element` 仅对 `CUSTOM_READER` 列表内的元素执行 `process_device`；固定 `globals.lvs:78` 定义该列表为 `M C R Q L D`，没有 `X`。整份 CustomReader 没有 `wants_subcircuit` 回调。CDL 的 `XR0` 因而走标准子电路解析，实际快照中形成 `PTAP1(A=0.141253N,P=47.54U)` 空电路，没有变成 CustomTap。

源码已经有 R 类型 tap 的器件构造、`TIE/WELL` 端子顺序和 A/P 单位转换：`custom_reader.lvs:418` 的 `create_resistor`、`:462` 的端子函数、`:643` 的参数函数，以及 `custom_devices.lvs:179` 的 CustomTap。`globals.lvs` 中 `PREFIX_MAP` 的 `ptap1 => R` 仅供 writer 使用；它不会自动把输入的 X 行转成 R 器件。

[KLayout 官方 reader 示例](https://www.klayout.de/doc/code/class_NetlistSpiceReader.html)明确演示 `wants_subcircuit` 选择模型、随后在 `element` 的 X 分支构造实际器件；[回调说明](https://www.klayout.de/doc/code/class_NetlistSpiceReaderDelegate.html#m_wants_subcircuit)规定模型名是大写。已保存本次读取的 HTML 哈希与示例文本；当前固定 0.30.5 二进制也存在该 API。下一项有界修复可先在独立 reader-only fixture 中，仅接受 `PTAP1/NTAP1` 的 X 元素，复用已有 R/tap 分支，验证端子、A/P 和未知子电路保持原行为，再决定 strict 单叶运行。**本轮没有实施该修复，也没有关闭 purge 或跳过 simplify。**

## 为什么物理 guard 有接触，网表却没有器件端子

上一轮真实几何已验证 guard 的 M1 → 288 contacts → 普通 ntap → nwell 路径；这与本次提取出命名 `guard` net 一致。普通 ntap 是连通层，不等同于专门的 `ntap1` 器件：固定规则依据 well 标签产生 `ntap1_mk`，而这个 guard 的 marker/tie 数为 0。`tap_extraction.lvs` 只从专门标记的 `ntap1_tie/ntap1_well` 提取 CustomTap；dantenna 则是 P/N 两端器件。原始库存因此在 guard 上没有可比较的器件端子，没有证据表明它因缺少 M1/contact/普通 ntap 而断开。

不能通过给 guard 增添虚构端子、增加 implicit net 或把它短接到猜测的 PG 来让 LVS 变绿。此叶的两个 cathode 本来需要真实父级 M2/Via1 连接；父级连通几何和这次叶级清理原因是不同问题。

## 剩余门槛和验证边界

修复 reader 后，tap 的 A/P 是否与真实版图相符仍需核查：实际提取 ptap1 为 A=141.2964 µm²、P=221.76 µm，原 CDL 为 A=141.253 µm²、P=47.54 µm。当前器件未配对，不能提前断言参数比较能通过，也不能按提取值改写黄金参考。重复 cathode、父级 `iovss/iovss$1`、层次与 guard 的真实上下文仍须分别处理。只移除 RF purge 的历史上游修复 A/B 已经失败，不能当作全部根因的解决方案。

本轮没有 full-chip 或新的 parent LVS，没有 DRC/物理几何/PPA 改动。该诊断本身不产生新芯片面积、功耗或 Fmax；同轮物理实现的 PPA 由主任务的独立 checkpoint 报告给出。

## 复核证据

- [LVS 执行清单](../../runs/croc-lvs-dcn-stage-snapshots-20260909-001/manifest.json)：固定 GDS/CDL、deck、镜像和脚本，2 CPU / 4 GB，内部 60 秒、外部 85 秒；实际退出 0、无 OOM，但日志结果 FAIL。
- [原始提取完整库存](../../runs/croc-lvs-dcn-stage-snapshots-20260909-001/snapshots/layout_netlist_raw_before_rf_mapping.inventory.json)、[RF purge 后](../../runs/croc-lvs-dcn-stage-snapshots-20260909-001/snapshots/layout_netlist_after_rf_purge.inventory.json)、[Reader 后](../../runs/croc-lvs-dcn-stage-snapshots-20260909-001/snapshots/schematic_after_reader.inventory.json)、[simplify 后](../../runs/croc-lvs-dcn-stage-snapshots-20260909-001/snapshots/schematic_netlist_after_simplify.inventory.json)。
- [新旧结果独立比较](../../runs/croc-lvs-dcn-stage-control-check-20260909-001/cross_reference.json)。
- [纯读审计](dcn-stage-snapshots-20260909-001.json)：222 个唯一文件哈希、31 次观测不变、只插入观测语句的 patch、strict FAIL 与历史一致。
- [源码和官方 API 依据](dcn-reader-extraction-review-20260909-001.json)。
- 6 项审计测试全部通过，含快照缺失、库存篡改、前后哈希不同、隐藏 raw guard 等负例；测试通过仅证明诊断的证据合同，不代表设计 LVS 通过。

```bash
cd /home/james_zhan/projects/open-3d-memory-chipflow
PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit_lvs_dcn_stages.py --output /tmp/dcn-stage-review.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_lvs_dcn_stages.py -v
```

审计输出使用 create-only 写入；选择尚不存在的输出文件。原始 run 和固定 PDK 始终保持原样。

# 签核政策与不可绕过门槛

SPDX-License-Identifier: Apache-2.0

## 1. 允许的最高声明

本仓库能自动给出的最高声明是 `public_rule_signoff`，含义严格限定为：固定 Croc、公开 IHP PDK、固定容器和本仓库验收器下，观察到全部公开门槛通过。

它不等于 `foundry_signoff`。IHP Open PDK 仍标记为 preview，实际 MPW/tapeout 需要工艺方确认冻结版本、rule deck、waiver、密度窗口、封装、ESD、padframe、seal ring 和交付格式。

ASAP7/TaiWei 永久是 `research_only`。

## 2. Croc 硬门槛

必须同时满足：

1. RTL 和门级仿真均出现精确 UART 签名；
2. 无 unresolved reference、inferred latch 和非白名单 SRAM blackbox；
3. OpenROAD 进程无 error；
4. `design_is_routed` 为 true；
5. VDD/VSS `check_power_grid` 均成功；
6. WNS/TNS 可解析且非负；
7. setup/hold 报告若存在 violation count，必须为 0；
8. GDS、sealed GDS、metal-filled GDS、active-filled GDS 都非空；
9. 完整 IHP main+density+antenna DRC 的未豁免违规为 0；
10. 顶层 LVS exact match；
11. `disabled_rules` 为空。

任何“未知/没生成/没解析到”都不等于通过。

## 3. 明令禁止的跑绿手段

- 关闭 density、antenna、off-grid、angle、FEOL、BEOL 或 recommended rules；
- 用 precheck deck 代替 main deck；
- 使用 `ignore_top_ports_mismatch`；
- 用 `implicit_nets=*` 把缺失电源端口掩盖掉；
- 只提取 netlist 不做 comparison；
- 把不支持的 SRAM macro 留成 blackbox；
- 删除失败报告后只保留成功阶段；
- 把没有运行的值填成 0；
- 把 route DRC 当作 foundry DRC；
- 把预测性 PDK GDS 描述成可投片。

单元测试会静态检查签核脚本中不存在这些禁用参数；真实运行时 parser 还要求结果数据库和明确 PASS 签名。

## 4. 3D 研究门槛

`pin3d-smoke` 通过需要：上下层实例非零、两层 PDN stage 成功、HBT/cross-tier 非零、mixed-fanout 指标存在、最终 ODB/DEF/SPEF/时序报告存在、route DRC 为 0。

`pin3d-full` 在 smoke 基础上还需要真实 HotSpot 输出和可解析最高温度。若上游 harness 缺失，正确状态是 failed，不是 temperature=null 的 passed。

## 5. 版本与证据

每次运行有独立 run ID。`run_stage.py` 对同一 run ID 的同名 stage 使用创建式日志；重复运行会报错，避免覆盖。manifest 记录命令、锁文件快照、主仓库 commit/dirty 状态、host 信息、退出码和 evidence。
`croc-netlist-sim -> croc-pnr -> croc-gds -> croc-signoff` 的依赖必须在同一 run manifest 中依次为 `passed`；共享上游目录里偶然存在的旧文件不能满足这个门禁。

大型 GDS/ODB/SPEF/波形/完整 run 目录不进 Git。归档目录生成 SHA-256 inventory，Git 只保存脚本、schema、文档、小型汇总和版本锁。

## 6. Foundry 交付仍缺什么

即使 `public_rule_signoff` 通过，真实投片前仍至少需要：

- IHP/MPW 对具体 PDK release 和 deck 的书面确认；
- 官方 waiver 列表与适用条件；
- IO 电压、ESD/latch-up、pad ring、seal ring 审核；
- density/fill 的 foundry 最终工具复跑；
- package/bonding diagram、pinout、power integrity；
- tapeout checklist、命名、坐标、GDS/OASIS checksum；
- 合同、付款和晶圆/封装下单。

这些都不在第一阶段开源工程授权范围内。

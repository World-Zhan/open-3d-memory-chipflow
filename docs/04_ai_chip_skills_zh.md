# 芯片 AI skill 与开源案例筛选

SPDX-License-Identifier: Apache-2.0

核查日期：2026-09-05。结论：现有工具已经能帮助规格、RTL、仿真和开源后端，但成熟度必须按阶段、PDK 和证据判断。对本项目，优先组合 **r2g 的后端闭环方法、digital-chip-design-agents 的领域检查表、wave-mcp 的波形调试**；执行仍由本仓库固定的 Croc/IHP 与 Pin3D 工具链负责。

## 筛选依据

本次读取 GitHub 元数据、固定 SHA 的目录树、README、相关 SKILL、许可证、部分 CI 和实验记录。没有安装第三方运行时，也没有本地重现第三方宣称的 EDA 成果。机读清单记录完整 SHA、来源 URL、缓存内容 SHA-256 和适用性判断：[研究索引](../reports/research/ai-chip-skills-20260905.json)。星数只保留为检索快照，不作为成熟度排序。

需要区分四种材料：skill 是操作规范，MCP 是工具接口，flow framework 是执行框架，案例是某次实验的证据。四者不能互相代替。

## 候选与采用判断

| 固定版本来源 | 类型 | 许可证核查 | 判断 |
|---|---|---|---|
| [hdl-tools/digital-chip-design-agents](https://github.com/hdl-tools/digital-chip-design-agents/tree/d9ec7f93343ecdd7bd7d886ef28563f8c5960308) | stage_skill_reference | MIT | 优先参考：覆盖架构、RTL、验证、STA、后端、memory-IP；适合检查表。已检查 CI 主要验证插件结构与部分 helper，不证明全芯片签核。不能照搬自动多 agent、全局 memory 或泛化时序例外。 |
| [ShenShan123/r2g-skills](https://github.com/ShenShan123/r2g-skills/tree/11b0dad38e6e89e91c5a91de2c286a734124eae3) | backend_skill_adapter_candidate | MIT | 优先做小样适配：有 ORFS/OpenROAD/KLayout/RCX 脚本与负向 A/B 案例；明确 ASAP7 NOT SUPPORTED。缺 deck 时的 skip 必须映射为未执行，不能继承为本仓库 PASS。IHP 支持声明仍需适配 Croc。 |
| [Tencent/wave-mcp](https://github.com/Tencent/wave-mcp/tree/4c9a2550cbc99ec4448cac556948d5ce32d7a214) | waveform_debug_mcp | MIT | 有真实波形后试点：FST/VCD 与 pyslang RTL 查询调试工具；不运行仿真、综合或 APR。大规模项目验证是维护者声明，本次未复现。API 未识别许可证，但已读 LICENSE 确认为 MIT。 |
| [Eriemon/verilog-generator](https://github.com/Eriemon/verilog-generator/tree/007372fb63fe1d0b51e5bb10f4569d0b62ae6730) | rtl_generation_skill_reference | Apache-2.0 | 选择性借鉴：规格/语义模型/RTL/测试证据闭环有用；Verilog-2001 风格、远端 SSH/Vivado 工作流限制不适合直接套 Croc SystemVerilog。 |
| [bjwanneng/veriflow-cc](https://github.com/bjwanneng/veriflow-cc/tree/bf5a98251cd5c0197790a609e5fc0e2d139417bb) | rtl_verification_framework | 未识别 | 观察，暂不复制代码：spec/golden/RTL/verify-fix/lint-synth；无后端签核。未识别到许可证，复制或安装前须确认许可；Claude 编排需改造。 |
| [wuhy68/ChatEDA](https://github.com/wuhy68/ChatEDA/tree/02bb522a98f759595fbfce6bee33f64ef02ce3a5) | research_framework | Apache-2.0 | 方法和 API 参考：论文与 ChatEDA-Bench 支持研究价值；不是已验证可直接运行的通用芯片全流程 skill。 |
| [shailja-thakur/AutoChip](https://github.com/shailja-thakur/AutoChip/tree/3abe0b606d8819dfe548661b0245b55a1ebab40b) | simulation_feedback_research | 未识别 | 反馈循环参考：LLM Verilog + Icarus/testbench 迭代修复，非 APR/签核；未识别到许可证，不直接复制或安装。 |
| [siliconcompiler/siliconcompiler](https://github.com/siliconcompiler/siliconcompiler/tree/51c0ee75059e9f715e30547834a4c0480c5d77a1) | deterministic_build_framework | Apache-2.0 | 成熟执行框架参照：不是 AI skill；工具适配、示例与 CI 更完整，区分 drcs/drvs/signoffflow。所检查固定 SHA 的 Tools CI 失败，不能将当前 main 当成本项目已合格版本。 |
| [kiwih/qtcore-C1](https://github.com/kiwih/qtcore-C1/tree/1608f36d1ad1efd5b1f63922a629169bad680f26) | ai_hardware_case | Apache-2.0 | 案例证据：可读到 GPT-4 会话与 RTL；作者明确由人设计测试台并驱动修复。仓库和 Caravel 配置不证明本次独立复现、实际制造或自主先进 3D 签核。 |

## 哪些证据最有价值

**r2g 的负向实验最贴近当前问题。** [Sky130HD 实验记录](https://github.com/ShenShan123/r2g-skills/blob/11b0dad38e6e89e91c5a91de2c286a734124eae3/docs/experiments/signoff/2026-08-22-sky130hd-recipe-coverage-iteration-v2.md)记载：AGR 的 DRC 从 20 降到 16 仍被拒绝；Blake2s 的 WNS 改善但 LVS 退化仍被拒绝；SHA512 时序改善后仍为负，也被拒绝。单个 SHA-256 clean 结果只作线索，未推广成通用优化配方。作者报告 1241 passed / 1 skipped，这不是本地测试数字。这种“改进不等于闭环”的方法可直接指导我们的 642 DRC 和电气违规处理。

其 [signoff-loop skill](https://github.com/ShenShan123/r2g-skills/blob/11b0dad38e6e89e91c5a91de2c286a734124eae3/r2g-skills/signoff-loop/SKILL.md)明确拒绝 ASAP7 signoff（exit 65）；不能借它把 Pin3D 的预测性 PDK变为签核平台。迁移前需审计 missing-deck skip、平台名、网表/SDC/RCX 输入和产物对应关系。

**digital-chip-design-agents 更像领域知识包。** 本次重点读 STA、PD、memory-IP skill。仓库有 17 个 SKILL 文件和 16 个插件，但检查到的 CI 主要是结构验证及部分 helper 测试；没有据此确认完整芯片 EDA 签核回归。STA 的 multicycle/hold 示例、不同工具命令需要对照本地固定版本。不要把其自动多 agent 和全局记忆习惯作为本项目默认规则。

**wave-mcp 可缩短验证定位时间。** 其 34 个工具面向波形与 RTL 结构查询，维护者声明在 OpenTitan、Xiangshan 等项目验证。本次没有独立复现这些规模声明。首次试点应输入本项目自己生成的一组 PASS/FAIL FST 或 VCD，检查能否定位已知握手/复位错误，保留原始波形与仿真器判定。工具能解释波形，不负责证明测试覆盖充分。

**QTCore-C1 是有材料可读的 AI 芯片案例。** [固定版本](https://github.com/kiwih/qtcore-C1/tree/1608f36d1ad1efd5b1f63922a629169bad680f26)公开 GPT-4 对话、8 位架构和 Verilog。作者明确写明：测试台由人编写，人主导反馈修复；顶层 wrapper 也不是 GPT-4 生成。它支持“人制定架构/验收、AI 协助 RTL”的做法，不能推出“AI 已自主完成先进 3D 芯片全签核”。相关 [Chip-Chat 论文](https://arxiv.org/abs/2305.13243)研究的是 QTCore-A1，不能将 A1 与 C1 的实验结论混写。

**SiliconCompiler 是执行框架参照。** 它区分布线 DRC (`drcs`)、电气约束 (`drvs`) 和单独 signoff flow，这正是此次 Croc 验收补漏需要的区分。不过所查固定 SHA 的 [Tools CI](https://github.com/siliconcompiler/siliconcompiler/actions/runs/33938267222)失败；其他 lint/Python job 成功不能覆盖工具回归失败。以后若选用，应锁定并验证 release，不替换当前环境来碰碰运气。

## 本仓库的落地方式

1. 本次新增原创项目 skill：[chipflow-evidence](../.agents/skills/chipflow-evidence/SKILL.md)，只引用适用的方法和本地证据，不复制上游指令包。
2. 后端先修验收：slew/cap/fanout 与 setup/hold 都须明确为 0；缺失字段不能 PASS。读档审计无需重新跑芯片。
3. 前端按[最小存储扩展规格](05_memory_spec_zh.md)先做 OBI 控制模块与独立测试；出现真实波形后再评估 wave-mcp。
4. 将来试点 r2g 时，用独立小模块、固定 IHP/工具版本和独立 A/B run ID，比较功能、DRC、LVS、STA、电气约束、RCX 和运行成本。原有 Croc/Pin3D 证据不得被覆盖。

暂时不需要用户额外提供大篇 skill。可以独立补通用工程规范、实现和验证；目标容量/带宽/功耗、真实工艺/键合参数和投片验收边界则属于产品及工艺输入，不能由 AI 生成后冒充已确认事实。

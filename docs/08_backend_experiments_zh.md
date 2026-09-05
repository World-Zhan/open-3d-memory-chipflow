# 2026-09-05 后端实验复现与验收

SPDX-License-Identifier: Apache-2.0

本轮没有替换原 Croc 版图。所有实验固定容器 `sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521`（实测 OpenROAD `v2.0-27244-gfecb04286`），只读挂载源仓库和输入，独立目录输出，限制 6 CPU / 8 GiB。原始日志、ODB/DEF/SPEF 留在本地；Git 保存小型 manifest、校验和 PPA 报告。

## 输入、执行顺序与结果

| 实验 | 可审查的命令与输入 | 结果范围 |
|---|---|---|
| RCX | [manifest](../runs/croc-postroute-rcx-20260905-001/manifest.json) 的 command/source_sha256；[Tcl](../scripts/croc_postroute_probe.tcl) | 从原 routed ODB 提取 typ SPEF，TT/FF 读回；不输出修改后的 ODB/DEF |
| CTS A/B | [manifest](../runs/croc-cts-fanout-ab-20260905-001/manifest.json) 的 arms[].command；[Tcl](../scripts/croc_cts_fanout_ab.tcl) | 同 placement ZIP，唯一 CTS 参数 default→8；placement-estimated PPA |
| ECO 001 | [manifest](../runs/croc-cts-branch-eco-20260905-001/manifest.json)；[Tcl](../scripts/croc_cts_branch_eco.tcl) | 工具没有 insert_buffer，失败；不作为后续输入 |
| ECO 002 | [manifest](../runs/croc-cts-branch-eco-20260905-002/manifest.json)；[Tcl](../scripts/croc_cts_branch_odb_eco.tcl) | fanout=0，但八条新网缺 NDR，已被 003 替代 |
| ECO 003 | [manifest](../runs/croc-cts-branch-eco-20260905-003/manifest.json)；[构造 Tcl](../scripts/croc_cts_branch_odb_ndr_eco.tcl)、[新进程验证 Tcl](../scripts/croc_cts_eco_check.tcl) | fanout=0，结构/电源/NDR 检查通过，仍无 route/signoff |

重跑必须使用新 run ID。先核对 manifest 的源文件 SHA-256；在 command 数组中更新本机仓库根路径、`--name` 和 `/output:rw` 的主机目录，保留输入路径、`:ro`、镜像、SDC、库和限制。CTS A/B 先从清单指定 ZIP 中仅取 `02_croc.placed.odb`、`02_croc.placed.sdc` 放入新的 `inputs/`，用同一 inputs 顺序运行两臂；ECO 003 的 `/input:ro` 必须仍指向有对应 source hash 的 CTS candidate。不得原样重跑写入既有历史输出目录。命令中的宿主 UID/GID 可按本机身份调整，这不改变设计输入。

运行前在新目录记录命令、输入和 Tcl 哈希；运行后记录结束状态、退出码、全部输出哈希及源哈希复核。命令 exit 0 只表示执行完成，电气/DRC/LVS 必须单独判定。不要从本机另一份 OpenROAD 源码推断本镜像 API。

## 结构校验

在 WSL 仓库根目录，以新输出名执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_croc_clock_eco.py \
  --before runs/croc-cts-fanout-ab-20260905-001/candidate/cts.def \
  --after runs/croc-cts-branch-eco-20260905-003/cts.def \
  --output runs/croc-cts-branch-eco-20260905-003/structural_recheck_NEW.json
```

校验器针对本轮八个 `sg13g2_buf_8`，要求原实例 master、die/units 不变；新分支各驱动八个原负载；VDD/VSS 显式连接；新增 CLOCK 网继承父网 NDR，原规则定义不变；折叠八个 buffer 后全体原网络连接一致。解析不完整、未知实例或重复记录均拒绝。它不证明完整形式等价、时钟波形或物理签核。

历史 002 的结构结果只检查连接，尚无 NDR 字段；不能用新版校验器倒签为通过。003 的结果明确包含 NDR。每轮 PPA 及行业比较见[本轮报告](../reports/ppa/20260905_review_zh.md)；当前全芯片 strict DRC/LVS 仍 FAIL。

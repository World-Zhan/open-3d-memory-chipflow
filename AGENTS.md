# Repository guidance

This repository is the WSL open-3d-memory-chipflow project; it is separate from the Windows AI_chip / NUMA simulator repository.

Read [CURRENT_STATUS.md](CURRENT_STATUS.md) for the latest evidence and next gates. For chip-flow auditing or implementation, use the project skill at [.agents/skills/chipflow-evidence/SKILL.md](.agents/skills/chipflow-evidence/SKILL.md). Keep pinned upstream sources and immutable run evidence intact; use additive patches and independent run IDs.

Module-level C1 work may advance from [the minimum specification](docs/05_memory_spec_zh.md) while baseline physical signoff remains blocked. Do not reinterpret a historical stage PASS, helper test result, source patch, or capacity estimate as present chip signoff.

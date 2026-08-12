# OpenDracoCLI

AI 时代的智能终端 — P1 跨平台 Shell 内核。

兼容 cmd / Linux 双语法自动映射，纯 subprocess 调原生 shell 执行，rich + prompt_toolkit TUI，SQLite 历史持久化。预留 PreExec/PostExec 钩子与事件总线供后续 P2/P3/P4 阶段接入。

## 安装

```bash
pip install -e .
```

## 运行

```bash
opendracocli
```

## 阶段说明

- **P1（当前）**：跨平台 Shell 内核 — 双语法映射 + 别名/宏 + subprocess 执行 + TUI + SQLite 历史
- P2：安全与风控（沙箱 + yes 确认 + 身份验证）
- P3：AI 智能层（纠错 + 角色化 + 感知自互动）
- P4：Agent 自动化（代码即行动 + Python 函数包装）
- P5：打磨（可定制启动界面 + 炫酷界面细化）

设计文档：`docs/superpowers/specs/2026-08-12-opendracocli-p1-kernel-design.md`

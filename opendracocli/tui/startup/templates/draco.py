"""内置模板: draco

OpenDracoCLI 默认品牌启动画面: 居中的 Draco 龙 ASCII art + 下方品牌信息行。
ANSI 多色 (青蓝主调 + 强调色), 比 minimal 更精致, 比 neofetch_style 更聚焦品牌。
信息行字段缺失 (空串) 则该项不显示; session_id 取前 8 位。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..loader import StartupContext

# ANSI 颜色 — 与 draco 主题的 accent 主调一致
CYAN = "\033[38;5;81m"      # 主色 (亮青蓝)
DIM_CYAN = "\033[38;5;38m"  # 辅助色 (深青)
MAGENTA = "\033[38;5;141m"  # 强调色 (紫)
GREEN = "\033[38;5;114m"    # 成功色 (柔绿)
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# 居中的 Draco 龙 ASCII art (11 行, 比通用版更精致)
_DRAGON = r"""
            /\
           /  \      ___
          /    \    /   \
         / /\   \  /     \
        / /  \   \/   /\  \
       / /    \      /  \  \
      / / /\   \    /    \  \
     / / /  \   \  /      \  \
    /_/ /    \   \/        \__\
    \_\/      \__\         \__/
"""


def _info_lines(ctx: StartupContext) -> list[str]:
    """构造品牌信息行, 空字段跳过"""
    lines: list[str] = []
    # 第一行: 品牌 + 版本 (加粗 + 主色)
    head = f"{BOLD}{CYAN}OpenDracoCLI{RESET}{DIM_CYAN} v{ctx.version}{RESET}"
    if ctx.platform:
        head += f" {DIM}({ctx.platform}){RESET}"
    lines.append(head)
    # 第二行: Python + Session (用 │ 分隔)
    parts: list[str] = []
    if ctx.python_version:
        parts.append(f"{DIM}Python {ctx.python_version}{RESET}")
    sid = (ctx.session_id or "")[:8]
    if sid:
        parts.append(f"{DIM}Session {sid}{RESET}")
    if parts:
        lines.append(f"  {DIM}│{RESET}  ".join(parts))
    # 第三行: 启动耗时 (强调色)
    if ctx.uptime_hint:
        lines.append(f"{MAGENTA}{ctx.uptime_hint}{RESET}")
    # 第四行: 上次会话摘要 (柔绿, 非空时显示)
    if ctx.last_session_summary:
        summary = ctx.last_session_summary[:60] + ("…" if len(ctx.last_session_summary) > 60 else "")
        lines.append(f"{GREEN}↻ {summary}{RESET}")
    return lines


def render(ctx: StartupContext) -> str:
    """渲染 draco 模板: 居中龙 art + 品牌信息行"""
    art = _DRAGON.strip("\n")
    body = "\n".join(_info_lines(ctx))
    # art 用主色, 信息行自带颜色
    return f"{CYAN}{art}{RESET}\n{body}"

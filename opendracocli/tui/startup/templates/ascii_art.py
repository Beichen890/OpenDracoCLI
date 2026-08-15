"""内置模板: ascii_art

精致 Draco 龙 ASCII art (~12 行, 用 /\\ / 等 claws 字符 + 鳞片细节),
下方接信息行 (版本/平台/python/session/uptime)。带 ANSI 青色。
信息行字段缺失 (空串) 则该行不显示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..loader import StartupContext

# ANSI 颜色
CYAN = "\033[36m"
DIM_CYAN = "\033[38;5;38m"
RESET = "\033[0m"

# 精致 Draco 龙 ASCII art (12 行, 加鳞片与爪细节)
_DRAGON = r"""
           /\                 /\
          /  \               /  \
         /    \  /\___/\___/    \
        /  /\  \/ _   / _  \  /\  \
       /  /  \ /  __//  __/ /  \ \  \
      /  /    \  ___/\___/  /   \ \  \
     /__/ \    \/  \/  \/  /    /  \ \__\
       \   \   /\  /\  /\  \   /   /
        \   \/_/  \/  \/  \/_/   /
         \__/                \__/
"""

# 备选: 简化版龙头 (兜底使用)
_DRAGON_SIMPLE = r"""         /\                 /\
        /  \               /  \
       /    \/\___/\___/\_//   \
      /  /\  / _   / _  \  /\   \
     /  /  \/  __//  __/ /  \ \  \
    /__/ \__\___/ \___/ \__/\_\__\
       \   \ \/\   /\/\  /  /  /
        \   \/--/  \_/_/-/  /  /
         \__/             \__/
"""


def _info_lines(ctx: StartupContext) -> list[str]:
    """构造信息行, 空字段跳过"""
    lines: list[str] = []
    head = f"OpenDracoCLI v{ctx.version}"
    if ctx.platform:
        head += f" ({ctx.platform})"
    lines.append(head)
    parts: list[str] = []
    if ctx.python_version:
        parts.append(f"Python {ctx.python_version}")
    sid = (ctx.session_id or "")[:8]
    if sid:
        parts.append(f"Session {sid}")
    if parts:
        lines.append("  ".join(parts))
    if ctx.uptime_hint:
        lines.append(ctx.uptime_hint)
    return lines


def render(ctx: StartupContext) -> str:
    """渲染 ascii_art 模板: 龙 ASCII art + 信息行"""
    try:
        art = _DRAGON.strip("\n")
    except Exception:
        art = _DRAGON_SIMPLE.strip("\n")
    body = "\n".join(_info_lines(ctx))
    return f"{CYAN}{art}{RESET}\n{DIM_CYAN}{'─' * 36}{RESET}\n{body}"

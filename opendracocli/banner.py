"""OpenDracoCLI 彩色品牌横幅

参考 DracoHub CLI 风格: 大号 Block Logo (ANSI Shadow / FIGlet 风格) + 状态行。
用 Rich 渲染彩色, 无 Rich 时降级到 ANSI/colorama 纯文本。
"""

from __future__ import annotations

import shutil
from typing import Optional

# ── 品牌配色 (与 DracoHub 一致: 龙焰金 / 深紫 / 青蓝) ──
C_PRIMARY = "bold cyan"           # 主色: 青蓝
C_ACCENT = "bold yellow"          # 强调: 金色
C_BRAND = "bold magenta"          # 品牌: 紫红
C_SUCCESS = "bold green"          # 成功
C_ERROR = "bold red"              # 错误
C_WARN = "yellow"                 # 警告
C_DIM = "dim"                     # 次要
C_INFO = "cyan"                   # 信息

# ── OPENDRACO 大号 Block Logo (ANSI Shadow 风格, 6 行) ──
# 用 █ 块字符组成 OPENDRACO 字样, 比 ASCII art 整齐精致
_OPENDRACO_LOGO = r"""
  ___                    ____                          _
 / _ \  _ __   ___ _ __ / ___|___  _ __ _ __   ___  ___| |_
| | | || '_ \ / _ \ '__| |   / _ \| '__| '_ \ / _ \/ __| __|
| |_| || |_) |  __/ |  | |__| (_) | |  | |_) | (_) \__ \ |_
 \___/ | .__/ \___|_|   \____\___/|_|  | .__/ \___/|___/\__|
       |_|                             |_|
"""

# 备选: 紧凑版 DRACO (4 行, 终端窄时用)
_DRACO_LOGO_COMPACT = r"""
 ____  _                _
|  _ \(_)___  _ __ ___ | |__   ___
| | | | / __|| '_ ` _ \| '_ \ / _ \
| |_| | \__ \| | | | | | |_) |  __/
|____/|_|___/|_| |_| |_|_.__/ \___|
"""


def _term_width() -> int:
    """获取终端宽度"""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _has_rich() -> bool:
    """检测 Rich 是否可用"""
    try:
        from rich.console import Console  # noqa: F401

        return True
    except ImportError:
        return False


def _has_colorama() -> bool:
    """检测 colorama 是否可用"""
    try:
        import colorama  # noqa: F401

        return True
    except ImportError:
        return False


def _c_fallback(text: str, color: str = "") -> str:
    """无 Rich 时的 ANSI 颜色回退 (用 colorama)"""
    if not _has_colorama():
        return text
    from colorama import Fore, Style

    colors = {
        "green": Fore.GREEN, "yellow": Fore.YELLOW, "cyan": Fore.CYAN,
        "magenta": Fore.MAGENTA, "red": Fore.RED, "blue": Fore.BLUE,
        "white": Fore.WHITE, "reset": Style.RESET_ALL,
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def render_banner(
    *,
    version: str = "",
    platform: str = "",
    session_id: str = "",
    ai_status: str = "",
    agent_status: str = "",
    uptime_hint: str = "",
) -> str:
    """渲染品牌横幅: 大号 Block Logo + 状态行

    返回 ANSI 字符串 (含 Rich 标记或 ANSI 转义), 调用方直接 print。
    """
    if _has_rich():
        from rich.console import Console
        from rich.panel import Panel
        from rich.rule import Rule
        from io import StringIO

        # 用 StringIO 离屏渲染, 返回字符串
        buf = StringIO()
        console = Console(
            file=buf, force_terminal=True, legacy_windows=False, width=_term_width()
        )
        w = _term_width()

        # ── 大号 Block Logo (居中, 主色) ──
        logo = _OPENDRACO_LOGO if w >= 60 else _DRACO_LOGO_COMPACT
        logo_lines = logo.strip("\n").split("\n")
        console.print()  # 顶部留空
        for line in logo_lines:
            clean = line.rstrip()
            pad = max(0, (w - len(clean)) // 2)
            console.print(" " * pad + clean, style=C_PRIMARY)

        # ── 状态行 ──
        console.print()
        head = "◆ OpenDracoCLI 已就绪"
        if version:
            head += f"  v{version}"
        console.print(f"  {head}", style=C_ACCENT)
        # 详情行: 平台/会话/AI/Agent
        details = []
        if platform:
            details.append(("平台", platform))
        if session_id:
            details.append(("会话", session_id[:8]))
        if ai_status:
            details.append(("AI", ai_status))
        if agent_status:
            details.append(("Agent", agent_status))
        if details:
            line = "  "
            for i, (k, v) in enumerate(details):
                if i > 0:
                    line += "  "
                line += f"[{C_DIM}]{k}[/] [{C_INFO}]{v}[/]"
            console.print(line)
        # 命令提示
        console.print(
            f"  [{C_DIM}]◆ 输入[/] [{C_SUCCESS}]/help[/] [{C_DIM}]查看命令 ·[/] "
            f"[{C_SUCCESS}]/ai[/] [{C_DIM}]AI ·[/] "
            f"[{C_SUCCESS}]/agent[/] [{C_DIM}]Agent ·[/] "
            f"[{C_SUCCESS}]/quit[/] [{C_DIM}]退出[/]"
        )
        if uptime_hint:
            console.print(f"  [{C_BRAND}]{uptime_hint}[/]")
        console.print()
        return buf.getvalue()

    # ── 降级: 纯文本 + colorama ──
    lines = []
    lines.append("")
    w = _term_width()
    logo = _OPENDRACO_LOGO if w >= 60 else _DRACO_LOGO_COMPACT
    for line in logo.strip("\n").split("\n"):
        clean = line.rstrip()
        pad = max(0, (w - len(clean)) // 2)
        lines.append(" " * pad + _c_fallback(clean, "cyan"))
    lines.append("")
    head = "◆ OpenDracoCLI 已就绪"
    if version:
        head += f"  v{version}"
    lines.append(f"  {_c_fallback(head, 'yellow')}")
    details = []
    if platform:
        details.append(("平台", platform))
    if session_id:
        details.append(("会话", session_id[:8]))
    if ai_status:
        details.append(("AI", ai_status))
    if agent_status:
        details.append(("Agent", agent_status))
    if details:
        line = "  " + "  ".join(f"{k} {v}" for k, v in details)
        lines.append(line)
    lines.append("  ◆ 输入 /help 查看命令 · /ai AI · /agent Agent · /quit 退出")
    if uptime_hint:
        lines.append(f"  {_c_fallback(uptime_hint, 'magenta')}")
    lines.append("")
    return "\n".join(lines)


def print_divider(title: str = "") -> None:
    """打印分隔线 (Rich Rule 或纯文本 ─)"""
    if _has_rich():
        from rich.console import Console
        from rich.rule import Rule

        console = Console()
        if title:
            console.print(Rule(title=title, style=C_PRIMARY))
        else:
            console.print(Rule(style=C_DIM))
    else:
        w = _term_width()
        if title:
            print(_c_fallback("─" * min(w, 78), "white"))
            print(_c_fallback(f"  {title}", "cyan"))
            print(_c_fallback("─" * min(w, 78), "white"))
        else:
            print(_c_fallback("─" * min(w, 78), "white"))


def print_panel(content: str, title: str = "", style: str = C_PRIMARY) -> None:
    """打印带边框的面板 (Rich Panel HEAVY 或纯文本 ┃)"""
    if _has_rich():
        from rich.console import Console
        from rich.panel import Panel
        from rich.box import HEAVY

        panel = Panel(
            content.rstrip(),
            title=title if title else None,
            title_align="left",
            border_style=style,
            box=HEAVY,
            padding=(1, 2),
        )
        Console().print(panel)
    else:
        w = _term_width()
        if title:
            print(_c_fallback("┏" + "━" * min(w - 2, 76) + "┓", "cyan"))
            print(f"{_c_fallback('┃', 'cyan')} {_c_fallback(title, 'yellow')}")
            print(_c_fallback("┣" + "━" * min(w - 2, 76) + "┫", "cyan"))
        else:
            print(_c_fallback("┏" + "━" * min(w - 2, 76) + "┓", "cyan"))
        for line in content.split("\n"):
            print(f"{_c_fallback('┃', 'cyan')} {line}")
        print(_c_fallback("┗" + "━" * min(w - 2, 76) + "┛", "cyan"))


def print_success(msg: str) -> None:
    """打印成功消息"""
    if _has_rich():
        from rich.console import Console

        Console().print(f"  ✅ {msg}", style=C_SUCCESS)
    else:
        print(f"  {_c_fallback('✅ ' + msg, 'green')}")


def print_error(msg: str) -> None:
    """打印错误消息"""
    if _has_rich():
        from rich.console import Console

        Console().print(f"  ❌ {msg}", style=C_ERROR)
    else:
        print(f"  {_c_fallback('❌ ' + msg, 'red')}")


def print_warn(msg: str) -> None:
    """打印警告消息"""
    if _has_rich():
        from rich.console import Console

        Console().print(f"  ⚠️  {msg}", style=C_WARN)
    else:
        print(f"  {_c_fallback('⚠️  ' + msg, 'yellow')}")


def print_info(msg: str) -> None:
    """打印信息消息"""
    if _has_rich():
        from rich.console import Console

        Console().print(f"  ℹ️  {msg}", style=C_INFO)
    else:
        print(f"  {_c_fallback('ℹ️  ' + msg, 'cyan')}")

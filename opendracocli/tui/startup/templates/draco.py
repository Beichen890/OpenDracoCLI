"""内置模板: draco

OpenDracoCLI 默认品牌启动画面: 用代码扫描内置 draco_logo.jpg 像素,
渲染为真彩色半块字符 (▀) 像素艺术 + 下方品牌信息行。
比手画 ASCII 整齐精致, 分辨率翻倍 (每字符格覆盖 2 像素行)。

无 Pillow 或图像加载失败时, 降级到纯 ASCII 龙 art, 绝不抛异常。
信息行字段缺失 (空串) 则该项不显示; session_id 取前 8 位。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..loader import StartupContext

from ..blockart import render_image_to_blocks, has_pillow

# 内置 logo 图像路径: opendracocli/tui/startup/assets/draco_logo.jpg
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "draco_logo.jpg"

# ANSI 颜色 — 与 draco 主题的 accent 主调一致
CYAN = "\033[38;5;81m"      # 主色 (亮青蓝)
DIM_CYAN = "\033[38;5;38m"  # 辅助色 (深青)
MAGENTA = "\033[38;5;141m"  # 强调色 (紫)
GREEN = "\033[38;5;114m"    # 成功色 (柔绿)
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# 降级兜底: 无 Pillow 时的纯 ASCII 龙 art (10 行)
_FALLBACK_DRAGON = r"""            /\
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
        summary = ctx.last_session_summary[:60] + (
            "…" if len(ctx.last_session_summary) > 60 else ""
        )
        lines.append(f"{GREEN}↻ {summary}{RESET}")
    return lines


def render(ctx: StartupContext) -> str:
    """渲染 draco 模板: 色块龙 art + 品牌信息行

    优先用 Pillow 扫描 draco_logo.jpg 像素渲染真彩色色块艺术;
    无 Pillow 或加载失败时降级到 ASCII 兜底。
    """
    art = ""
    if has_pillow():
        art = render_image_to_blocks(
            _LOGO_PATH,
            width=60,
            height=22,
            bg_threshold=256,  # 禁用背景替换, 全像素输出色块 (logo 本身有透明边)
        )
    if not art:
        # 降级: 纯 ASCII 龙 + 主色
        art = f"{CYAN}{_FALLBACK_DRAGON.strip(chr(10))}{RESET}"
    body = "\n".join(_info_lines(ctx))
    return f"{art}\n{body}"

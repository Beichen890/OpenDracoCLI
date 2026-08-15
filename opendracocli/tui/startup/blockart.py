"""图像 → 色块字符渲染器

扫描图像像素, 用半块字符 (▀) 将每两个垂直像素压缩为一个字符格,
前景色 = 上像素, 背景色 = 下像素, 实现 2 倍垂直分辨率。
支持 LANCZOS 重采样 + 可调宽度 + 真彩色 24-bit ANSI 输出。

无 Pillow 时降级为纯文本兜底, 绝不抛异常。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from PIL import Image  # type: ignore

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def render_image_to_blocks(
    image_path: Path,
    width: int = 60,
    height: Optional[int] = None,
    bg_threshold: int = 240,
) -> str:
    """扫描图像像素, 渲染为真彩色半块字符 ANSI 字符串。

    Args:
        image_path: 图像文件路径
        width: 输出字符列数 (每列对应一个像素列)
        height: 输出字符行数 (None 则按图像宽高比自动计算)
        bg_threshold: 亮度阈值, 亮于此值的像素格用空格替代以减少噪声 (0-255,
                     设为 256 则禁用此优化, 全部输出色块)

    Returns:
        ANSI 真彩色字符串, 每行用 \\n 分隔。失败返回空串。
    """
    if not _HAS_PIL:
        return ""

    try:
        im = Image.open(image_path).convert("RGB")
    except Exception:
        return ""

    src_w, src_h = im.size
    # 计算目标像素尺寸 (字符行数 × 2, 因为半块字符每行覆盖 2 像素行)
    if height is None:
        # 保持宽高比: 字符高度 = (width × src_h / src_w) / 2
        char_h = max(1, int(round(width * src_h / src_w / 2)))
    else:
        char_h = max(1, int(height))

    px_w = max(1, int(width))
    px_h = char_h * 2
    im = im.resize((px_w, px_h), Image.LANCZOS)
    px = im.load()

    lines: list[str] = []
    for y in range(char_h):
        line_parts: list[str] = []
        for x in range(px_w):
            ur, ug, ub = px[x, y * 2]
            lr, lg, lb = px[x, y * 2 + 1]
            up_lum = (ur * 299 + ug * 587 + ub * 114) // 1000
            lo_lum = (lr * 299 + lg * 587 + lb * 114) // 1000
            # 两像素都接近背景白 → 输出空格, 减少 ANSI 噪声 + 提速
            if up_lum >= bg_threshold and lo_lum >= bg_threshold:
                line_parts.append(" ")
                continue
            # 用 ▀: 前景=上像素, 背景=下像素
            line_parts.append(
                f"\033[38;2;{ur};{ug};{ub}m\033[48;2;{lr};{lg};{lb}m▀\033[0m"
            )
        lines.append("".join(line_parts))
    return "\n".join(lines)


def has_pillow() -> bool:
    """是否安装了 Pillow (用于模板层降级判断)"""
    return _HAS_PIL

"""历史侧栏 Widget — 显示最近 N 条命令，点击/回车回填输入区

视觉规范:
- 成功 (exit_code==0): 绿色 ✓ 前缀
- 失败 (exit_code!=0): 红色 ×N 前缀
- 未知 (exit_code is None): dim ? 前缀
- 命令文本: 普通前景色, 过长用 … 截断
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option


@dataclass
class HistoryEntry:
    """一条历史条目"""

    raw_input: str
    exit_code: Optional[int]
    id: Optional[int]


class HistorySidebar(OptionList):
    """历史侧栏

    发出 HistorySelected 消息（含 raw_input）供 App 回填输入框。
    默认只加载最近 50 条，滚动时由 App 按需追加。
    """

    DEFAULT_CSS = """
    HistorySidebar {
        border: round $accent;
        background: $boost;
        width: 32;
        min-width: 20;
        max-width: 48;
        height: 1fr;
        display: block;
        scrollbar-size: 1 1;
        scrollbar-color: $text-muted $boost;
    }
    HistorySidebar.-hidden {
        display: none;
    }
    HistorySidebar > .option-list--option-highlighted {
        background: $accent 20%;
        text-style: bold;
    }
    """

    class HistorySelected(Message):
        """用户选中某条历史"""

        def __init__(self, raw_input: str) -> None:
            self.raw_input = raw_input
            super().__init__()

    def __init__(self) -> None:
        super().__init__(name="history")
        self.border_title = "◈ 历史"
        self._entries: list[HistoryEntry] = []

    def load_entries(self, entries: list[HistoryEntry]) -> None:
        """加载历史条目（覆盖）"""
        self._entries = list(entries)
        self.clear_options()
        for e in self._entries:
            self.add_option(self._format_option(e))

    def append_entries(self, entries: list[HistoryEntry]) -> None:
        """追加条目（滚动加载时用）"""
        for e in entries:
            self._entries.append(e)
            self.add_option(self._format_option(e))

    def push_latest(self, entry: HistoryEntry) -> None:
        """新执行一条命令后插入到顶部"""
        self._entries.insert(0, entry)
        # 限制条数
        if len(self._entries) > 200:
            self._entries = self._entries[:200]
        # Textual OptionList 无 insert-at-index API, 重建选项列表以保持最新在顶部
        self.clear_options()
        for e in self._entries:
            self.add_option(self._format_option(e))

    @staticmethod
    def _format_option(e: HistoryEntry) -> Option:
        """格式化历史条目: 颜色编码退出码 + 截断过长输入"""
        if e.exit_code == 0:
            mark = "[green]✓[/]"
        elif e.exit_code is None:
            mark = "[dim]?[/]"
        else:
            mark = f"[red]×{e.exit_code}[/]"
        # 截断过长输入
        raw = e.raw_input[:60] + ("…" if len(e.raw_input) > 60 else "")
        return Option(
            f"{mark} {raw}",
            id=str(e.id) if e.id is not None else None,
        )

    def toggle_hidden(self) -> None:
        """切换显隐"""
        if self.has_class("-hidden"):
            self.remove_class("-hidden")
        else:
            self.add_class("-hidden")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """回车选中 → 发出消息"""
        idx = event.option_index
        if 0 <= idx < len(self._entries):
            self.post_message(self.HistorySelected(self._entries[idx].raw_input))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """高亮即预览（不回填，避免误触）"""
        # 不主动回填，仅选中时回填

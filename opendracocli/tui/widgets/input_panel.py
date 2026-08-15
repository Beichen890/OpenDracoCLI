"""输入区 Widget — 命令输入框 + 历史回溯

基于 textual Input，回车提交。历史回溯（上下方向键）由 App 监听按键处理
（textual Input 默认绑定了上下方向键移动光标，App 通过 keymap 拦截或
提供独立的历史回溯快捷键）。

视觉规范:
- 默认态: 圆角 accent 边框 + boost 背景
- 焦点态: 双线 accent 边框 + 加粗文字
- 占位符: dim 斜体提示
"""

from __future__ import annotations

from typing import Optional

from textual.message import Message
from textual.widgets import Input


class InputPanel(Input):
    """命令输入框"""

    DEFAULT_CSS = """
    InputPanel {
        dock: top;
        border: round $accent;
        background: $boost;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    InputPanel:focus {
        border: double $accent;
        text-style: bold;
    }
    InputPanel > .input--placeholder {
        color: $text-muted;
        text-style: italic;
    }
    InputPanel > .input--cursor {
        color: $accent;
        text-style: bold;
    }
    InputPanel > .input--selection {
        background: $accent 30%;
    }
    """

    class Submitted(Message):
        """用户回车提交命令

        兼容 Textual ``Input.Submitted`` 的构造签名 (input, value, validation_result)，
        由 ``Input.action_submit`` 直接构造发出；App 通过 ``on_input_panel_submitted``
        接收。与 PasswordScreen 的 ``Input.Submitted`` 隔离 (不同消息类型)。
        """

        def __init__(
            self,
            input: "Input",
            value: str,
            validation_result: Optional[object] = None,
        ) -> None:
            self.input = input
            self.value = value
            self.validation_result = validation_result
            super().__init__()

    def __init__(self) -> None:
        super().__init__(placeholder="❯ 输入命令或 /help …", name="input")
        self.border_title = "◈ 命令"

    def fill(self, text: str) -> None:
        """回填历史到输入框"""
        self.value = text
        self.cursor_position = len(text)
        self.focus()

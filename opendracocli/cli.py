"""OpenDracoCLI TUI 主循环 — prompt_toolkit 输入 + rich 渲染

特性:
  - prompt_toolkit 提供输入行：历史回溯（上下方向键）、Tab 补全、多行
  - rich 渲染输出（彩色 stdout/stderr、错误面板）
  - 内置 slash 命令：/alias /aliases /history /risk /help /quit
  - P2 风控：RiskAssessmentHook + SandboxExecutor 自动接线
  - 会话 ID（启动生成）
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from .aliases.manager import AliasManager, get_global_manager
from .config import DracoConfig, get_global_config
from .errors import DracoError
from .events import EVT_SESSION_ENDED, EVT_SESSION_STARTED, Event, get_global_bus
from .history.store import HistoryStore, get_global_store
from .hooks.risk_hook import RiskAssessmentHook
from .hooks.registry import get_global_registry
from .logger import get_logger
from .security.authenticator import Authenticator
from .security.confirmer import Confirmer
from .security.risk_assessor import RiskAssessor, get_global_assessor
from .security.sandbox import SandboxExecutor
from .shell.pipeline import ShellPipeline

log = get_logger("cli")


def _get_prompt_text() -> str:
    """生成提示符（含 cwd）"""
    cwd = os.getcwd()
    # 缩短 home 路径
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    return f"draco {cwd}> "


class OpenDracoCLI:
    """TUI 主应用"""

    def __init__(
        self,
        config: Optional[DracoConfig] = None,
        alias_manager: Optional[AliasManager] = None,
        history_store: Optional[HistoryStore] = None,
    ) -> None:
        self._config = config or get_global_config()
        self._aliases = alias_manager or get_global_manager()
        self._history = history_store or get_global_store()

        # P2: 接线风控组件
        self._assessor = get_global_assessor(self._config)
        self._confirmer = Confirmer()
        self._authenticator = Authenticator(
            hash_path=self._config.auth_hash_file_resolved,
            iterations=self._config.pbkdf2_iterations,
        )
        self._sandbox = SandboxExecutor(
            inner=None,  # 占位，pipeline 创建后再绑定
            writable_paths=self._config.sandbox_writable_paths_resolved,
        )

        self._pipeline = ShellPipeline(
            config=self._config,
            alias_manager=self._aliases,
            history_store=self._history,
        )
        # 绑定沙箱的 inner executor 为 pipeline 的原生 executor
        self._sandbox._inner = self._pipeline._executor
        self._pipeline.set_sandbox_executor(self._sandbox)

        # 注册 RiskAssessmentHook（priority=10，最先执行）
        self._risk_hook = RiskAssessmentHook(
            assessor=self._assessor,
            confirmer=self._confirmer,
            authenticator=self._authenticator,
            config=self._config,
        )
        get_global_registry().register_pre(self._risk_hook)

        self._session_id = str(uuid.uuid4())
        self._running = False

    async def run(self) -> None:
        """启动 TUI 主循环"""
        self._running = True
        get_global_bus().publish(
            Event(
                type=EVT_SESSION_STARTED,
                payload={"session_id": self._session_id, "platform": self._config.current_platform},
            )
        )

        # rich 可用则用它打印启动横幅
        try:
            from rich.console import Console
            from rich.panel import Panel

            console = Console()
            console.print(
                Panel.fit(
                    "[bold cyan]OpenDracoCLI[/] — AI 时代的智能终端 (P1)\n"
                    f"平台: {self._config.current_platform}  会话: {self._session_id[:8]}\n"
                    "输入 [green]/help[/] 查看内置命令，[green]/quit[/] 退出",
                    border_style="cyan",
                )
            )
            self._rich = True
        except ImportError:
            self._rich = False
            print("OpenDracoCLI (P1) — /help for commands, /quit to exit")

        # 历史 tail 提示
        try:
            recent = self._history.recent(limit=3, session_id=None)
            if recent:
                print(f"(最近 {len(recent)} 条历史可用方向键回溯)")
        except Exception:
            pass

        # prompt_toolkit 历史
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory

            # 从 SQLite 加载历史到内存（prompt_toolkit 的方向键回溯）
            pt_history = InMemoryHistory()
            try:
                for rec in reversed(self._history.recent(limit=500, session_id=None)):
                    pt_history.append_string(rec.raw_input)
            except Exception:
                pass

            session = PromptSession(history=pt_history)
            self._pt_session = session
            self._pt_available = True
        except ImportError:
            self._pt_available = False
            self._pt_session = None

        while self._running:
            try:
                if self._pt_available:
                    text = await session.prompt_async(_get_prompt_text())
                else:
                    # 回退到 input()
                    text = input(_get_prompt_text())
            except (EOFError, KeyboardInterrupt):
                # Ctrl+D / Ctrl+C 退出
                print()
                break

            text = text.strip()
            if not text:
                continue

            # slash 命令
            if text.startswith("/"):
                handled = self._handle_slash(text)
                if handled == "quit":
                    break
                continue

            # 执行命令
            await self._exec_command(text)

        self._running = False
        get_global_bus().publish(
            Event(type=EVT_SESSION_ENDED, payload={"session_id": self._session_id})
        )
        try:
            self._history.close()
        except Exception:
            pass

    async def _exec_command(self, text: str) -> None:
        """执行一条命令并渲染输出"""
        try:
            result = await self._pipeline.run(
                text, session_id=self._session_id
            )
        except Exception as e:
            log.exception("pipeline crashed")
            self._render_error(f"管线异常: {e}")
            return

        if result.blocked:
            self._render_block(result)
            return

        if not result.success and result.error is not None:
            self._render_draco_error(result.error)
            return

        # 渲染 stdout/stderr
        if result.stdout:
            sys.stdout.write(result.stdout)
            if not result.stdout.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
        if result.stderr:
            sys.stderr.write(result.stderr)
            if not result.stderr.endswith("\n"):
                sys.stderr.write("\n")
            sys.stderr.flush()

        # 非零退出码提示
        if result.exit_code not in (0, None):
            self._render_error(
                f"退出码 {result.exit_code}" + (f"（别名 {result.alias_used}）" if result.alias_used else "")
            )

    def _handle_slash(self, text: str) -> Optional[str]:
        """处理 / 开头的内置命令，返回 'quit' 或 None"""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            return "quit"
        if cmd in ("/help", "/h", "/?"):
            self._print_help()
            return None
        if cmd == "/alias":
            self._handle_alias_cmd(arg)
            return None
        if cmd == "/aliases":
            self._list_aliases()
            return None
        if cmd == "/history":
            self._show_history(arg)
            return None
        if cmd == "/risk":
            self._handle_risk_cmd(arg)
            return None
        self._render_error(f"未知命令: {cmd}（/help 查看可用命令）")
        return None

    def _print_help(self) -> None:
        print("内置命令:")
        print("  /alias <name> <expansion>   添加/更新别名")
        print("  /alias <name>               查看别名")
        print("  /alias -d <name>            删除别名")
        print("  /aliases                    列出所有别名")
        print("  /history [N]                显示最近 N 条历史（默认 20）")
        print("  /risk                       显示当前风险规则表")
        print("  /risk test <command>        模拟评估命令风险（不执行）")
        print("  /help                       显示此帮助")
        print("  /quit                       退出")

    def _handle_alias_cmd(self, arg: str) -> None:
        """处理 /alias 子命令"""
        arg = arg.strip()
        if not arg:
            self._list_aliases()
            return
        if arg.startswith("-d "):
            name = arg[3:].strip()
            if self._aliases.remove(name):
                print(f"已删除别名: {name}")
            else:
                self._render_error(f"别名不存在: {name}")
            return
        # /alias name expansion...
        parts = arg.split(maxsplit=1)
        if len(parts) == 1:
            # 查看
            exp = self._aliases.get(parts[0])
            if exp is not None:
                print(f"{parts[0]} = {exp}")
            else:
                self._render_error(f"别名不存在: {parts[0]}")
            return
        name, expansion = parts
        is_new = self._aliases.add(name, expansion)
        print(f"{'已添加' if is_new else '已更新'}别名: {name} = {expansion}")

    def _list_aliases(self) -> None:
        aliases = self._aliases.list()
        if not aliases:
            print("（无别名，用 /alias <name> <expansion> 添加）")
            return
        for name in sorted(aliases):
            print(f"  {name} = {aliases[name]}")

    def _show_history(self, arg: str) -> None:
        try:
            n = int(arg) if arg.strip() else 20
        except ValueError:
            n = 20
        try:
            recs = self._history.recent(limit=n, session_id=None)
        except DracoError as e:
            self._render_draco_error(e)
            return
        if not recs:
            print("（无历史记录）")
            return
        print(f"最近 {len(recs)} 条历史:")
        for r in reversed(recs):  # 时间正序显示
            status = "OK" if r.exit_code == 0 else (f"×{r.exit_code}" if r.exit_code is not None else "?")
            print(f"  [{status}] {r.raw_input}")

    def _handle_risk_cmd(self, arg: str) -> None:
        """处理 /risk 子命令

        /risk                  — 显示当前规则表
        /risk test <command>   — 模拟评估某命令的风险等级（不执行）
        """
        arg = arg.strip()
        if not arg:
            self._show_risk_rules()
            return
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower()
        if sub == "test":
            if len(parts) < 2:
                self._render_error("用法: /risk test <command>")
                return
            self._preview_risk(parts[1])
            return
        self._render_error(f"未知子命令: {sub}（可用: test）")

    def _show_risk_rules(self) -> None:
        """显示当前生效的风险规则表"""
        from .security.risk_assessor import RiskLevel

        level_order = [RiskLevel.CRITICAL, RiskLevel.DANGER, RiskLevel.CAUTION]
        level_label = {
            RiskLevel.CRITICAL: "🚨 CRITICAL",
            RiskLevel.DANGER: "🔴 DANGER",
            RiskLevel.CAUTION: "⚠️  CAUTION",
        }
        if getattr(self, "_rich", False):
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(title="风险规则表", border_style="cyan")
            table.add_column("等级", style="bold")
            table.add_column("命令")
            table.add_column("args_contain")
            table.add_column("exact_args")
            table.add_column("说明")
            for level in level_order:
                for pat in self._assessor._patterns_by_level[level]:
                    table.add_row(
                        level_label[level],
                        pat.cmd,
                        ",".join(pat.args_contain) or "-",
                        ",".join(pat.exact_args) or "-",
                        pat.desc,
                    )
            console.print(table)
        else:
            print("风险规则表:")
            for level in level_order:
                pats = self._assessor._patterns_by_level[level]
                if not pats:
                    continue
                print(f"  [{level_label[level]}]")
                for pat in pats:
                    ac = ",".join(pat.args_contain) or "-"
                    ea = ",".join(pat.exact_args) or "-"
                    print(f"    {pat.cmd}  contain=[{ac}] exact=[{ea}]  {pat.desc}")

    def _preview_risk(self, command: str) -> None:
        """模拟评估某命令的风险等级（不执行）"""
        from .shell.parser import parse
        from .shell.normalizer import normalize

        try:
            ir = parse(command)
            normalize(ir)
            # 别名展开 + 平台映射（与真实管线一致，确保评估准确）
            ir, _ = self._pipeline._expander.expand(ir)
            self._pipeline._mapper.map(ir)
        except DracoError as e:
            self._render_draco_error(e)
            return

        assessment = self._assessor.assess(ir)
        level = assessment.level
        label = {
            "safe": "✅ SAFE",
            "caution": "⚠️  CAUTION",
            "danger": "🔴 DANGER",
            "critical": "🚨 CRITICAL",
        }.get(level.value, level.value)

        if getattr(self, "_rich", False):
            from rich.console import Console
            from rich.panel import Panel

            console = Console()
            color = {
                "safe": "green",
                "caution": "yellow",
                "danger": "red",
                "critical": "bold red",
            }.get(level.value, "white")
            body = f"[{color}]{label}[/]\n命令: {command}\n"
            if assessment.reason:
                body += f"原因: {assessment.reason}\n"
            if assessment.matched_rules:
                body += "命中规则:\n"
                for m in assessment.matched_rules:
                    body += f"  - [{m.level.value}] {m.cmd}: {m.desc}\n"
            console.print(Panel(body.strip(), title="风险预览", border_style=color))
        else:
            print(f"风险预览: {label}")
            print(f"  命令: {command}")
            if assessment.reason:
                print(f"  原因: {assessment.reason}")
            for m in assessment.matched_rules:
                print(f"  命中: [{m.level.value}] {m.cmd}: {m.desc}")

    def _render_error(self, msg: str) -> None:
        if getattr(self, "_rich", False):
            from rich.console import Console
            Console().print(f"[bold red]错误:[/] {msg}")
        else:
            print(f"错误: {msg}", file=sys.stderr)

    def _render_draco_error(self, err: DracoError) -> None:
        if getattr(self, "_rich", False):
            from rich.console import Console
            from rich.panel import Panel

            Console().print(
                Panel(
                    f"[bold red]{err.code}[/]\n{err.message}",
                    title="命令失败",
                    border_style="red",
                )
            )
        else:
            print(f"[{err.code}] {err.message}", file=sys.stderr)

    def _render_block(self, result) -> None:
        msg = result.block_reason or "被钩子阻断"
        if getattr(self, "_rich", False):
            from rich.console import Console
            Console().print(f"[bold yellow]已阻断:[/] {msg}")
        else:
            print(f"已阻断: {msg}", file=sys.stderr)


def main() -> None:
    """入口函数（pyproject scripts 指向）

    支持参数:
      --setup-auth   设置/重置身份验证密码（用于 critical 级操作）
    """
    args = sys.argv[1:]
    if "--setup-auth" in args:
        _setup_auth_interactive()
        return
    app = OpenDracoCLI()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass


def _setup_auth_interactive() -> None:
    """交互式设置身份验证密码"""
    cfg = get_global_config()
    auth = Authenticator(
        hash_path=cfg.auth_hash_file_resolved,
        iterations=cfg.pbkdf2_iterations,
    )
    print("OpenDracoCLI — 设置身份验证密码")
    print(f"  哈希文件: {cfg.auth_hash_file_resolved}")
    print(f"  算法: PBKDF2-HMAC-SHA256 ({cfg.pbkdf2_iterations} 轮)")
    if auth.is_configured():
        print("  ⚠️  已存在密码，将覆盖。")
    print()

    try:
        pw1 = input("请输入新密码: ")
        if not pw1:
            print("密码不能为空，已取消。")
            return
        pw2 = input("请再次输入以确认: ")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return

    if pw1 != pw2:
        print("两次输入不一致，已取消。")
        return
    auth.set_password(pw1)
    print("✅ 密码已设置。critical 级操作将通过此密码验证身份。")


if __name__ == "__main__":
    main()

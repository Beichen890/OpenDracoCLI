"""Pipeline — 编排整条执行管线

TaskStep 风格：parse → normalize → alias_expand → platform_map → risk(pre) → exec → post → history

每步可观测，单步失败抛 DracoError，由上层捕获并发布 CommandFailed 事件。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..aliases.manager import AliasManager
from ..config import DracoConfig, get_global_config
from ..errors import DracoError
from ..events import EVT_COMMAND_EXECUTED, EVT_COMMAND_FAILED, Event, get_global_bus
from ..hooks.base import ExecContext, ExecDecision
from ..hooks.registry import HookRegistry, get_global_registry
from ..history.store import HistoryStore, get_global_store
from ..logger import get_logger
from .alias_expander import AliasExpander
from .executor import ExecResult, SubprocessExecutor
from .normalizer import normalize
from .parser import parse
from .platform_mapper import PlatformMapper

log = get_logger("shell.pipeline")


@dataclass
class PipelineResult:
    """管线执行结果（聚合 ExecResult + 元数据）"""

    success: bool
    raw_input: str
    mapped_command: str = ""
    canonical_ir: str = ""
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    alias_used: Optional[str] = None
    is_high_risk: bool = False
    error: Optional[DracoError] = None
    blocked: bool = False
    block_reason: Optional[str] = None


class ShellPipeline:
    """编排整条执行管线"""

    def __init__(
        self,
        config: DracoConfig | None = None,
        alias_manager: Optional[AliasManager] = None,
        history_store: Optional[HistoryStore] = None,
        hook_registry: Optional[HookRegistry] = None,
        executor: Optional[SubprocessExecutor] = None,
        platform_mapper: Optional[PlatformMapper] = None,
        sandbox_executor: Optional[Any] = None,
    ) -> None:
        self._config = config or get_global_config()
        self._aliases = alias_manager
        self._history = history_store
        self._hooks = hook_registry or get_global_registry()
        self._executor = executor or SubprocessExecutor(config=self._config)
        self._mapper = platform_mapper or PlatformMapper(config=self._config)
        self._expander = AliasExpander(
            manager=self._aliases, config=self._config
        )
        # P2: 沙箱执行器（可选，由 CLI 在启用风控时注入）
        self._sandbox_executor = sandbox_executor

    def set_sandbox_executor(self, sx: Any) -> None:
        """注入沙箱执行器（P2 风控启用时调用）"""
        self._sandbox_executor = sx

    def set_alias_manager(self, m: AliasManager) -> None:
        self._aliases = m
        self._expander.set_manager(m)

    async def run(
        self,
        raw_input: str,
        *,
        cwd: Optional[str] = None,
        session_id: str = "",
        timeout: Optional[float] = None,
    ) -> PipelineResult:
        """执行一次完整管线

        流程:
          1. parse       — 解析为 IR
          2. normalize   — 归一化
          3. alias_expand — 别名展开（产出抽象命令名）
          4. platform_map — 平台映射（抽象 → 原生）
          5. pre_exec    — PreExec 钩子链（可阻断/改写）
          6. execute     — subprocess 执行
          7. post_exec   — PostExec 钩子链（只读）
          8. history     — 写 SQLite
          9. event       — 发布事件
        """
        import os

        started_at = time.time()
        start_perf = time.perf_counter()
        effective_cwd = cwd or os.getcwd()
        result = PipelineResult(success=False, raw_input=raw_input)

        # --- 1. parse ---
        try:
            ir = parse(raw_input)
        except DracoError as e:
            return self._fail(result, e, started_at, session_id, effective_cwd)

        # --- 2. normalize ---
        normalize(ir)

        # --- 3. alias expand (先于平台映射) ---
        try:
            ir, alias_used = self._expander.expand(ir)
        except DracoError as e:
            return self._fail(result, e, started_at, session_id, effective_cwd)
        result.alias_used = alias_used

        # --- 4. platform map ---
        self._mapper.map(ir)

        # 序列化 IR 元数据（存历史用）
        result.canonical_ir = ir.to_json()

        # --- 5. pre_exec hooks ---
        ctx = ExecContext(
            ir=ir,
            raw_input=raw_input,
            alias_used=alias_used,
            cwd=effective_cwd,
            env=dict(os.environ),
        )
        try:
            decision, block = await self._hooks.run_pre(ctx)
        except Exception as e:
            log.exception("pre-exec hooks crashed")
            return self._fail(
                result,
                DracoError(code="draco.hook.crash", message=str(e)),
                started_at,
                session_id,
                effective_cwd,
            )

        if decision == ExecDecision.BLOCK:
            result.blocked = True
            result.block_reason = block.reason if block else "blocked"
            result.success = False
            result.duration_ms = int((time.perf_counter() - start_perf) * 1000)
            # 阻断也记录历史（exit_code=None）
            self._record(result, started_at, session_id, effective_cwd, stdout="", stderr="")
            get_global_bus().publish(
                Event(
                    type=EVT_COMMAND_FAILED,
                    payload={
                        "raw_input": raw_input,
                        "reason": result.block_reason,
                        "blocked": True,
                    },
                )
            )
            return result

        # 钩子可能改写了 ctx.ir，重新序列化
        result.canonical_ir = ctx.ir.to_json()

        # P2: 根据风控钩子标记选择 executor
        use_sandbox = ctx.metadata.get("use_sandbox", False)
        risk_level = ctx.metadata.get("risk_level", "safe")
        result.is_high_risk = risk_level in ("danger", "critical")

        executor = self._executor
        if use_sandbox and self._sandbox_executor is not None:
            executor = self._sandbox_executor
            log.info("using sandbox executor for risk_level=%s", risk_level)

        # --- 6. execute ---
        try:
            exec_result: ExecResult = await executor.execute(
                ctx.ir, cwd=effective_cwd, timeout=timeout
            )
        except DracoError as e:
            # timeout / cancelled
            result.mapped_command = ""
            return self._fail(result, e, started_at, session_id, effective_cwd)

        result.success = True
        result.mapped_command = exec_result.mapped_command
        result.exit_code = exec_result.exit_code
        result.stdout = exec_result.stdout
        result.stderr = exec_result.stderr
        result.duration_ms = exec_result.duration_ms

        # --- 7. post_exec hooks (只读) ---
        try:
            await self._hooks.run_post(ctx, exec_result)
        except Exception:
            log.exception("post-exec hooks crashed")

        # --- 8. history ---
        self._record(result, started_at, session_id, effective_cwd)

        # --- 9. event ---
        get_global_bus().publish(
            Event(
                type=EVT_COMMAND_EXECUTED,
                payload={
                    "raw_input": raw_input,
                    "mapped_command": result.mapped_command,
                    "exit_code": result.exit_code,
                    "alias_used": result.alias_used,
                    "duration_ms": result.duration_ms,
                    "session_id": session_id,
                },
            )
        )

        return result

    def _fail(
        self,
        result: PipelineResult,
        err: DracoError,
        started_at: float,
        session_id: str,
        cwd: str,
    ) -> PipelineResult:
        """管线失败统一处理：记录历史 + 发事件"""
        result.success = False
        result.error = err
        result.exit_code = None
        result.duration_ms = int((time.perf_counter() - started_at) * 1000)
        self._record(result, started_at, session_id, cwd, stdout="", stderr=err.message)
        get_global_bus().publish(
            Event(
                type=EVT_COMMAND_FAILED,
                payload={
                    "raw_input": result.raw_input,
                    "error_code": err.code,
                    "message": err.message,
                },
            )
        )
        return result

    def _record(
        self,
        result: PipelineResult,
        started_at: float,
        session_id: str,
        cwd: str,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """写入历史（失败时不抛异常，避免历史故障拖垮主流程）"""
        if self._history is None:
            return
        try:
            self._history.record(
                raw_input=result.raw_input,
                canonical_ir=result.canonical_ir,
                mapped_command=result.mapped_command,
                platform=self._config.current_platform,
                cwd=cwd,
                exit_code=result.exit_code,
                started_at=started_at,
                duration_ms=result.duration_ms,
                stdout=stdout if stdout else result.stdout,
                stderr=stderr if stderr else result.stderr,
                is_high_risk=result.is_high_risk,
                alias_used=result.alias_used,
                session_id=session_id,
            )
        except DracoError as e:
            log.error("failed to record history: %s", e)

"""P2 安全端到端集成测试 — pipeline + risk_hook + sandbox"""
import pytest

from opendracocli.aliases.manager import AliasManager
from opendracocli.config import DracoConfig
from opendracocli.events import EVT_RISK_BLOCKED, EventBus, set_global_bus
from opendracocli.hooks.registry import HookRegistry
from opendracocli.history.store import HistoryStore
from opendracocli.hooks.risk_hook import RiskAssessmentHook
from opendracocli.security.authenticator import Authenticator
from opendracocli.security.confirmer import Confirmer
from opendracocli.security.risk_assessor import RiskAssessor
from opendracocli.security.sandbox import SandboxExecutor
from opendracocli.shell.executor import SubprocessExecutor
from opendracocli.shell.pipeline import ShellPipeline


class _StubAliasManager(AliasManager):
    def __init__(self):
        self._config = DracoConfig()
        self._aliases = {}

    def _load(self): pass
    def _save(self): pass


@pytest.fixture
def secured_pipeline(tmp_path):
    """装配了风控钩子 + 沙箱的 pipeline"""
    cfg = DracoConfig(
        history_db_path=str(tmp_path / "hist.db"),
        aliases_file=str(tmp_path / "aliases.json"),
        auth_hash_file=str(tmp_path / "auth.hash"),
        security_rules_file="",
        sandbox_writable_paths=[str(tmp_path)],
    )
    aliases = _StubAliasManager()
    history = HistoryStore(config=cfg)
    hooks = HookRegistry()

    assessor = RiskAssessor(builtin_rules_path=cfg.builtin_rules_path)
    confirmer = Confirmer()
    authenticator = Authenticator(
        hash_path=tmp_path / "auth.hash", iterations=10000
    )
    risk_hook = RiskAssessmentHook(
        assessor=assessor,
        confirmer=confirmer,
        authenticator=authenticator,
        config=cfg,
    )
    hooks.register_pre(risk_hook)

    inner = SubprocessExecutor(config=cfg)
    sandbox = SandboxExecutor(
        inner=inner,
        writable_paths=cfg.sandbox_writable_paths_resolved,
    )

    pipe = ShellPipeline(
        config=cfg,
        alias_manager=aliases,
        history_store=history,
        hook_registry=hooks,
        executor=inner,
        sandbox_executor=sandbox,
    )

    bus = EventBus()
    set_global_bus(bus)

    return pipe, history, confirmer, authenticator, bus


@pytest.mark.asyncio
async def test_safe_command_no_confirmation(secured_pipeline):
    """echo 不触发任何确认"""
    pipe, _, confirmer, *_ = secured_pipeline
    confirm_calls = []
    confirmer.set_test_callback(lambda p, d: (confirm_calls.append(p), False)[1])

    result = await pipe.run("echo safe", session_id="s1")
    assert result.success
    assert result.exit_code == 0
    assert confirm_calls == []  # 没有调用确认


@pytest.mark.asyncio
async def test_caution_confirmation_yes(secured_pipeline):
    """rm file.txt → caution → yes → 执行"""
    pipe, _, confirmer, *_ = secured_pipeline
    confirmer.set_test_callback(lambda p, d: True)

    result = await pipe.run("rm nonexistent_file", session_id="s1")
    assert result.success  # 管线成功（rm 可能返回非0但管线本身没断）
    assert result.is_high_risk is False  # caution 不是高危


@pytest.mark.asyncio
async def test_caution_confirmation_no_blocks(secured_pipeline):
    """rm file.txt → caution → 即使 confirmer 返回 False 也放行，命令实际执行。

    行为变更：CAUTION 仅警告并放行（CONTINUE），不再调用 confirmer。
    """
    pipe, history, confirmer, *_ = secured_pipeline
    confirm_calls = []
    # 若 CAUTION 仍调 confirmer，会记录调用并返回 False（拒绝）
    confirmer.set_test_callback(lambda p, d: (confirm_calls.append(p), False)[1])

    result = await pipe.run("rm somefile", session_id="s1")
    assert not result.blocked  # CAUTION 不再阻断
    assert result.success  # 命令实际执行（rm 非零退出但管线本身成功）
    assert confirm_calls == []  # CAUTION 不再调用 confirmer

    # 历史记录：实际执行（exit_code 非 None）
    recs = history.recent(limit=10, session_id=None)
    assert len(recs) == 1
    assert recs[0].exit_code is not None  # 实际执行了


@pytest.mark.asyncio
async def test_danger_uses_sandbox(secured_pipeline, tmp_path):
    """rm -rf <whitelisted> → danger → yes → 沙箱执行"""
    pipe, _, confirmer, *_ = secured_pipeline
    confirmer.set_test_callback(lambda p, d: True)

    # 在白名单内创建目录再删
    target = tmp_path / "danger_test"
    target.mkdir()
    result = await pipe.run(f"rm -rf {target}", session_id="s1")
    assert result.success
    assert result.is_high_risk is True  # danger 是高危


@pytest.mark.asyncio
async def test_critical_not_configured_blocks(secured_pipeline):
    """rm -rf / → critical → 未配置密码 → 不再被身份验证阻断（放行到沙箱，由沙箱拦截）。

    行为变更：CRITICAL 未配置密码时不再 BLOCK，改为警告并放行；
    / 不在白名单 → 由沙箱拦截（blocked=True, success=False）。
    """
    pipe, _, confirmer, auth, *_ = secured_pipeline
    assert auth.is_configured() is False

    result = await pipe.run("rm -rf /", session_id="s1")
    assert result.blocked  # 由沙箱拦截（/ 不在白名单）
    assert result.success is False
    # 身份验证不再阻断：block_reason 不含密码/setup-auth
    assert "密码" not in (result.block_reason or "")
    assert "setup-auth" not in (result.block_reason or "")
    # 放行到沙箱阶段 → 沙箱拦截
    assert "沙箱拦截" in (result.block_reason or "")


@pytest.mark.asyncio
async def test_critical_correct_password_executes(secured_pipeline):
    """critical → 密码正确 → 直接执行（不再 yes 确认）。

    行为变更：CRITICAL 密码验证通过后直接 CONTINUE，不再调用 confirmer。
    用 mkfs（CRITICAL 但无写路径参数，沙箱放行）验证命令实际执行且不触发 yes：
    即便 confirmer 返回 False 也不会被阻断。
    """
    pipe, _, confirmer, auth, *_ = secured_pipeline
    auth.set_password("admin123")
    auth.set_test_callback(lambda: "admin123")
    confirm_calls = []
    # confirmer 返回 False 并记录调用：验证密码通过后不再调 yes 确认
    confirmer.set_test_callback(lambda p, d: (confirm_calls.append(p), False)[1])

    result = await pipe.run("mkfs", session_id="s1")
    # 密码正确 → 不再 yes 确认（confirmer 未被调用）
    assert confirm_calls == []
    # 直接执行，不被风控阻断
    assert not result.blocked
    assert result.success


@pytest.mark.asyncio
async def test_sandbox_blocks_write_outside_whitelist(secured_pipeline):
    """沙箱拦截写白名单外路径 → blocked=True, success=False。

    行为变更：pipeline 中沙箱违规的 PipelineResult 现在为
    success=False, blocked=True（之前管线 success=True）。
    """
    pipe, _, confirmer, *_ = secured_pipeline
    confirmer.set_test_callback(lambda p, d: True)

    # danger: rm -rf 白名单外路径 → 沙箱拦截
    result = await pipe.run("rm -rf /etc/opendracocli_test", session_id="s1")
    assert result.blocked  # 沙箱拦截
    assert result.success is False
    assert result.exit_code == -1
    assert "沙箱拦截" in (result.stderr or "")


@pytest.mark.asyncio
async def test_risk_blocked_event_published(secured_pipeline):
    """DANGER 被拒时发布 RiskBlocked 事件。

    CAUTION 不再阻断（不会发布拦截事件），改用 DANGER 命令验证事件发布。
    """
    pipe, _, confirmer, _, bus = secured_pipeline
    confirmer.set_test_callback(lambda p, d: False)
    events = []
    bus.subscribe(EVT_RISK_BLOCKED, lambda e: events.append(e))

    await pipe.run("rm -rf /tmp/test_event", session_id="s1")
    assert len(events) == 1
    assert events[0].payload["level"] == "danger"


@pytest.mark.asyncio
async def test_p1_regression_alias_still_works(secured_pipeline):
    """P1 别名功能在 P2 风控下仍正常"""
    pipe, _, confirmer, *_ = secured_pipeline
    confirmer.set_test_callback(lambda p, d: True)  # 万一触发

    pipe._aliases.add("greet", "echo hello_from_alias")
    result = await pipe.run("greet", session_id="s1")
    assert result.success
    assert "hello_from_alias" in result.stdout
    assert result.alias_used == "greet"

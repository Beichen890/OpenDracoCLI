"""risk_hook 测试"""
import pytest

from opendracocli.config import DracoConfig
from opendracocli.events import EVT_RISK_BLOCKED, EventBus, set_global_bus
from opendracocli.hooks.base import ExecContext, ExecDecision
from opendracocli.hooks.registry import HookRegistry
from opendracocli.security.authenticator import Authenticator
from opendracocli.security.confirmer import Confirmer
from opendracocli.security.risk_assessor import RiskAssessor, RiskLevel
from opendracocli.hooks.risk_hook import RiskAssessmentHook
from opendracocli.shell.ir import CommandIR, CommandNode
from opendracocli.shell.parser import parse


@pytest.fixture
def setup(tmp_path):
    """组装风控组件"""
    cfg = DracoConfig(
        auth_hash_file=str(tmp_path / "auth.hash"),
        security_rules_file="",  # 不加载用户规则
    )
    assessor = RiskAssessor(builtin_rules_path=cfg.builtin_rules_path)
    confirmer = Confirmer()
    authenticator = Authenticator(
        hash_path=tmp_path / "auth.hash", iterations=10000
    )
    bus = EventBus()
    set_global_bus(bus)
    hook = RiskAssessmentHook(
        assessor=assessor,
        confirmer=confirmer,
        authenticator=authenticator,
        config=cfg,
    )
    return hook, confirmer, authenticator, bus, assessor


def _ctx(raw: str) -> ExecContext:
    return ExecContext(ir=parse(raw), raw_input=raw)


@pytest.mark.asyncio
async def test_safe_passes_through(setup):
    hook, *_ = setup
    ctx = _ctx("echo hi")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert block is None
    assert ctx.metadata["risk_level"] == "safe"


@pytest.mark.asyncio
async def test_caution_confirmed(setup):
    hook, confirmer, *_ = setup
    confirmer.set_test_callback(lambda p, d: True)
    ctx = _ctx("rm file.txt")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert ctx.metadata["risk_level"] == "caution"
    assert not ctx.metadata.get("use_sandbox")  # caution 不用沙箱


@pytest.mark.asyncio
async def test_caution_denied(setup):
    """CAUTION 不再阻断：即使 confirmer 返回 False 也仅警告并放行（CONTINUE）。

    行为变更：CAUTION 仅警告并放行，不再调用 confirmer.ask_yes。
    """
    hook, confirmer, _, bus, _ = setup
    calls = []
    # 若 CAUTION 仍调 confirmer，这里会记录调用并返回 False（拒绝）
    confirmer.set_test_callback(lambda p, d: (calls.append(p), False)[1])
    events = []
    bus.subscribe(EVT_RISK_BLOCKED, lambda e: events.append(e))

    ctx = _ctx("rm file.txt")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert block is None
    assert ctx.metadata["risk_level"] == "caution"
    assert not ctx.metadata.get("use_sandbox")  # caution 不用沙箱
    assert calls == []  # 不再调用 confirmer
    assert len(events) == 0  # 不再发布拦截事件


@pytest.mark.asyncio
async def test_danger_confirmed_uses_sandbox(setup):
    hook, confirmer, *_ = setup
    confirmer.set_test_callback(lambda p, d: True)
    ctx = _ctx("rm -rf /tmp/test")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert ctx.metadata["risk_level"] == "danger"
    assert ctx.metadata["use_sandbox"] is True  # danger 用沙箱


@pytest.mark.asyncio
async def test_danger_denied(setup):
    hook, confirmer, *_ = setup
    confirmer.set_test_callback(lambda p, d: False)
    ctx = _ctx("rm -rf /tmp/test")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.BLOCK


@pytest.mark.asyncio
async def test_critical_not_configured_blocks(setup):
    """未配置密码 → critical 不再阻断，改为警告并放行（CONTINUE）。

    行为变更：CRITICAL 未配置密码时不再返回 BLOCK。
    """
    hook, confirmer, auth, *_ = setup
    assert auth.is_configured() is False
    ctx = _ctx("rm -rf /")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert block is None
    assert ctx.metadata["risk_level"] == "critical"
    assert ctx.metadata["use_sandbox"] is True


@pytest.mark.asyncio
async def test_critical_wrong_password_blocks(setup):
    """密码错误 → 拦截"""
    hook, confirmer, auth, *_ = setup
    auth.set_password("correct")
    auth.set_test_callback(lambda: "wrong")
    ctx = _ctx("rm -rf /")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.BLOCK
    assert "身份验证失败" in block.reason


@pytest.mark.asyncio
async def test_critical_correct_password_then_yes(setup):
    """密码正确 + yes → 放行 + 沙箱"""
    hook, confirmer, auth, *_ = setup
    auth.set_password("secret")
    auth.set_test_callback(lambda: "secret")
    confirmer.set_test_callback(lambda p, d: True)
    ctx = _ctx("rm -rf /")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert ctx.metadata["risk_level"] == "critical"
    assert ctx.metadata["use_sandbox"] is True


@pytest.mark.asyncio
async def test_critical_correct_password_then_no(setup):
    """密码正确 → 直接放行（不再冗余 yes 确认）；confirmer 返回 False 也不阻断。

    行为变更：CRITICAL 密码验证通过后直接 CONTINUE，不再调用 confirmer。
    """
    hook, confirmer, auth, *_ = setup
    auth.set_password("secret")
    auth.set_test_callback(lambda: "secret")
    # confirmer 返回 False：若密码通过后仍调 yes 确认会被拒；验证不再调用
    confirmer.set_test_callback(lambda p, d: False)
    ctx = _ctx("rm -rf /")
    decision, block = await hook.pre_exec(ctx)
    assert decision == ExecDecision.CONTINUE
    assert block is None
    assert ctx.metadata["risk_level"] == "critical"
    assert ctx.metadata["use_sandbox"] is True


@pytest.mark.asyncio
async def test_event_published_on_block(setup):
    """DANGER 被拒时发布 RiskBlocked 事件。

    CAUTION 不再阻断（不会发布拦截事件），改用 DANGER 命令验证拦截事件发布。
    """
    hook, confirmer, _, bus, _ = setup
    confirmer.set_test_callback(lambda p, d: False)
    events = []
    bus.subscribe(EVT_RISK_BLOCKED, lambda e: events.append(e))
    ctx = _ctx("rm -rf /tmp/test")
    await hook.pre_exec(ctx)
    assert len(events) == 1
    assert events[0].payload["level"] == "danger"

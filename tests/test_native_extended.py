"""Rust 内核扩展命令测试 — 系统信息/路径/文本/磁盘类

覆盖 P5 扩展的 21 个新命令:
- 系统信息: date / whoami / hostname / uname / env / printenv / true / false / which / clear
- 路径操作: dirname / basename / realpath / readlink
- 文本处理: tr / sort / uniq / tee / seq / test
- 磁盘: du
"""
from __future__ import annotations

import os

import pytest

from opendracocli.aliases.manager import AliasManager
from opendracocli.config import DracoConfig
from opendracocli.hooks.registry import HookRegistry
from opendracocli.history.store import HistoryStore
from opendracocli.shell.pipeline import ShellPipeline

pytestmark = pytest.mark.asyncio


def _have_native() -> bool:
    try:
        from opendracocli import _native  # noqa: F401

        return True
    except ImportError:
        return False


skip_no_native = pytest.mark.skipif(
    not _have_native(), reason="Rust 内核未构建（maturin develop）"
)


class _StubAliasManager(AliasManager):
    def __init__(self, aliases: dict[str, str] | None = None):
        self._config = DracoConfig()
        self._aliases = dict(aliases or {})

    def _load(self) -> None:
        pass

    def _save(self) -> None:
        pass


@pytest.fixture
def pipeline(tmp_path):
    cfg = DracoConfig(
        history_db_path=str(tmp_path / "hist.db"),
        aliases_file=str(tmp_path / "aliases.json"),
    )
    aliases = _StubAliasManager({})
    history = HistoryStore(config=cfg)
    hooks = HookRegistry()
    pipe = ShellPipeline(
        config=cfg,
        alias_manager=aliases,
        history_store=history,
        hook_registry=hooks,
    )
    return pipe, history, aliases, hooks, cfg


@pytest.fixture
def workdir(tmp_path):
    (tmp_path / "a.txt").write_text("banana\napple\ncherry\n")
    (tmp_path / "b.txt").write_text("x\nx\ny\ny\nx\n")
    (tmp_path / "nums.txt").write_text("10\n2\n1\n")
    (tmp_path / "dups.txt").write_text("b\na\nb\na\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.txt").write_text("deep\n")
    (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")
    return tmp_path


# ===== date =====


@skip_no_native
async def test_date_default(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("date", session_id="s1")
    assert r.success
    # 默认格式 YYYY-MM-DD HH:MM:SS
    assert len(r.stdout.strip()) >= 19


@skip_no_native
async def test_date_utc(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("date -u", session_id="s1")
    assert r.success
    assert "UTC" in r.stdout


@skip_no_native
async def test_date_format(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("date -u +%Y-%m-%d", session_id="s1")
    assert r.success
    # 格式 YYYY-MM-DD
    parts = r.stdout.strip().split("-")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


# ===== whoami / hostname / uname =====


@skip_no_native
async def test_whoami(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("whoami", session_id="s1")
    assert r.success
    assert r.stdout.strip() != ""


@skip_no_native
async def test_hostname(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("hostname", session_id="s1")
    assert r.success
    assert r.stdout.strip() != ""


@skip_no_native
async def test_uname_default(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("uname", session_id="s1")
    assert r.success
    assert r.stdout.strip() != ""


@skip_no_native
async def test_uname_all(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("uname -a", session_id="s1")
    assert r.success
    parts = r.stdout.strip().split()
    assert len(parts) >= 2


# ===== env / printenv =====


@skip_no_native
async def test_env_lists_vars(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("env", session_id="s1")
    assert r.success
    assert "PATH=" in r.stdout


@skip_no_native
async def test_printenv_specific(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("printenv PATH", session_id="s1")
    assert r.success
    assert r.stdout.strip() != ""


@skip_no_native
async def test_printenv_missing(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("printenv NONEXISTENT_VAR_XYZ", session_id="s1")
    assert r.exit_code == 1


# ===== true / false =====


@skip_no_native
async def test_true_returns_zero(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("true", session_id="s1")
    assert r.success
    assert r.exit_code == 0


@skip_no_native
async def test_false_returns_one(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("false", session_id="s1")
    assert r.exit_code == 1


# ===== which =====


@skip_no_native
async def test_which_finds_ls(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("which ls", session_id="s1")
    assert r.success
    assert "ls" in r.stdout


@skip_no_native
async def test_which_not_found(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("which nonexistent_cmd_xyz", session_id="s1")
    assert r.exit_code == 1


# ===== clear =====


@skip_no_native
async def test_clear_outputs_escape(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("clear", session_id="s1")
    assert r.success
    assert "\x1b[" in r.stdout


# ===== dirname / basename =====


@skip_no_native
async def test_dirname(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("dirname /a/b/c.txt", session_id="s1")
    assert r.success
    assert r.stdout.strip() == "/a/b"


@skip_no_native
async def test_dirname_single(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("dirname foo", session_id="s1")
    assert r.success
    assert r.stdout.strip() == "."


@skip_no_native
async def test_basename(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("basename /a/b/c.txt", session_id="s1")
    assert r.success
    assert r.stdout.strip() == "c.txt"


@skip_no_native
async def test_basename_suffix(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("basename /a/b/c.txt .txt", session_id="s1")
    assert r.success
    assert r.stdout.strip() == "c"


# ===== realpath =====


@skip_no_native
async def test_realpath(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("realpath a.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    assert r.stdout.strip().endswith("a.txt")


@skip_no_native
async def test_realpath_nonexistent_with_s(pipeline, tmp_path):
    """-s 不要求文件存在，仅词法规范化"""
    pipe, *_ = pipeline
    r = await pipe.run("realpath -s ../foo/./bar", session_id="s1", cwd=str(tmp_path))
    assert r.success
    assert "." not in r.stdout.strip().split("/")


# ===== readlink =====


@skip_no_native
async def test_readlink(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("readlink link.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    assert "a.txt" in r.stdout


@skip_no_native
async def test_readlink_f(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("readlink -f link.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    assert r.stdout.strip().endswith("a.txt")


# ===== tr =====


@skip_no_native
async def test_tr_uppercase(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("echo hello | tr a-z A-Z", session_id="s1")
    assert r.success
    assert "HELLO" in r.stdout


@skip_no_native
async def test_tr_delete(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("echo hello | tr -d l", session_id="s1")
    assert r.success
    assert "heo" in r.stdout


@skip_no_native
async def test_tr_squeeze(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("echo aaabbb | tr -s ab", session_id="s1")
    assert r.success
    assert "ab" in r.stdout


# ===== sort =====


@skip_no_native
async def test_sort_alpha(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("sort a.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    lines = r.stdout.strip().split("\n")
    assert lines == ["apple", "banana", "cherry"]


@skip_no_native
async def test_sort_numeric(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("sort -n nums.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    lines = r.stdout.strip().split("\n")
    assert lines == ["1", "2", "10"]


@skip_no_native
async def test_sort_reverse(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("sort -r a.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    lines = r.stdout.strip().split("\n")
    assert lines == ["cherry", "banana", "apple"]


@skip_no_native
async def test_sort_unique(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("sort -u dups.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    lines = r.stdout.strip().split("\n")
    assert lines == ["a", "b"]


# ===== uniq =====


@skip_no_native
async def test_uniq_basic(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("uniq b.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    # b.txt: x x y y x → 去重相邻后 x y x
    lines = r.stdout.strip().split("\n")
    assert lines == ["x", "y", "x"]


@skip_no_native
async def test_uniq_count(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("uniq -c b.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    assert "2" in r.stdout  # 两个 x


@skip_no_native
async def test_uniq_only_dups(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("uniq -d b.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    lines = r.stdout.strip().split("\n")
    # b.txt: x x y y x → 相邻重复的有 x 和 y
    assert "x" in lines
    assert "y" in lines


# ===== tee =====


@skip_no_native
async def test_tee_writes_file_and_stdout(pipeline, tmp_path):
    pipe, *_ = pipeline
    out_file = tmp_path / "tee_out.txt"
    r = await pipe.run(f"echo hello | tee {out_file}", session_id="s1", cwd=str(tmp_path))
    assert r.success
    assert "hello" in r.stdout
    assert out_file.exists()
    assert "hello" in out_file.read_text()


@skip_no_native
async def test_tee_append(pipeline, tmp_path):
    pipe, *_ = pipeline
    out_file = tmp_path / "tee_out.txt"
    out_file.write_text("first\n")
    r = await pipe.run(f"echo second | tee -a {out_file}", session_id="s1", cwd=str(tmp_path))
    assert r.success
    content = out_file.read_text()
    assert "first" in content
    assert "second" in content


# ===== seq =====


@skip_no_native
async def test_seq_last(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("seq 3", session_id="s1")
    assert r.success
    assert r.stdout.strip().split("\n") == ["1", "2", "3"]


@skip_no_native
async def test_seq_first_last(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("seq 2 5", session_id="s1")
    assert r.success
    assert r.stdout.strip().split("\n") == ["2", "3", "4", "5"]


@skip_no_native
async def test_seq_step(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("seq 1 2 10", session_id="s1")
    assert r.success
    assert r.stdout.strip().split("\n") == ["1", "3", "5", "7", "9"]


@skip_no_native
async def test_seq_separator(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("seq -s , 1 3", session_id="s1")
    assert r.success
    assert r.stdout.strip() == "1,2,3"


@skip_no_native
async def test_seq_descending(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run("seq 3 -1 1", session_id="s1")
    assert r.success
    assert r.stdout.strip().split("\n") == ["3", "2", "1"]


# ===== test =====


@skip_no_native
async def test_test_file_exists(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("test -e a.txt", session_id="s1", cwd=str(workdir))
    assert r.exit_code == 0


@skip_no_native
async def test_test_file_not_exists(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("test -e nonexistent", session_id="s1", cwd=str(workdir))
    assert r.exit_code == 1


@skip_no_native
async def test_test_is_dir(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("test -d sub", session_id="s1", cwd=str(workdir))
    assert r.exit_code == 0


@skip_no_native
async def test_test_is_file(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("test -f a.txt", session_id="s1", cwd=str(workdir))
    assert r.exit_code == 0


@skip_no_native
async def test_test_string_eq(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run('test abc = abc', session_id="s1")
    assert r.exit_code == 0


@skip_no_native
async def test_test_string_neq(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run('test abc != def', session_id="s1")
    assert r.exit_code == 0


@skip_no_native
async def test_test_int_lt(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run('test 3 -lt 5', session_id="s1")
    assert r.exit_code == 0


@skip_no_native
async def test_test_int_ge(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run('test 3 -ge 5', session_id="s1")
    assert r.exit_code == 1


@skip_no_native
async def test_test_z_empty(pipeline):
    pipe, *_ = pipeline
    r = await pipe.run('test -z ""', session_id="s1")
    assert r.exit_code == 0


# ===== du =====


@skip_no_native
async def test_du_directory(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("du -s sub", session_id="s1", cwd=str(workdir))
    assert r.success
    # 至少有一行总计
    assert "sub" in r.stdout


@skip_no_native
async def test_du_human(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("du -sh a.txt", session_id="s1", cwd=str(workdir))
    assert r.success
    assert "a.txt" in r.stdout


@skip_no_native
async def test_du_nonexistent(pipeline, workdir):
    pipe, *_ = pipeline
    r = await pipe.run("du nonexistent_dir", session_id="s1", cwd=str(workdir))
    assert r.exit_code != 0


# ===== 管道组合测试 =====


@skip_no_native
async def test_pipe_sort_uniq(pipeline, workdir):
    """sort dups.txt | uniq 管道链"""
    pipe, *_ = pipeline
    r = await pipe.run("sort dups.txt | uniq", session_id="s1", cwd=str(workdir))
    assert r.success
    lines = r.stdout.strip().split("\n")
    assert lines == ["a", "b"]


@skip_no_native
async def test_pipe_seq_head(pipeline):
    """seq | head 取前 N 行"""
    pipe, *_ = pipeline
    r = await pipe.run("seq 100 | head -n 5", session_id="s1")
    assert r.success
    assert r.stdout.strip().split("\n") == ["1", "2", "3", "4", "5"]


@skip_no_native
async def test_pipe_tr_wc(pipeline):
    """echo | tr | wc 管道链"""
    pipe, *_ = pipeline
    r = await pipe.run("echo hello | tr a-z A-Z | wc", session_id="s1")
    assert r.success
    parts = r.stdout.split()
    # 1 行 1 词 (HELLO) — 注意 echo 末尾有换行
    assert parts[0] == "1"


@skip_no_native
async def test_true_false_with_and(pipeline):
    """true && echo ok → 输出 ok"""
    pipe, *_ = pipeline
    r = await pipe.run("true && echo ok", session_id="s1")
    assert r.success
    assert "ok" in r.stdout


@skip_no_native
async def test_false_or_echo(pipeline):
    """false || echo fallback → 输出 fallback"""
    pipe, *_ = pipeline
    r = await pipe.run("false || echo fallback", session_id="s1")
    assert r.success
    assert "fallback" in r.stdout

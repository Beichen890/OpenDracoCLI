"""SandboxExecutor — 路径白名单沙箱

实现 Executor 协议，内部包装 SubprocessExecutor。
执行前检查 IR 中所有重定向目标 + 显式路径参数是否在可写白名单内。
违规 → 直接返回失败 ExecResult，不调 subprocess。

P2 简化版：只做路径白名单拦截（不真正 unshare/chroot）。
真正系统级沙箱留 P2.1。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from ..logger import get_logger
from ..shell.executor import ExecResult, SubprocessExecutor, serialize_ir
from ..shell.ir import CommandIR

log = get_logger("security.sandbox")


class SandboxExecutor:
    """路径白名单沙箱执行器"""

    def __init__(
        self,
        inner: SubprocessExecutor,
        writable_paths: List[Path],
    ) -> None:
        self._inner = inner
        self._writable = [p.expanduser().resolve() for p in writable_paths]
        log.debug("sandbox writable paths: %s", self._writable)

    async def execute(
        self,
        ir: CommandIR,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ExecResult:
        """执行前检查路径，通过则交给 inner executor"""
        violation = self.check(ir, cwd)
        if violation is not None:
            log.warning(violation)
            return ExecResult(
                exit_code=-1,
                stderr=violation,
                mapped_command=serialize_ir(ir),
                duration_ms=0,
            )
        # 路径检查通过，交给 inner
        return await self._inner.execute(ir, cwd=cwd, timeout=timeout)

    def check(self, ir: CommandIR, cwd: Optional[str]) -> Optional[str]:
        """检查 IR 是否违反写白名单

        Returns:
            违规错误消息；None 表示通过
        """
        for p in self._extract_write_paths(ir, cwd):
            if not self._is_writable(p):
                return (
                    f"沙箱拦截: 写入路径 {p} 不在允许范围内"
                )
        return None

    def _extract_write_paths(
        self, ir: CommandIR, cwd: Optional[str]
    ) -> List[Path]:
        """从 IR 提取所有可能被写入的路径

        来源:
          1. 重定向目标 (>, >>, 2>)
          2. 部分命令的显式路径参数（rm/rmdir/del 的路径参数）
        """
        paths: List[Path] = []
        base = Path(cwd) if cwd else Path.cwd()

        # 1. 重定向目标
        for r in ir.redirects:
            if r.kind in ("stdout", "append", "stderr"):
                paths.append(self._resolve_path(r.target, base))

        # 2. 危险命令的路径参数
        # 全量写命令（含可绕过沙箱的命令）
        write_cmds = {
            "rm", "rmdir", "del", "rd", "mv", "move", "cp", "copy",
            "truncate", "chmod", "chown", "dd",
            "mkdir", "touch", "tee", "install", "tar", "unzip", "zip",
            "sed", "awk", "perl",
        }
        # mv/cp 只需检查目标路径（最后一个参数），源路径只需读
        dest_only_cmds = {"mv", "move", "cp", "copy", "install"}
        for node in ir.nodes:
            name_lower = node.name.lower()
            if name_lower in write_cmds:
                args = [a for a in node.args if not a.startswith("-")]
                # mv/cp: 只检查最后一个参数（目标）
                if name_lower in dest_only_cmds and len(args) >= 2:
                    check_args = [args[-1]]
                else:
                    check_args = args
                for arg in check_args:
                    if arg.isdigit():
                        continue
                    paths.append(self._resolve_path(arg, base))
            # sudo/doas/pkexec + 写命令
            elif name_lower in ("sudo", "doas", "pkexec", "su"):
                for arg in node.args:
                    if arg.lower() in write_cmds:
                        # sudo 后面的写命令，检查其后续参数
                        idx = node.args.index(arg)
                        sub_args = node.args[idx + 1:]
                        check_args = [a for a in sub_args if not a.startswith("-")]
                        if arg.lower() in dest_only_cmds and len(check_args) >= 2:
                            check_args = [check_args[-1]]
                        for a in check_args:
                            if not a.isdigit():
                                paths.append(self._resolve_path(a, base))

        return paths

    @staticmethod
    def _resolve_path(p: str, base: Path) -> Path:
        """解析路径为绝对路径"""
        expanded = Path(os.path.expanduser(os.path.expandvars(p)))
        if expanded.is_absolute():
            return expanded.resolve()
        return (base / expanded).resolve()

    def _is_writable(self, path: Path) -> bool:
        """检查路径是否在白名单内

        路径在任一白名单目录下（含自身）即视为可写。
        """
        try:
            resolved = path.resolve()
        except OSError:
            return False

        for allowed in self._writable:
            try:
                # allowed 是否是 resolved 的祖先（或相等）
                resolved.relative_to(allowed)
                return True
            except ValueError:
                continue
        return False

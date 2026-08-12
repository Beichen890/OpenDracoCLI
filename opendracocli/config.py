"""OpenDracoCLI 配置

环境变量 DRACO_* 覆盖，参考 DracoDownloader config.py 的哲学。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


def _expand(p: str) -> str:
    """展开 ~ 和环境变量"""
    return os.path.expanduser(os.path.expandvars(p))


@dataclass
class DracoConfig:
    """全局配置

    所有字段支持 DRACO_<FIELD_NAME_UPPER> 环境变量覆盖。
    """

    history_db_path: str = "~/.opendracocli/history.db"
    mappings_dir: str = "mappings"  # 相对包目录
    aliases_file: str = "~/.opendracocli/aliases.json"
    stdout_summary_lines: int = 20
    stderr_summary_lines: int = 20
    exec_timeout: float = 3600.0
    max_alias_depth: int = 3
    log_level: str = "INFO"
    # Windows 用 cmd /c, Unix 用 bash -c；可被环境变量覆盖为 powershell/zsh 等
    windows_shell: str = "cmd"
    unix_shell: str = "bash"

    def __post_init__(self) -> None:
        # 环境变量覆盖
        for f in fields(self):
            env_key = f"DRACO_{f.name.upper()}"
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            self._set_from_str(f.name, raw, f.type)

    def _set_from_str(self, name: str, raw: str, type_hint: Any) -> None:
        cur = getattr(self, name)
        if isinstance(cur, bool) or type_hint is bool:
            setattr(self, name, raw.lower() in ("1", "true", "yes", "on"))
        elif isinstance(cur, int) or type_hint is int:
            setattr(self, name, int(raw))
        elif isinstance(cur, float) or type_hint is float:
            setattr(self, name, float(raw))
        else:
            setattr(self, name, raw)

    @property
    def history_db_resolved(self) -> Path:
        return Path(_expand(self.history_db_path))

    @property
    def aliases_file_resolved(self) -> Path:
        return Path(_expand(self.aliases_file))

    @property
    def mappings_dir_resolved(self) -> Path:
        """映射表目录的绝对路径（相对包目录解析）"""
        p = Path(self.mappings_dir)
        if p.is_absolute():
            return p
        # 相对包目录（mappings_dir 默认 "mappings"，即包内子目录）
        return Path(__file__).parent / p

    @property
    def current_platform(self) -> str:
        """返回 'win' | 'linux' | 'darwin'"""
        import sys

        if sys.platform.startswith("win"):
            return "win"
        if sys.platform == "darwin":
            return "darwin"
        return "linux"

    @property
    def native_shell(self) -> tuple[str, list[str]]:
        """返回当前平台原生 shell 的 (executable, prefix_args)

        用于 subprocess 调用：shell_executable + prefix + [command_str]
        """
        if self.current_platform == "win":
            shell = self.windows_shell
            if shell == "cmd":
                return ("cmd.exe", ["/c"])
            if shell == "powershell":
                return ("powershell.exe", ["-NoProfile", "-Command"])
            return (shell, ["/c"])
        # Unix-like
        shell = self.unix_shell
        if shell == "bash":
            return ("bash", ["-c"])
        if shell == "zsh":
            return ("zsh", ["-c"])
        if shell == "sh":
            return ("sh", ["-c"])
        return (shell, ["-c"])


_global_config: DracoConfig | None = None


def get_global_config() -> DracoConfig:
    """获取全局配置单例"""
    global _global_config
    if _global_config is None:
        _global_config = DracoConfig()
    return _global_config


def set_global_config(cfg: DracoConfig) -> None:
    """注入全局配置（测试用）"""
    global _global_config
    _global_config = cfg

"""PlatformMapper — 展开后命令名 → 当前平台原生命令名

查 mappings/*.json，把 IR 中每个 CommandNode 的 name 换成当前平台原生名。
未命中则原样透传。

注意：必须在 AliasExpander 之后执行（决策 1b）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from ..config import DracoConfig, get_global_config
from ..logger import get_logger
from .ir import CommandIR

log = get_logger("shell.platform_mapper")


class PlatformMapper:
    """平台命令名映射器"""

    def __init__(self, config: DracoConfig | None = None) -> None:
        self._config = config or get_global_config()
        self._unix_to_win: Dict[str, str] = {}
        self._win_to_unix: Dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        base = self._config.mappings_dir_resolved
        self._unix_to_win = self._load_table(base / "unix_to_win.json")
        self._win_to_unix = self._load_table(base / "win_to_unix.json")
        self._loaded = True
        log.debug(
            "loaded mappings: unix_to_win=%d, win_to_unix=%d",
            len(self._unix_to_win),
            len(self._win_to_unix),
        )

    @staticmethod
    def _load_table(path: Path) -> Dict[str, str]:
        if not path.exists():
            log.warning("mapping file not found: %s", path)
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 过滤 _comment 等元数据键
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except (OSError, json.JSONDecodeError) as e:
            log.error("failed to load mapping %s: %s", path, e)
            return {}

    def map(self, ir: CommandIR) -> CommandIR:
        """对 IR 中每个节点做平台映射（原地修改并返回）"""
        self._load()
        platform = self._config.current_platform
        table = self._select_table(platform)
        if not table:
            return ir

        for node in ir.nodes:
            # 注意：type nul 这种映射值含空格，需要特殊处理
            # P1 简化处理：如果映射值含空格，把第一段当 name，其余当 args 前缀
            mapped = table.get(node.name)
            if mapped is None:
                continue
            parts = mapped.split()
            if len(parts) == 1:
                node.name = parts[0]
            else:
                # type nul > file 这种，把 "type nul" 拆成 name=type, args 前缀加 nul
                node.name = parts[0]
                node.args = parts[1:] + node.args
        return ir

    def _select_table(self, platform: str) -> Dict[str, str]:
        """根据当前平台选择映射表

        win → 用 unix_to_win（把 Unix 命令转成 Windows）
        linux/darwin → 用 win_to_unix（把 Windows 命令转成 Unix）
        """
        if platform == "win":
            return self._unix_to_win
        return self._win_to_unix

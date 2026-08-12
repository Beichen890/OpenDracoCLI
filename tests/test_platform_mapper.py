"""platform_mapper 测试"""
from opendracocli.config import DracoConfig
from opendracocli.shell.ir import CommandIR, CommandNode
from opendracocli.shell.platform_mapper import PlatformMapper


class _WinConfig(DracoConfig):
    """固定为 Windows 平台的测试配置"""

    @property
    def current_platform(self) -> str:
        return "win"


class _LinuxConfig(DracoConfig):
    """固定为 Linux 平台的测试配置"""

    @property
    def current_platform(self) -> str:
        return "linux"


def test_unix_to_win_mapping():
    mapper = PlatformMapper(config=_WinConfig())

    ir = CommandIR(nodes=[CommandNode(name="ls", args=["-la"])])
    mapper.map(ir)
    assert ir.nodes[0].name == "dir"


def test_win_to_unix_mapping():
    mapper = PlatformMapper(config=_LinuxConfig())

    ir = CommandIR(nodes=[CommandNode(name="dir", args=[])])
    mapper.map(ir)
    assert ir.nodes[0].name == "ls"


def test_unmapped_passthrough():
    mapper = PlatformMapper(config=_LinuxConfig())

    ir = CommandIR(nodes=[CommandNode(name="git", args=["status"])])
    mapper.map(ir)
    # git 不在 win_to_unix 表，透传
    assert ir.nodes[0].name == "git"


def test_args_preserved_after_mapping():
    mapper = PlatformMapper(config=_WinConfig())

    ir = CommandIR(nodes=[CommandNode(name="ls", args=["-la", "/tmp"])])
    mapper.map(ir)
    assert ir.nodes[0].name == "dir"
    assert ir.nodes[0].args == ["-la", "/tmp"]


def test_multi_word_mapping_splits_name_and_args():
    """touch → 'type nul' 这种映射值含空格"""
    mapper = PlatformMapper(config=_WinConfig())

    ir = CommandIR(nodes=[CommandNode(name="touch", args=["file.txt"])])
    mapper.map(ir)
    assert ir.nodes[0].name == "type"
    assert ir.nodes[0].args == ["nul", "file.txt"]


def test_multiple_nodes_in_pipeline():
    mapper = PlatformMapper(config=_WinConfig())

    ir = CommandIR(
        nodes=[
            CommandNode(name="ls", args=["-la"]),
            CommandNode(name="grep", args=["foo"]),
        ],
        operators=["|"],
    )
    mapper.map(ir)
    assert ir.nodes[0].name == "dir"
    assert ir.nodes[1].name == "findstr"  # grep → findstr


def test_cat_to_type_on_win():
    mapper = PlatformMapper(config=_WinConfig())

    ir = CommandIR(nodes=[CommandNode(name="cat", args=["file.txt"])])
    mapper.map(ir)
    assert ir.nodes[0].name == "type"


def test_clear_to_cls_on_win():
    mapper = PlatformMapper(config=_WinConfig())

    ir = CommandIR(nodes=[CommandNode(name="clear", args=[])])
    mapper.map(ir)
    assert ir.nodes[0].name == "cls"

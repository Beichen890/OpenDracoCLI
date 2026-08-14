//! Draco 原生内核 — PyO3 绑定层
//!
//! 暴露给 Python 的扩展模块 `opendracocli._native`：
//! - execute(cmd, args, cwd, stdin) -> CommandResult  统一执行入口
//! - supported_commands() -> list[str]  内核支持的命令清单
//!
//! Rust 内部用 match 分发到 fs_cmds 的实现。
//! 命令未命中返回 exit_code=127（与 shell 一致），由上层 NativeDispatcher 决定走 Draco 函数或 exec 兜底。

use pyo3::prelude::*;

mod disk_cmds;
mod fs_cmds;
mod path_cmds;
mod sys_cmds;
mod text_cmds;

/// 命令执行结果（映射到 Python 的 opendracocli._native.CommandResult）
#[pyclass(get_all)]
struct CommandResult {
    /// 进程退出码（0 成功）
    exit_code: i32,
    /// 标准输出
    stdout: String,
    /// 标准错误
    stderr: String,
    /// cd 等命令返回的新工作目录（绝对路径）；None 表示不变
    new_cwd: Option<String>,
}

/// 统一执行入口：按命令名分发到 Rust 实现
///
/// Args:
///     cmd: 命令名（已归一化小写）
///     args: 参数列表（glob 已在 Python 侧展开）
///     cwd: 当前工作目录（绝对路径）
///     stdin: 上游管道输入（无则为 None）
///
/// Returns:
///     CommandResult；未覆盖命令 exit_code=127
#[pyfunction(signature = (cmd, args, cwd, stdin=None))]
fn execute(cmd: &str, args: Vec<String>, cwd: &str, stdin: Option<String>) -> CommandResult {
    let stdin_ref = stdin.as_deref();
    let out = match cmd {
        // --- 文件系统 ---
        "ls" => fs_cmds::ls(&args, cwd),
        "cd" => fs_cmds::cd(&args, cwd),
        "pwd" => fs_cmds::pwd(&args, cwd),
        "cat" => fs_cmds::cat(&args, cwd, stdin_ref),
        "head" => fs_cmds::head(&args, cwd, stdin_ref),
        "tail" => fs_cmds::tail(&args, cwd, stdin_ref),
        "cp" => fs_cmds::cp(&args, cwd),
        "mv" => fs_cmds::mv(&args, cwd),
        "rm" => fs_cmds::rm(&args, cwd),
        "mkdir" => fs_cmds::mkdir(&args, cwd),
        "rmdir" => fs_cmds::rmdir(&args, cwd),
        "touch" => fs_cmds::touch(&args, cwd),
        "stat" => fs_cmds::stat(&args, cwd),
        "ln" => fs_cmds::ln(&args, cwd),
        "echo" => fs_cmds::echo(&args, cwd, stdin_ref),
        "wc" => fs_cmds::wc(&args, cwd, stdin_ref),
        // --- 系统信息 ---
        "date" => sys_cmds::date(&args, cwd),
        "whoami" => sys_cmds::whoami(&args, cwd),
        "hostname" => sys_cmds::hostname(&args, cwd),
        "uname" => sys_cmds::uname(&args, cwd),
        "env" => sys_cmds::env_cmd(&args, cwd),
        "printenv" => sys_cmds::printenv(&args, cwd),
        "true" => sys_cmds::true_cmd(&args, cwd),
        "false" => sys_cmds::false_cmd(&args, cwd),
        "which" => sys_cmds::which(&args, cwd),
        "clear" => sys_cmds::clear(&args, cwd),
        // --- 路径操作 ---
        "dirname" => path_cmds::dirname(&args, cwd),
        "basename" => path_cmds::basename(&args, cwd),
        "realpath" => path_cmds::realpath(&args, cwd),
        "readlink" => path_cmds::readlink(&args, cwd),
        // --- 文本处理 ---
        "tr" => text_cmds::tr(&args, cwd, stdin_ref),
        "sort" => text_cmds::sort(&args, cwd, stdin_ref),
        "uniq" => text_cmds::uniq(&args, cwd, stdin_ref),
        "tee" => text_cmds::tee(&args, cwd, stdin_ref),
        "seq" => text_cmds::seq(&args, cwd),
        "test" => text_cmds::test_cmd(&args, cwd),
        // --- 磁盘 ---
        "du" => disk_cmds::du(&args, cwd),
        _ => {
            return CommandResult {
                exit_code: 127,
                stdout: String::new(),
                stderr: format!("draco_native: {}: 命令未在内核中实现", cmd),
                new_cwd: None,
            }
        }
    };
    CommandResult {
        exit_code: out.exit_code,
        stdout: out.stdout,
        stderr: out.stderr,
        new_cwd: out.new_cwd,
    }
}

/// 返回内核支持的命令清单（供 NativeDispatcher 判断是否走 Rust 通道）
#[pyfunction]
fn supported_commands() -> Vec<String> {
    vec![
        // 文件系统
        "ls", "cd", "pwd", "cat", "head", "tail", "cp", "mv", "rm",
        "mkdir", "rmdir", "touch", "stat", "ln", "echo", "wc",
        // 系统信息
        "date", "whoami", "hostname", "uname", "env", "printenv",
        "true", "false", "which", "clear",
        // 路径操作
        "dirname", "basename", "realpath", "readlink",
        // 文本处理
        "tr", "sort", "uniq", "tee", "seq", "test",
        // 磁盘
        "du",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}

/// Python 模块入口：opendracocli._native
#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(execute, m)?)?;
    m.add_function(wrap_pyfunction!(supported_commands, m)?)?;
    m.add_class::<CommandResult>()?;
    Ok(())
}

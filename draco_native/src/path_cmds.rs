//! 路径操作类命令（纯 Rust，不依赖 pyo3）
//!
//! 包含: dirname / basename / realpath / readlink
//! 跨平台路径处理，对齐 GNU coreutils 语义。

use std::path::Path;

use crate::fs_cmds::{CmdOut, resolve, split_args};

// ============================================================
// dirname — 提取路径的目录部分
//
// dirname /a/b/c.txt → /a/b
// dirname a/b/c      → a/b
// dirname a          → .
// dirname /          → /
// ============================================================
pub fn dirname(args: &[String], _cwd: &str) -> CmdOut {
    let (_, pos) = split_args(args);
    if pos.is_empty() {
        return CmdOut::err("dirname: 用法: dirname 路径".into());
    }
    let mut out = String::new();
    for p in &pos {
        out.push_str(&dirname_one(p));
        out.push('\n');
    }
    CmdOut::ok(out)
}

fn dirname_one(p: &str) -> String {
    if p.is_empty() {
        return ".".to_string();
    }
    // 去掉尾部所有分隔符
    let trimmed = p.trim_end_matches('/').trim_end_matches('\\');
    if trimmed.is_empty() {
        // 全是分隔符 → 根目录
        return if p.starts_with('\\') {
            "\\".to_string()
        } else {
            "/".to_string()
        };
    }
    match Path::new(trimmed).parent() {
        Some(parent) => {
            let s = parent.to_string_lossy().to_string();
            if s.is_empty() {
                ".".to_string()
            } else {
                s
            }
        }
        None => ".".to_string(),
    }
}

// ============================================================
// basename — 提取路径的文件名部分
//
// basename /a/b/c.txt       → c.txt
// basename /a/b/c.txt .txt  → c
// basename /a/b/            → b
// ============================================================
pub fn basename(args: &[String], _cwd: &str) -> CmdOut {
    let (_, pos) = split_args(args);
    if pos.is_empty() {
        return CmdOut::err("basename: 用法: basename 路径 [后缀]".into());
    }
    let path = &pos[0];
    let suffix = pos.get(1).map(|s| s.as_str()).unwrap_or("");

    let name = basename_one(path);
    let result = if !suffix.is_empty() && name.ends_with(suffix) && name != suffix {
        name[..name.len() - suffix.len()].to_string()
    } else {
        name
    };
    CmdOut::ok(format!("{}\n", result))
}

fn basename_one(p: &str) -> String {
    if p.is_empty() {
        return ".".to_string();
    }
    let trimmed = p.trim_end_matches('/').trim_end_matches('\\');
    if trimmed.is_empty() {
        return if p.starts_with('\\') {
            "\\".to_string()
        } else {
            "/".to_string()
        };
    }
    match Path::new(trimmed).file_name() {
        Some(n) => n.to_string_lossy().to_string(),
        None => trimmed.to_string(),
    }
}

// ============================================================
// realpath — 规范化绝对路径
//
// realpath 路径       规范化（文件需存在）
// realpath -s 路径   不要求存在，仅做词法规范化
// ============================================================
pub fn realpath(args: &[String], cwd: &str) -> CmdOut {
    let (flags, pos) = split_args(args);
    let no_symlink = flags.contains(&'s');
    if pos.is_empty() {
        return CmdOut::err("realpath: 用法: realpath [-s] 路径".into());
    }
    let mut out = String::new();
    for p in &pos {
        let abs = resolve(cwd, p);
        if no_symlink {
            // 词法规范化：消除 . 和 ..
            let cleaned = lexical_canonicalize(&abs);
            out.push_str(&cleaned.to_string_lossy());
            out.push('\n');
        } else {
            match std::fs::canonicalize(&abs) {
                Ok(canon) => {
                    out.push_str(&canon.to_string_lossy());
                    out.push('\n');
                }
                Err(e) => {
                    return CmdOut::err(format!("realpath: {}: {}", p, e));
                }
            }
        }
    }
    CmdOut::ok(out)
}

/// 词法规范化路径（消除 . 和 ..，不访问文件系统）
fn lexical_canonicalize(path: &Path) -> std::path::PathBuf {
    use std::path::Component;
    let mut result = std::path::PathBuf::new();
    for comp in path.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                // 只有当前结果有可弹出的普通组件时才弹出
                let last = result.components().next_back();
                match last {
                    Some(Component::Normal(_)) => {
                        result.pop();
                    }
                    Some(Component::RootDir) | None => {}
                    _ => {
                        result.pop();
                    }
                }
            }
            other => result.push(other.as_os_str()),
        }
    }
    if result.as_os_str().is_empty() {
        result.push(".");
    }
    result
}

// ============================================================
// readlink — 读取符号链接目标
//
// readlink 链接       打印链接目标（不跟随）
// readlink -f 路径    规范化到最终目标（跟随所有链接）
// ============================================================
pub fn readlink(args: &[String], cwd: &str) -> CmdOut {
    let (flags, pos) = split_args(args);
    let follow = flags.contains(&'f');
    if pos.is_empty() {
        return CmdOut::err("readlink: 用法: readlink [-f] 路径".into());
    }
    let mut out = String::new();
    for p in &pos {
        let abs = resolve(cwd, p);
        if follow {
            match std::fs::canonicalize(&abs) {
                Ok(canon) => {
                    out.push_str(&canon.to_string_lossy());
                    out.push('\n');
                }
                Err(e) => {
                    return CmdOut::err(format!("readlink: {}: {}", p, e));
                }
            }
        } else {
            match std::fs::read_link(&abs) {
                Ok(target) => {
                    out.push_str(&target.to_string_lossy());
                    out.push('\n');
                }
                Err(e) => {
                    return CmdOut::err(format!("readlink: {}: {}", p, e));
                }
            }
        }
    }
    CmdOut::ok(out)
}

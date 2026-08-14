//! 磁盘/空间类命令（纯 Rust，不依赖 pyo3）
//!
//! 包含: du
//! 递归计算目录占用空间，对齐 GNU du 常用子集。

use std::fs;
use std::path::Path;

use crate::fs_cmds::{CmdOut, human_size, resolve, split_args};

// ============================================================
// du — 估算文件/目录磁盘占用
//
// du [路径]          递归显示各子目录大小（KB）
// du -s 路径         仅显示总计
// du -h 路径         人类可读（K/M/G）
// du -a 路径         显示所有文件（不仅是目录）
// ============================================================
pub fn du(args: &[String], cwd: &str) -> CmdOut {
    let (flags, pos) = split_args(args);
    let summary = flags.contains(&'s');
    let human = flags.contains(&'h');
    let all = flags.contains(&'a');

    let targets: Vec<String> = if pos.is_empty() {
        vec![".".to_string()]
    } else {
        pos.clone()
    };

    let mut out = String::new();
    let mut total: u64 = 0;
    let mut had_err = false;

    for t in &targets {
        let path = resolve(cwd, t);
        if !path.exists() {
            out.push_str(&format!("du: {}: 没有那个文件或目录\n", t));
            had_err = true;
            continue;
        }

        let mut entries: Vec<(String, u64)> = Vec::new();
        match compute_size(&path, &mut entries, all) {
            Ok(size) => {
                total += size;
                if !summary {
                    // 输出各子目录/文件
                    for (name, sz) in &entries {
                        let s = if human {
                            human_size(*sz)
                        } else {
                            (*sz / 1024).max(1).to_string()
                        };
                        out.push_str(&format!("{:>10}\t{}\n", s, name));
                    }
                }
                // 总计
                let s = if human {
                    human_size(size)
                } else {
                    (size / 1024).max(1).to_string()
                };
                out.push_str(&format!("{:>10}\t{}\n", s, t));
            }
            Err(e) => {
                out.push_str(&format!("du: {}: {}\n", t, e));
                had_err = true;
            }
        }
    }

    if targets.len() > 1 {
        let s = if human {
            human_size(total)
        } else {
            (total / 1024).max(1).to_string()
        };
        out.push_str(&format!("{:>10}\t总计\n", s));
    }

    if had_err {
        CmdOut {
            exit_code: 1,
            stdout: out,
            stderr: String::new(),
            new_cwd: None,
        }
    } else {
        CmdOut::ok(out)
    }
}

/// 递归计算目录大小（字节），收集子目录大小到 entries
fn compute_size(
    path: &Path,
    entries: &mut Vec<(String, u64)>,
    include_files: bool,
) -> std::io::Result<u64> {
    let meta = fs::symlink_metadata(path)?;
    // 符号链接本身不计入（对齐 du 默认行为）
    if meta.file_type().is_symlink() {
        return Ok(0);
    }

    if meta.is_file() {
        return Ok(meta.len());
    }

    // 目录：递归
    let mut total = meta.len(); // 目录元数据本身
    for ent in fs::read_dir(path)? {
        let ent = ent?;
        let child = ent.path();
        let child_name = child.to_string_lossy().to_string();
        let child_size = compute_size(&child, entries, include_files)?;

        if child.is_dir() {
            entries.push((child_name.clone(), child_size));
        } else if include_files && child.is_file() {
            entries.push((child_name, child_size));
        }
        total += child_size;
    }
    Ok(total)
}

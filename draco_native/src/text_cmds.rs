//! 文本处理类命令（纯 Rust，不依赖 pyo3）
//!
//! 包含: tr / sort / uniq / tee / seq / test
//! 高频文本操作放内核，避免 subprocess 开销。

use std::fs::OpenOptions;
use std::io::Write;

use crate::fs_cmds::{CmdOut, resolve, split_args};

// ============================================================
// tr — 转换/删除字符
//
// tr SET1 SET2     将 SET1 中的字符替换为 SET2 对应字符
// tr -d SET1       删除 SET1 中的字符
// tr -s SET1       压缩 SET1 中的重复字符为单个
//
// SET 支持: a-z 范围、\n \t \\ 字面转义
// ============================================================
pub fn tr(args: &[String], _cwd: &str, stdin: Option<&str>) -> CmdOut {
    let (flags, pos) = split_args(args);
    let delete = flags.contains(&'d');
    let squeeze = flags.contains(&'s');

    let input = stdin.unwrap_or("");

    if delete {
        if pos.is_empty() {
            return CmdOut::err("tr: 用法: tr -d SET".into());
        }
        let set1 = expand_set(&pos[0]);
        let out: String = input.chars().filter(|c| !set1.contains(c)).collect();
        return CmdOut::ok(out);
    }

    if pos.len() < 2 && !squeeze {
        return CmdOut::err("tr: 用法: tr SET1 SET2".into());
    }

    if squeeze && pos.len() == 1 {
        // tr -s SET1: 仅压缩
        let set1 = expand_set(&pos[0]);
        let out = squeeze_chars(input, &set1);
        return CmdOut::ok(out);
    }

    if pos.len() < 2 {
        return CmdOut::err("tr: 用法: tr SET1 SET2".into());
    }

    let set1 = expand_set(&pos[0]);
    let set2 = expand_set(&pos[1]);

    // 构建 char → char 映射
    let mut map: Vec<(char, char)> = Vec::new();
    let last2 = *set2.last().unwrap_or(&'\0');
    for (i, &c1) in set1.iter().enumerate() {
        let c2 = if i < set2.len() { set2[i] } else { last2 };
        map.push((c1, c2));
    }

    let mut out = String::with_capacity(input.len());
    for c in input.chars() {
        let mut replaced = false;
        for &(from, to) in &map {
            if c == from {
                out.push(to);
                replaced = true;
                break;
            }
        }
        if !replaced {
            out.push(c);
        }
    }

    if squeeze {
        let squeeze_set: Vec<char> = set2.clone();
        out = squeeze_chars(&out, &squeeze_set);
    }

    CmdOut::ok(out)
}

/// 展开 SET 表达式为字符列表（支持 a-z / \n \t \\ 等）
fn expand_set(s: &str) -> Vec<char> {
    let unescaped = unescape(s);
    let mut result = Vec::new();
    let chars: Vec<char> = unescaped.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if i + 2 < chars.len() && chars[i + 1] == '-' {
            let start = chars[i] as u32;
            let end = chars[i + 2] as u32;
            if start <= end {
                for code in start..=end {
                    if let Some(c) = char::from_u32(code) {
                        result.push(c);
                    }
                }
            }
            i += 3;
        } else {
            result.push(chars[i]);
            i += 1;
        }
    }
    result
}

/// 解析转义序列 \n \t \\ \r
fn unescape(s: &str) -> String {
    let mut out = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\\' {
            match chars.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some('r') => out.push('\r'),
                Some('\\') => out.push('\\'),
                Some(other) => {
                    out.push('\\');
                    out.push(other);
                }
                None => out.push('\\'),
            }
        } else {
            out.push(c);
        }
    }
    out
}

/// 压缩 set 中的连续重复字符为单个
fn squeeze_chars(input: &str, set: &[char]) -> String {
    let mut out = String::with_capacity(input.len());
    let mut prev: Option<char> = None;
    for c in input.chars() {
        if set.contains(&c) && prev == Some(c) {
            continue;
        }
        out.push(c);
        prev = Some(c);
    }
    out
}

// ============================================================
// sort — 排序行
//
// sort         升序（字典序）
// sort -n      数值排序
// sort -r      降序
// sort -u      去重
// sort -k N    按第 N 个字段排序（空格分隔）
// ============================================================
pub fn sort(args: &[String], cwd: &str, stdin: Option<&str>) -> CmdOut {
    let (flags, pos) = split_args(args);
    let numeric = flags.contains(&'n');
    let reverse = flags.contains(&'r');
    let unique = flags.contains(&'u');
    let key = parse_key_flag(args);

    let mut lines: Vec<String> = if pos.is_empty() {
        stdin.unwrap_or("").lines().map(|l| l.to_string()).collect()
    } else {
        let mut all = Vec::new();
        for f in &pos {
            let path = resolve(cwd, f);
            match std::fs::read(&path) {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    all.extend(text.lines().map(|l| l.to_string()));
                }
                Err(e) => {
                    return CmdOut::err(format!("sort: {}: {}", f, e));
                }
            }
        }
        all
    };

    let get_key = |line: &str| -> String {
        if let Some(k) = key {
            let fields: Vec<&str> = line.split_whitespace().collect();
            if k <= fields.len() {
                fields[k - 1].to_string()
            } else {
                String::new()
            }
        } else {
            line.to_string()
        }
    };

    lines.sort_by(|a, b| {
        let ka = get_key(a);
        let kb = get_key(b);
        let ord = if numeric {
            let na: f64 = ka.trim().parse().unwrap_or(f64::NEG_INFINITY);
            let nb: f64 = kb.trim().parse().unwrap_or(f64::NEG_INFINITY);
            na.partial_cmp(&nb).unwrap_or(std::cmp::Ordering::Equal)
        } else {
            ka.cmp(&kb)
        };
        if reverse {
            ord.reverse()
        } else {
            ord
        }
    });

    if unique {
        lines.dedup_by(|a, b| get_key(a) == get_key(b));
    }

    let mut out = lines.join("\n");
    if !out.is_empty() {
        out.push('\n');
    }
    CmdOut::ok(out)
}

/// 从 -k N 参数提取字段序号（1-based）
fn parse_key_flag(args: &[String]) -> Option<usize> {
    let mut i = 0;
    while i < args.len() {
        if args[i] == "-k" && i + 1 < args.len() {
            return args[i + 1].parse::<usize>().ok();
        }
        i += 1;
    }
    None
}

// ============================================================
// uniq — 去除相邻重复行
//
// uniq          去除相邻重复
// uniq -c       前缀出现次数
// uniq -d       仅输出重复行
// uniq -u       仅输出不重复行
// ============================================================
pub fn uniq(args: &[String], cwd: &str, stdin: Option<&str>) -> CmdOut {
    let (flags, pos) = split_args(args);
    let count = flags.contains(&'c');
    let only_dups = flags.contains(&'d');
    let only_uniq = flags.contains(&'u');

    let input = if pos.is_empty() {
        stdin.unwrap_or("").to_string()
    } else {
        let path = resolve(cwd, &pos[0]);
        match std::fs::read(&path) {
            Ok(bytes) => String::from_utf8_lossy(&bytes).to_string(),
            Err(e) => return CmdOut::err(format!("uniq: {}: {}", pos[0], e)),
        }
    };

    let lines: Vec<&str> = input.lines().collect();
    let mut out = String::new();

    let mut i = 0;
    while i < lines.len() {
        let current = lines[i];
        let mut count_same = 1;
        while i + count_same < lines.len() && lines[i + count_same] == current {
            count_same += 1;
        }

        let is_dup = count_same > 1;
        let should_print = if only_dups {
            is_dup
        } else if only_uniq {
            !is_dup
        } else {
            true
        };

        if should_print {
            if count {
                out.push_str(&format!("{:>7} {}\n", count_same, current));
            } else {
                out.push_str(current);
                out.push('\n');
            }
        }
        i += count_same;
    }

    CmdOut::ok(out)
}

// ============================================================
// tee — 读 stdin 并写到文件和 stdout
//
// tee 文件       覆盖写
// tee -a 文件    追加写
// ============================================================
pub fn tee(args: &[String], _cwd: &str, stdin: Option<&str>) -> CmdOut {
    let (flags, pos) = split_args(args);
    let append = flags.contains(&'a');
    let input = stdin.unwrap_or("").to_string();

    // 写到各文件
    let mut errs = String::new();
    for f in &pos {
        let path = resolve(_cwd, f);
        let result = if append {
            OpenOptions::new().create(true).append(true).open(&path)
        } else {
            OpenOptions::new().create(true).write(true).truncate(true).open(&path)
        };
        match result {
            Ok(mut fh) => {
                if let Err(e) = fh.write_all(input.as_bytes()) {
                    errs.push_str(&format!("tee: {}: {}\n", f, e));
                }
            }
            Err(e) => {
                errs.push_str(&format!("tee: {}: {}\n", f, e));
            }
        }
    }

    if errs.is_empty() {
        CmdOut::ok(input)
    } else {
        CmdOut {
            exit_code: 1,
            stdout: input,
            stderr: errs,
            new_cwd: None,
        }
    }
}

// ============================================================
// seq — 打印数字序列
//
// seq LAST              1..LAST
// seq FIRST LAST        FIRST..LAST
// seq FIRST INCR LAST   FIRST, FIRST+INCR, ... ≤ LAST
// seq -s SEP LAST       用 SEP 分隔（默认 \n）
// ============================================================
pub fn seq(args: &[String], _cwd: &str) -> CmdOut {
    let mut sep = "\n".to_string();
    let mut nums: Vec<String> = Vec::new();

    let mut i = 0;
    while i < args.len() {
        if args[i] == "-s" && i + 1 < args.len() {
            sep = args[i + 1].clone();
            i += 2;
            continue;
        }
        nums.push(args[i].clone());
        i += 1;
    }

    if nums.is_empty() || nums.len() > 3 {
        return CmdOut::err("seq: 用法: seq [-s SEP] [FIRST [INCR]] LAST".into());
    }

    let mut parsed: Vec<f64> = Vec::new();
    for s in &nums {
        match s.parse::<f64>() {
            Ok(v) => parsed.push(v),
            Err(e) => return CmdOut::err(format!("seq: 无效数字: {}", e)),
        }
    }

    let (first, incr, last) = match parsed.len() {
        1 => (1.0, 1.0, parsed[0]),
        2 => (parsed[0], 1.0, parsed[1]),
        3 => (parsed[0], parsed[1], parsed[2]),
        _ => unreachable!(),
    };

    if incr == 0.0 {
        return CmdOut::err("seq: 增量不能为 0".into());
    }

    // 判断是否全为整数（用整数格式输出）
    let all_int = nums.iter().all(|s| {
        s.parse::<i64>().is_ok() && !s.contains('.') && !s.contains('e')
    });

    let mut values: Vec<f64> = Vec::new();
    if incr > 0.0 {
        let mut v = first;
        while v <= last + 1e-9 {
            values.push(v);
            v += incr;
        }
    } else {
        let mut v = first;
        while v >= last - 1e-9 {
            values.push(v);
            v += incr;
        }
    }

    let parts: Vec<String> = values
        .iter()
        .map(|v| {
            if all_int {
                format!("{}", *v as i64)
            } else {
                format!("{}", v)
            }
        })
        .collect();

    let mut out = parts.join(&sep);
    if !out.is_empty() {
        out.push('\n');
    }
    CmdOut::ok(out)
}

// ============================================================
// test — 条件测试（返回 exit_code: 0=true 1=false）
//
// 文件测试: -e(存在) -f(普通文件) -d(目录) -r(可读) -w(可写) -x(可执行) -s(非空)
// 字符串: -z(空) -n(非空) s1 = s2 s1 != s2
// 整数: n1 -eq n2 -ne -lt -le -gt -ge
// ============================================================
pub fn test_cmd(args: &[String], cwd: &str) -> CmdOut {
    // 去掉结尾的 ]（如果有）
    let filtered: Vec<String> = args
        .iter()
        .filter(|a| a != &"]" && a != &"[")
        .cloned()
        .collect();

    let result = eval_test(&filtered, cwd);
    let exit = if result { 0 } else { 1 };
    CmdOut {
        exit_code: exit,
        stdout: String::new(),
        stderr: String::new(),
        new_cwd: None,
    }
}

fn eval_test(args: &[String], cwd: &str) -> bool {
    match args.len() {
        0 => false,
        1 => !args[0].is_empty(),
        2 => {
            let op = &args[0];
            let val = &args[1];
            match op.as_str() {
                "-e" => resolve(cwd, val).exists(),
                "-f" => resolve(cwd, val).is_file(),
                "-d" => resolve(cwd, val).is_dir(),
                "-r" => resolve(cwd, val).metadata().map(|m| !m.permissions().readonly()).unwrap_or(false),
                "-w" => {
                    let p = resolve(cwd, val);
                    if p.exists() {
                        !p.metadata().map(|m| m.permissions().readonly()).unwrap_or(true)
                    } else {
                        // 检查父目录是否可写
                        p.parent().map(|d| !d.metadata().map(|m| m.permissions().readonly()).unwrap_or(true)).unwrap_or(false)
                    }
                }
                "-x" => {
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::PermissionsExt;
                        resolve(cwd, val).metadata().map(|m| m.permissions().mode() & 0o111 != 0).unwrap_or(false)
                    }
                    #[cfg(not(unix))]
                    {
                        resolve(cwd, val).is_file()
                    }
                }
                "-s" => resolve(cwd, val).metadata().map(|m| m.len() > 0).unwrap_or(false),
                "-z" => val.is_empty(),
                "-n" => !val.is_empty(),
                "!" => !eval_test(&args[1..], cwd),
                _ => false,
            }
        }
        3 => {
            let a = &args[0];
            let op = &args[1];
            let b = &args[2];
            match op.as_str() {
                "=" | "==" => a == b,
                "!=" => a != b,
                "-eq" => a.parse::<i64>().ok().zip(b.parse::<i64>().ok()).map(|(x, y)| x == y).unwrap_or(false),
                "-ne" => a.parse::<i64>().ok().zip(b.parse::<i64>().ok()).map(|(x, y)| x != y).unwrap_or(false),
                "-lt" => a.parse::<i64>().ok().zip(b.parse::<i64>().ok()).map(|(x, y)| x < y).unwrap_or(false),
                "-le" => a.parse::<i64>().ok().zip(b.parse::<i64>().ok()).map(|(x, y)| x <= y).unwrap_or(false),
                "-gt" => a.parse::<i64>().ok().zip(b.parse::<i64>().ok()).map(|(x, y)| x > y).unwrap_or(false),
                "-ge" => a.parse::<i64>().ok().zip(b.parse::<i64>().ok()).map(|(x, y)| x >= y).unwrap_or(false),
                _ => false,
            }
        }
        4 => {
            // ! expr
            if args[0] == "!" {
                return !eval_test(&args[1..], cwd);
            }
            false
        }
        _ => false,
    }
}

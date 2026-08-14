//! 系统信息类命令（纯 Rust，不依赖 pyo3）
//!
//! 包含: date / whoami / hostname / uname / env / printenv / true / false / which / clear
//! 跨平台：Unix 用 libc 获取 hostname/uname/本地时区；Windows 用环境变量降级。

use std::env;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::fs_cmds::{CmdOut, split_args};

// ============================================================
// date — 打印当前日期/时间
//
// 支持:
//   date           本地时间，默认格式 "YYYY-MM-DD HH:MM:SS +TZ"
//   date -u        UTC 时间
//   date +%FORMAT  自定义格式（支持 %Y %m %d %H %M %S %s %j %w %Z）
// ============================================================
pub fn date(args: &[String], _cwd: &str) -> CmdOut {
    let (flags, pos) = split_args(args);
    let utc = flags.contains(&'u');

    // 检测 +FORMAT
    let fmt = pos.iter().find(|a| a.starts_with('+')).map(|s| &s[1..]);

    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);

    // 本地时区偏移（秒）；UTC 时为 0
    let tz_offset = if utc { 0 } else { local_tz_offset() };
    let local_secs = secs + tz_offset;

    let (year, month, day, hour, min, sec, doy, wday) = unix_to_datetime(local_secs);

    let tz_label = if utc {
        "UTC".to_string()
    } else {
        tz_offset_label(tz_offset)
    };

    let out = match fmt {
        Some(f) => format_date(&f, year, month, day, hour, min, sec, doy, wday, &tz_label, secs),
        None => format!(
            "{:04}-{:02}-{:02} {:02}:{:02}:{:02} {}\n",
            year, month, day, hour, min, sec, tz_label
        ),
    };
    CmdOut::ok(out)
}

/// 本地时区偏移（秒）。Unix 用 libc::localtime_r；Windows 暂返回 0（UTC）。
fn local_tz_offset() -> i64 {
    #[cfg(unix)]
    {
        unsafe {
            let now: libc::time_t = libc::time(std::ptr::null_mut());
            let mut tm: libc::tm = std::mem::zeroed();
            if libc::localtime_r(&now, &mut tm).is_null() {
                return 0;
            }
            tm.tm_gmtoff as i64
        }
    }
    #[cfg(not(unix))]
    {
        0
    }
}

/// 时区偏移标签：+0800 / -0530 / UTC
fn tz_offset_label(offset: i64) -> String {
    if offset == 0 {
        return "UTC".to_string();
    }
    let sign = if offset >= 0 { '+' } else { '-' };
    let abs = offset.abs();
    let h = abs / 3600;
    let m = (abs % 3600) / 60;
    format!("{}{:02}{:02}", sign, h, m)
}

/// Unix 时间戳 → (年 月 日 时 分 秒 一年中第几天 星期几)
/// 星期: 0=周日 1=周一 ... 6=周六（与 POSIX tm_wday 一致）
/// 算法: Howard Hinnant 的 civil_from_days
fn unix_to_datetime(secs: i64) -> (i64, u32, u32, u32, u32, u32, u32, u32) {
    let days = secs.div_euclid(86400);
    let secs_of_day = secs.rem_euclid(86400) as u32;
    let hour = secs_of_day / 3600;
    let min = (secs_of_day % 3600) / 60;
    let sec = secs_of_day % 60;

    // 1970-01-01 是周四 → wday = (days + 4) % 7
    let wday = ((days % 7 + 4) % 7 + 7) % 7;

    // days → year/month/day
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if m <= 2 { y + 1 } else { y };

    // 一年中第几天（1-based）
    let day_of_year = doy + 1;

    (year, m as u32, d as u32, hour, min, sec, day_of_year as u32, wday as u32)
}

/// 按格式串格式化日期（支持 %Y %m %d %H %M %S %s %j %w %Z %%）
fn format_date(
    fmt: &str,
    year: i64,
    month: u32,
    day: u32,
    hour: u32,
    min: u32,
    sec: u32,
    doy: u32,
    wday: u32,
    tz: &str,
    epoch: i64,
) -> String {
    let mut out = String::new();
    let mut chars = fmt.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '%' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('Y') => out.push_str(&format!("{:04}", year)),
            Some('m') => out.push_str(&format!("{:02}", month)),
            Some('d') => out.push_str(&format!("{:02}", day)),
            Some('H') => out.push_str(&format!("{:02}", hour)),
            Some('M') => out.push_str(&format!("{:02}", min)),
            Some('S') => out.push_str(&format!("{:02}", sec)),
            Some('s') => out.push_str(&epoch.to_string()),
            Some('j') => out.push_str(&format!("{:03}", doy)),
            Some('w') => out.push_str(&wday.to_string()),
            Some('Z') => out.push_str(tz),
            Some('%') => out.push('%'),
            Some(other) => {
                out.push('%');
                out.push(other);
            }
            None => out.push('%'),
        }
    }
    out.push('\n');
    out
}

// ============================================================
// whoami — 打印当前用户名
// ============================================================
pub fn whoami(_args: &[String], _cwd: &str) -> CmdOut {
    let user = env::var("USER")
        .or_else(|_| env::var("USERNAME"))
        .or_else(|_| env::var("LOGNAME"))
        .unwrap_or_else(|_| "unknown".to_string());
    CmdOut::ok(format!("{}\n", user))
}

// ============================================================
// hostname — 打印主机名
// ============================================================
pub fn hostname(_args: &[String], _cwd: &str) -> CmdOut {
    let name = get_hostname().unwrap_or_else(|_| "unknown".to_string());
    CmdOut::ok(format!("{}\n", name))
}

fn get_hostname() -> Result<String, std::io::Error> {
    #[cfg(unix)]
    {
        use std::ffi::CStr;
        let mut buf = [0u8; 256];
        let ret = unsafe { libc::gethostname(buf.as_mut_ptr() as *mut libc::c_char, buf.len()) };
        if ret != 0 {
            return Err(std::io::Error::last_os_error());
        }
        let cstr = CStr::from_bytes_until_nul(&buf)
            .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidData, "bad hostname"))?;
        Ok(cstr.to_string_lossy().to_string())
    }
    #[cfg(not(unix))]
    {
        env::var("COMPUTERNAME")
            .or_else(|_| env::var("HOSTNAME"))
            .map_err(|_| std::io::Error::new(std::io::ErrorKind::NotFound, "no hostname env"))
    }
}

// ============================================================
// uname — 打印系统信息
//
// 支持: -s(sysname) -n(nodename) -r(release) -v(version) -m(machine) -a(all)
// ============================================================
pub fn uname(args: &[String], _cwd: &str) -> CmdOut {
    let (flags, _) = split_args(args);
    let all = flags.contains(&'a');
    let want = |c: char| all || flags.contains(&c);

    let sysname = sysname();
    let nodename = get_hostname().unwrap_or_else(|_| "unknown".to_string());
    let (release, version, machine) = platform_info();

    let mut parts: Vec<String> = Vec::new();
    if want('s') || (!all && flags.is_empty()) {
        parts.push(sysname.clone());
    }
    if all || want('n') {
        parts.push(nodename);
    }
    if all || want('r') {
        parts.push(release);
    }
    if all || want('v') {
        parts.push(version);
    }
    if all || want('m') {
        parts.push(machine);
    }

    if parts.is_empty() {
        parts.push(sysname);
    }
    CmdOut::ok(format!("{}\n", parts.join(" ")))
}

fn sysname() -> String {
    #[cfg(unix)]
    {
        "Linux".to_string()
    }
    #[cfg(windows)]
    {
        "Windows".to_string()
    }
    #[cfg(not(any(unix, windows)))]
    {
        std::env::consts::OS.to_string()
    }
}

fn platform_info() -> (String, String, String) {
    #[cfg(unix)]
    {
        unsafe {
            let mut buf: libc::utsname = std::mem::zeroed();
            if libc::uname(&mut buf) == 0 {
                let to_str = |arr: &[libc::c_char]| {
                    let s: Vec<u8> = arr
                        .iter()
                        .take_while(|&&c| c != 0)
                        .map(|&c| c as u8)
                        .collect();
                    String::from_utf8_lossy(&s).to_string()
                };
                let release = to_str(&buf.release);
                let version = to_str(&buf.version);
                let machine = to_str(&buf.machine);
                return (release, version, machine);
            }
        }
        ("unknown".to_string(), "unknown".to_string(), std::env::consts::ARCH.to_string())
    }
    #[cfg(not(unix))]
    {
        ("unknown".to_string(), "unknown".to_string(), std::env::consts::ARCH.to_string())
    }
}

// ============================================================
// env — 打印所有环境变量（按名称排序）
// ============================================================
pub fn env_cmd(_args: &[String], _cwd: &str) -> CmdOut {
    let mut vars: Vec<(String, String)> = env::vars().collect();
    vars.sort_by(|a, b| a.0.cmp(&b.0));
    let mut out = String::new();
    for (k, v) in &vars {
        out.push_str(&format!("{}={}\n", k, v));
    }
    CmdOut::ok(out)
}

// ============================================================
// printenv — 打印指定环境变量
// ============================================================
pub fn printenv(args: &[String], _cwd: &str) -> CmdOut {
    let (_, pos) = split_args(args);
    if pos.is_empty() {
        return env_cmd(args, _cwd);
    }
    let mut out = String::new();
    let mut missing = false;
    for name in &pos {
        match env::var(name) {
            Ok(v) => {
                out.push_str(&v);
                out.push('\n');
            }
            Err(_) => {
                missing = true;
            }
        }
    }
    if missing {
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

// ============================================================
// true — 总是返回成功
// ============================================================
pub fn true_cmd(_args: &[String], _cwd: &str) -> CmdOut {
    CmdOut::ok_stream()
}

// ============================================================
// false — 总是返回失败
// ============================================================
pub fn false_cmd(_args: &[String], _cwd: &str) -> CmdOut {
    CmdOut {
        exit_code: 1,
        stdout: String::new(),
        stderr: String::new(),
        new_cwd: None,
    }
}

// ============================================================
// which — 在 PATH 中查找可执行文件
// ============================================================
pub fn which(args: &[String], _cwd: &str) -> CmdOut {
    let (_, pos) = split_args(args);
    if pos.is_empty() {
        return CmdOut::err("which: 用法: which 命令 [命令...]".into());
    }
    let path_env = env::var("PATH").unwrap_or_default();
    let path_ext = env::var("PATHEXT").ok();

    let mut out = String::new();
    let mut all_found = true;
    for name in &pos {
        match find_in_path(name, &path_env, path_ext.as_deref()) {
            Some(p) => {
                out.push_str(&format!("{}\n", p.display()));
            }
            None => {
                all_found = false;
            }
        }
    }
    if !all_found {
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

/// 在 PATH 中查找可执行文件
fn find_in_path(name: &str, path_env: &str, path_ext: Option<&str>) -> Option<PathBuf> {
    let p = std::path::Path::new(name);
    // 含路径分隔符 → 直接检查
    if p.is_absolute() || name.contains('/') || name.contains('\\') {
        return if is_executable(p) {
            Some(p.to_path_buf())
        } else {
            None
        };
    }

    let exts: Vec<String> = match path_ext {
        // Windows: 尝试 PATHEXT 中的扩展名
        Some(e) if cfg!(windows) => e.split(';').map(|s| s.to_lowercase()).collect(),
        _ => vec![String::new()],
    };

    for dir in path_env.split(if cfg!(windows) { ';' } else { ':' }) {
        if dir.is_empty() {
            continue;
        }
        for ext in &exts {
            let candidate = PathBuf::from(dir).join(format!("{}{}", name, ext));
            if is_executable(&candidate) {
                return Some(candidate);
            }
        }
    }
    None
}

fn is_executable(path: &std::path::Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        match std::fs::metadata(path) {
            Ok(m) => m.is_file() && (m.permissions().mode() & 0o111 != 0),
            Err(_) => false,
        }
    }
    #[cfg(not(unix))]
    {
        std::fs::metadata(path).map(|m| m.is_file()).unwrap_or(false)
    }
}

// ============================================================
// clear — 清屏（输出 ANSI 转义序列）
// ============================================================
pub fn clear(_args: &[String], _cwd: &str) -> CmdOut {
    // \x1b[2J 清屏，\x1b[H 光标回原点
    CmdOut::ok("\x1b[2J\x1b[H".to_string())
}

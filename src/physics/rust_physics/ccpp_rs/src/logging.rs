// Rust-side wrapper around `ccpp_rs_write_log` — the bind(C) helper
// in CAM-SIMA's `ccpp_rs_logging_mod.F90`. Lets a Rust scheme emit one
// line to a host log unit (typically CAM-SIMA's `iulog`).
//
// Two log targets are supported by host convention:
//
// 1. **Host log unit** (atm.log via `iulog`). Routed via
//    `println_log(master, log_unit, msg)`. The first arg is a
//    boolean: pass the host's master flag (standard name
//    `flag_for_mpi_root`) to write only from the root MPI rank,
//    OR pass `true` to write from every rank (interleaved output is
//    the host's problem — most CAM-SIMA hosts share a single atm.log
//    so this is rarely what you want).
//
// 2. **Per-rank stdout / stderr** (for debugging from every rank).
//    Use Rust's native `println!` / `eprintln!` — Rust schemes are
//    linked into the host binary and share its stdout/stderr. No
//    host plumbing required. Each rank's output is independent.
//
//    Example:
//        eprintln!("[rank ?] rust_demo_run: T(0,0)={}", t.get(0, 0));
//
//    Note that stdout from MPI ranks is typically aggregated by the
//    job launcher (PBS / Slurm / mpirun); per-rank ordering is not
//    guaranteed.
//
// Messages longer than 1024 bytes are truncated to match CAM-SIMA's
// errmsg buffer convention.
//
// Per RUST_DESIGN.md §9 (CP-I).

use std::os::raw::{c_char, c_int};

const MAX_LOG_LEN: usize = 1024;

extern "C" {
    fn ccpp_rs_write_log(
        master_flag: bool,
        log_unit: c_int,
        buf: *const c_char,
        buf_len: c_int,
    );
}

/// Emit `msg` on the master MPI rank to `log_unit`. No-op on other
/// ranks. Messages longer than `MAX_LOG_LEN` bytes are truncated at
/// the byte boundary (UTF-8 sequences may be cut; the Fortran side
/// treats the buffer as opaque bytes up to the first NUL).
pub fn println_log(master: bool, log_unit: i32, msg: &str) {
    if !master {
        return;
    }
    // Copy into a fixed buffer, NUL-terminate, hand to Fortran.
    let bytes = msg.as_bytes();
    let n = bytes.len().min(MAX_LOG_LEN);
    let mut buf = [0u8; MAX_LOG_LEN + 1];
    buf[..n].copy_from_slice(&bytes[..n]);
    buf[n] = 0;
    unsafe {
        ccpp_rs_write_log(
            master,
            log_unit as c_int,
            buf.as_ptr() as *const c_char,
            (n + 1) as c_int,
        );
    }
}

/// `format!()`-style logging macro for the host log unit. The format
/// arguments are evaluated lazily — they only run when `$master` is
/// true — so a `log!(masterproc, log_unit, "expensive: {}", slow())`
/// in a hot loop on a non-master rank costs nothing beyond the
/// boolean check.
///
/// For per-rank debug output, use Rust's native `println!` /
/// `eprintln!` (see module docs).
#[macro_export]
macro_rules! log {
    ($master:expr, $log_unit:expr, $($arg:tt)*) => {
        if $master {
            $crate::logging::println_log(true, $log_unit, &format!($($arg)*));
        }
    };
}

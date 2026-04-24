use std::os::raw::{c_char, c_int};

/// Absolute minimum: takes one integer, returns one integer.
#[no_mangle]
pub extern "C" fn rust_ffi_sandbox_identity(x: c_int) -> c_int {
    x
}

/// Verifies c_double <-> real(c_double) on every compiler.
#[no_mangle]
pub extern "C" fn rust_ffi_sandbox_doubled(x: f64) -> f64 {
    x * 2.0
}

/// Verifies c_char buffer + explicit length convention for strings.
/// Writes "hello from rust" into the caller's buffer, NUL-terminated
/// when there is room. The Fortran side trims at the first NUL.
#[no_mangle]
pub extern "C" fn rust_ffi_sandbox_write_msg(buf: *mut c_char, buf_len: c_int) {
    if buf.is_null() || buf_len <= 0 {
        return;
    }
    let msg = b"hello from rust";
    let n = (msg.len()).min(buf_len as usize);
    unsafe {
        for i in 0..n {
            *buf.add(i) = msg[i] as c_char;
        }
        // null-terminate if room; the Fortran side copies up to null.
        if n < buf_len as usize {
            *buf.add(n) = 0;
        }
    }
}

/// Verifies logical(c_bool) handling.
#[no_mangle]
pub extern "C" fn rust_ffi_sandbox_not(x: bool) -> bool {
    !x
}

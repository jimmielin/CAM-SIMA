// rust_demo.rs -- CCPP physics scheme in Rust.
// Paired metadata: rust_demo.meta.
// No hand-written Fortran shim; capgen emits the FFI glue directly
// into the group cap.
//
// Per RUST_DESIGN.md §8.3.

use ccpp_rs::ErrmsgBuf;
use std::os::raw::{c_char, c_int};

#[no_mangle]
pub extern "C" fn rust_demo_init(
    trop_cloud_top_lev: c_int,
    pver:               c_int,
    do_shift:           bool,           // logical(c_bool), value
    top_lev:            *mut c_int,
    errmsg:             *mut c_char,
    errmsg_len:         c_int,
) -> c_int {
    if top_lev.is_null() {
        return write_err(errmsg, errmsg_len, "rust_demo: null top_lev");
    }

    // Shift the cloud physics top one layer down when requested, but
    // only if the result stays within the model column (top_lev <= pver).
    // Otherwise leave it unchanged. The conditional exists to exercise
    // the logical(c_bool) -> bool conversion path and a real integer
    // computation through capgen's generated FFI glue.
    let shift: c_int = if do_shift { 1 } else { 0 };
    let candidate = trop_cloud_top_lev + shift;
    let result = if candidate <= pver { candidate } else { trop_cloud_top_lev };
    unsafe { *top_lev = result; }

    // Success: empty errmsg, errflg = 0.
    0
}

fn write_err(buf: *mut c_char, buf_len: c_int, msg: &str) -> c_int {
    let mut b = unsafe { ErrmsgBuf::from_raw(buf, buf_len) };
    b.write(msg);
    1
}

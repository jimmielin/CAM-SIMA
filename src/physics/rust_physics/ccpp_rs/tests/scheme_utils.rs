// Unit test for ccpp_rs::constituent_index.
//
// The bind(C) façade `ccpp_scheme_constituent_index` is provided by the
// Fortran module `ccpp_scheme_utils_ccapi.F90` in production builds;
// here we stub it via a #[no_mangle] symbol so the test exercises both
// the happy path (index returned, errcode == 0) and the failure path
// (errcode != 0, errmsg propagated).

use ccpp_rs::constituent_index;
use std::os::raw::{c_char, c_int};

fn unmarshal(name: *const c_char, name_len: c_int) -> String {
    if name.is_null() || name_len <= 0 {
        return String::new();
    }
    let n = name_len as usize;
    let mut out = String::with_capacity(n);
    unsafe {
        for i in 0..n {
            let b = *name.add(i) as u8;
            if b == 0 {
                break;
            }
            out.push(b as char);
        }
    }
    out
}

fn write_errmsg(buf: *mut c_char, buf_len: c_int, msg: &str) {
    if buf.is_null() || buf_len <= 0 {
        return;
    }
    let cap = buf_len as usize;
    let bytes = msg.as_bytes();
    let n = bytes.len().min(cap.saturating_sub(1));
    unsafe {
        for i in 0..n {
            *buf.add(i) = bytes[i] as c_char;
        }
        for i in n..cap {
            *buf.add(i) = 0;
        }
    }
}

#[no_mangle]
extern "C" fn ccpp_scheme_constituent_index(
    name: *const c_char,
    name_len: c_int,
    idx_out: *mut c_int,
    errmsg: *mut c_char,
    errmsg_len: c_int,
) -> c_int {
    let n = unmarshal(name, name_len);
    match n.as_str() {
        "water_vapor" => {
            unsafe { *idx_out = 1; }
            write_errmsg(errmsg, errmsg_len, "");
            0
        }
        "ozone" => {
            unsafe { *idx_out = 3; }
            write_errmsg(errmsg, errmsg_len, "");
            0
        }
        _ => {
            unsafe { *idx_out = -99; }
            write_errmsg(
                errmsg,
                errmsg_len,
                "ccpp_constituent_index: constituent not registered",
            );
            1
        }
    }
}

#[test]
fn happy_path_returns_index() {
    let idx = constituent_index("water_vapor").expect("water_vapor should resolve");
    assert_eq!(idx, 1);
    let idx = constituent_index("ozone").expect("ozone should resolve");
    assert_eq!(idx, 3);
}

#[test]
fn failure_path_returns_err() {
    let err = constituent_index("graupel").expect_err("graupel is not registered");
    assert_eq!(err.code, 1);
    assert!(
        err.message.contains("not registered"),
        "unexpected message: {}",
        err.message
    );
}

#[test]
fn empty_name_returns_err() {
    let err = constituent_index("").expect_err("empty name is not registered");
    assert_eq!(err.code, 1);
}

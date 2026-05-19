// Rust-side wrappers around ccpp_scheme_utils free functions.
//
// Phase 2 scope: constituent index lookup by standard name. The
// underlying Fortran call is `ccpp_constituent_index`, fronted by the
// bind(C) façade `ccpp_scheme_constituent_index` in
// `ccpp_scheme_utils_ccapi.F90`.
//
// Per RUST_DESIGN.md §9 (Phase 2 extension): the lookup does not need
// an opaque host handle because the underlying Fortran module keeps a
// module-private `constituent_obj` pointer initialized at framework
// init time. Rust callers just pass a standard name and get back
// either the model's constituent index or a SchemeError.

use std::os::raw::{c_char, c_int};

use crate::error::SchemeError;

const ERRMSG_BUF_LEN: usize = 512;
const NAME_BUF_LEN: usize = 256;

/// Look up the model index of a constituent by standard name.
///
/// On success, returns `Ok(index)` where the index is the host's
/// (1-based) Fortran array position for the constituent.
///
/// On failure (name not registered, framework not initialized, etc.),
/// returns `Err(SchemeError { code, message })` carrying the errcode
/// and errmsg produced by the underlying Fortran `ccpp_constituent_index`.
pub fn constituent_index(name: &str) -> Result<i32, SchemeError> {
    // Marshal the Rust string into a NUL-padded c_char buffer. We use
    // a stack buffer of NAME_BUF_LEN bytes; standard names longer than
    // 255 chars are silently truncated, which matches the Fortran
    // façade's local `character(len=256)`.
    let mut name_buf = [0u8; NAME_BUF_LEN];
    let bytes = name.as_bytes();
    let n = bytes.len().min(NAME_BUF_LEN - 1);
    name_buf[..n].copy_from_slice(&bytes[..n]);
    // The remaining bytes are already 0 (NUL).

    let mut idx_out: c_int = 0;
    let mut errbuf = [0u8; ERRMSG_BUF_LEN];
    let errcode = unsafe {
        ccpp_scheme_constituent_index(
            name_buf.as_ptr() as *const c_char,
            n as c_int,
            &mut idx_out,
            errbuf.as_mut_ptr() as *mut c_char,
            errbuf.len() as c_int,
        )
    };

    if errcode != 0 {
        Err(SchemeError::from_buf(errcode, &errbuf))
    } else {
        Ok(idx_out as i32)
    }
}

extern "C" {
    fn ccpp_scheme_constituent_index(
        name: *const c_char,
        name_len: c_int,
        idx_out: *mut c_int,
        errmsg: *mut c_char,
        errmsg_len: c_int,
    ) -> c_int;
}

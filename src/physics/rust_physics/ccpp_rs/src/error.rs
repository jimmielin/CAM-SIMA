// Common error type for façade-backed lookups.
//
// The Fortran façade modules (ccpp_constituent_prop_ccapi,
// ccpp_scheme_utils_ccapi) return an (errcode, errmsg) pair on every
// call. SchemeError pairs them in a single Rust value so wrappers can
// expose a clean `Result<T, SchemeError>` API.
//
// Per RUST_DESIGN.md §7.6 (DDT façade error convention) and §9
// (Phase 2 extension).

use std::fmt;
use std::os::raw::c_int;

#[derive(Debug, Clone)]
pub struct SchemeError {
    pub code: i32,
    pub message: String,
}

impl SchemeError {
    pub fn new(code: i32, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// Build from a (errcode, NUL-padded byte buffer) pair returned by
    /// a bind(C) façade call. Stops at the first NUL.
    pub(crate) fn from_buf(code: c_int, buf: &[u8]) -> Self {
        let n = buf.iter().position(|&b| b == 0).unwrap_or(buf.len());
        let message = String::from_utf8_lossy(&buf[..n]).into_owned();
        Self {
            code: code as i32,
            message,
        }
    }
}

impl fmt::Display for SchemeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.message.is_empty() {
            write!(f, "SchemeError(code={})", self.code)
        } else {
            write!(f, "SchemeError(code={}, message=\"{}\")", self.code, self.message)
        }
    }
}

impl std::error::Error for SchemeError {}

// Helper for writing error messages back across the FFI boundary.
//
// Capgen-emitted caps marshal a Fortran character buffer into a (`*mut c_char`,
// `c_int`) pair. ErrmsgBuf wraps that pair so scheme code can call
// `buf.write("...")` without re-implementing length checks and NUL termination
// each time. The companion Fortran routine `ccpp_rs_unmarshal_string`
// (`ccpp_rs_marshal_mod.F90`) stops copying at the first NUL.
//
// Per RUST_DESIGN.md §8.6.

use std::os::raw::{c_char, c_int};
use std::slice;

pub struct ErrmsgBuf<'a> {
    buf: &'a mut [c_char],
}

impl<'a> ErrmsgBuf<'a> {
    /// Wrap a raw `(*mut c_char, c_int)` pair handed in from Fortran.
    ///
    /// # Safety
    /// `ptr` must be non-null and point to at least `len` writable `c_char`
    /// elements that are not aliased for the duration of the borrow.
    pub unsafe fn from_raw(ptr: *mut c_char, len: c_int) -> Self {
        let n = if len < 0 { 0 } else { len as usize };
        Self {
            buf: slice::from_raw_parts_mut(ptr, n),
        }
    }

    /// Copy `msg` into the buffer, truncating to fit, and NUL-terminate.
    ///
    /// Returns the number of message bytes actually written (excluding the
    /// trailing NUL). Subsequent bytes in the buffer are also set to NUL so
    /// that `ccpp_rs_unmarshal_string` produces a clean Fortran string even
    /// if the buffer previously held stale data.
    pub fn write(&mut self, msg: &str) -> usize {
        if self.buf.is_empty() {
            return 0;
        }
        let cap = self.buf.len() - 1;
        let bytes = msg.as_bytes();
        let n = bytes.len().min(cap);
        for i in 0..n {
            self.buf[i] = bytes[i] as c_char;
        }
        for slot in &mut self.buf[n..] {
            *slot = 0;
        }
        n
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read_until_nul(buf: &[c_char]) -> String {
        let mut s = String::new();
        for &c in buf {
            if c == 0 {
                break;
            }
            s.push(c as u8 as char);
        }
        s
    }

    #[test]
    fn writes_short_message_and_nul_terminates() {
        let mut raw = vec![0i8; 32];
        let n = unsafe {
            ErrmsgBuf::from_raw(raw.as_mut_ptr() as *mut c_char, raw.len() as c_int)
                .write("hello")
        };
        assert_eq!(n, 5);
        assert_eq!(read_until_nul(&raw), "hello");
        // The byte after the message must be NUL.
        assert_eq!(raw[5], 0);
    }

    #[test]
    fn truncates_when_message_is_too_long() {
        let mut raw = vec![0i8; 8];
        let n = unsafe {
            ErrmsgBuf::from_raw(raw.as_mut_ptr() as *mut c_char, raw.len() as c_int)
                .write("abcdefghijkl")
        };
        // 8-byte buffer reserves 1 byte for the trailing NUL -> 7 bytes copied.
        assert_eq!(n, 7);
        assert_eq!(read_until_nul(&raw), "abcdefg");
        assert_eq!(raw[7], 0);
    }

    #[test]
    fn empty_message_produces_empty_string() {
        let mut raw = vec![b'X' as c_char; 4];
        let n = unsafe {
            ErrmsgBuf::from_raw(raw.as_mut_ptr() as *mut c_char, raw.len() as c_int).write("")
        };
        assert_eq!(n, 0);
        assert_eq!(read_until_nul(&raw), "");
        // Pre-existing bytes must be cleared so unmarshal does not pick them up.
        assert!(raw.iter().all(|&c| c == 0));
    }

    #[test]
    fn zero_length_buffer_writes_nothing() {
        let mut raw: Vec<c_char> = Vec::new();
        let n = unsafe {
            ErrmsgBuf::from_raw(raw.as_mut_ptr() as *mut c_char, 0).write("anything")
        };
        assert_eq!(n, 0);
    }
}

// Safe Rust wrapper around the opaque `ccpp_constituent_prop_ptr_t`
// handle that capgen-emitted FFI glue passes through as `(c_ptr, count)`.
//
// The Fortran type-bound API lives in `ccpp_constituent_prop_mod.F90`;
// each Phase 2 getter we expose has a hand-written bind(C) façade
// function in `ccpp_constituent_prop_ccapi.F90`. Rust calls those
// façade functions via the externs declared at the bottom of this
// file.
//
// Error convention: every getter takes an out-arg `errcode: *mut c_int`
// and an `errmsg: *mut c_char` buffer in addition to the value. We map
// `errcode != 0` onto `Err(SchemeError { code, message })` so scheme
// authors can use `?` and pattern-match cleanly. Note that some
// type-bound getters (e.g. `molar_mass`) succeed (errcode == 0) but
// return a sentinel (`kphys_unassigned`, ~1.797e+308) when the
// property was never set — callers that care must test for that
// separately.
//
// Safety contract (RUST_DESIGN.md §7.6.3, load-bearing):
// - `from_raw` accepts an opaque pointer + count from Fortran.
// - `get(idx)` bounds-checks `idx < count` BEFORE any façade call,
//   so the façade's `c_f_pointer(hdl, cp, [huge(0)])` never sees an
//   out-of-range subscript. The bounds check is the load-bearing
//   guarantee against UB; do not remove it.

use std::os::raw::{c_char, c_int, c_void};

use crate::error::SchemeError;
use crate::generated::KindPhys;

const ERRMSG_BUF_LEN: usize = 512;

pub struct ConstituentProps<'a> {
    hdl: *mut c_void,
    count: usize,
    _marker: std::marker::PhantomData<&'a ()>,
}

pub struct ConstituentPropRef<'a> {
    hdl: *mut c_void,
    idx: c_int,
    _marker: std::marker::PhantomData<&'a ()>,
}

impl<'a> ConstituentProps<'a> {
    /// Wrap a raw `(*mut c_void, c_int)` pair handed in from Fortran.
    /// `count` is the number of constituents in the host's array.
    ///
    /// # Safety
    /// `hdl` must point at the head of a `type(ccpp_constituent_prop_ptr_t)`
    /// Fortran array of length `count`. The array must outlive the
    /// returned `ConstituentProps`. Negative counts are clamped to 0.
    pub unsafe fn from_raw(hdl: *mut c_void, count: c_int) -> Self {
        let count = if count < 0 { 0 } else { count as usize };
        Self {
            hdl,
            count,
            _marker: std::marker::PhantomData,
        }
    }

    /// Number of constituents in the host's array.
    pub fn len(&self) -> usize {
        self.count
    }

    /// True if the host has zero constituents.
    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// Borrow a reference to constituent `idx` (0-based). Panics if
    /// `idx >= len()` — see the safety contract at the top of this
    /// module for why the bounds check is load-bearing.
    pub fn get(&self, idx: usize) -> ConstituentPropRef<'a> {
        assert!(
            idx < self.count,
            "ConstituentProps::get: idx={} out of bounds (count={})",
            idx,
            self.count
        );
        ConstituentPropRef {
            hdl: self.hdl,
            idx: idx as c_int,
            _marker: std::marker::PhantomData,
        }
    }

    /// Iterate over every constituent in declaration order.
    pub fn iter(&self) -> impl Iterator<Item = ConstituentPropRef<'a>> + '_ {
        let hdl = self.hdl;
        (0..self.count).map(move |i| ConstituentPropRef {
            hdl,
            idx: i as c_int,
            _marker: std::marker::PhantomData,
        })
    }
}

impl<'a> ConstituentPropRef<'a> {
    /// True iff this constituent is declared as a dry-air mixing ratio.
    pub fn is_dry(&self) -> Result<bool, SchemeError> {
        let mut errcode: c_int = 0;
        let mut errbuf = [0u8; ERRMSG_BUF_LEN];
        let dry = unsafe {
            ccpp_cprop_is_dry(
                self.hdl,
                self.idx,
                &mut errcode,
                errbuf.as_mut_ptr() as *mut c_char,
                errbuf.len() as c_int,
            )
        };
        if errcode != 0 {
            Err(SchemeError::from_buf(errcode, &errbuf))
        } else {
            Ok(dry)
        }
    }

    /// Standard name of this constituent (trimmed). Returns an empty
    /// string when the Fortran side reports zero length AND succeeds;
    /// returns `Err` when the underlying lookup fails.
    pub fn standard_name(&self) -> Result<String, SchemeError> {
        const BUF_LEN: usize = 256;
        let mut buf = [0u8; BUF_LEN];
        let mut errcode: c_int = 0;
        let mut errbuf = [0u8; ERRMSG_BUF_LEN];
        let n = unsafe {
            ccpp_cprop_standard_name(
                self.hdl,
                self.idx,
                buf.as_mut_ptr() as *mut c_char,
                BUF_LEN as c_int,
                &mut errcode,
                errbuf.as_mut_ptr() as *mut c_char,
                errbuf.len() as c_int,
            )
        };
        if errcode != 0 {
            return Err(SchemeError::from_buf(errcode, &errbuf));
        }
        let n = if n < 0 { 0 } else { (n as usize).min(BUF_LEN) };
        // Bytes are ASCII in practice; lossy decode protects against
        // any stray non-UTF-8 garbage without forcing a Result up the
        // stack (scheme code rarely cares).
        Ok(String::from_utf8_lossy(&buf[..n]).into_owned())
    }

    /// Molar mass in kind_phys units. Returns whatever the Fortran
    /// type-bound getter does for "unassigned" (typically the
    /// `kphys_unassigned` sentinel ~1.797e+308) when the property has
    /// not been set — that branch still reports errcode==0 and shows
    /// up as `Ok(sentinel)`; only true failures (e.g. uninitialized
    /// underlying object) produce `Err`.
    pub fn molar_mass(&self) -> Result<KindPhys, SchemeError> {
        let mut errcode: c_int = 0;
        let mut errbuf = [0u8; ERRMSG_BUF_LEN];
        let mw = unsafe {
            ccpp_cprop_molar_mass(
                self.hdl,
                self.idx,
                &mut errcode,
                errbuf.as_mut_ptr() as *mut c_char,
                errbuf.len() as c_int,
            )
        };
        if errcode != 0 {
            Err(SchemeError::from_buf(errcode, &errbuf))
        } else {
            Ok(mw)
        }
    }
}

extern "C" {
    fn ccpp_cprop_is_dry(
        hdl: *mut c_void,
        idx: c_int,
        errcode: *mut c_int,
        errmsg: *mut c_char,
        errmsg_len: c_int,
    ) -> bool;
    fn ccpp_cprop_standard_name(
        hdl: *mut c_void,
        idx: c_int,
        buf: *mut c_char,
        buf_len: c_int,
        errcode: *mut c_int,
        errmsg: *mut c_char,
        errmsg_len: c_int,
    ) -> c_int;
    fn ccpp_cprop_molar_mass(
        hdl: *mut c_void,
        idx: c_int,
        errcode: *mut c_int,
        errmsg: *mut c_char,
        errmsg_len: c_int,
    ) -> KindPhys;
}

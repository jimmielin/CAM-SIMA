// Unit test for ccpp_rs::ConstituentProps. The 3 façade functions are
// normally provided by the Fortran-side ccpp_constituent_prop_ccapi.F90
// module; here we stub them out via #[no_mangle] symbols so the test
// runs standalone without any Fortran linkage.
//
// The stubs treat the opaque `hdl` as an index into a static fixture
// table keyed by idx, returning deterministic values. The test then
// verifies that ConstituentProps::get(idx) routes through to the
// correct stub and propagates the result back to Rust. We also
// exercise the errcode propagation path for one of the getters.

use ccpp_rs::{ConstituentProps, KindPhys};
use std::ffi::CStr;
use std::os::raw::{c_char, c_int, c_void};
use std::ptr;
use std::sync::atomic::{AtomicI32, Ordering};

struct Fixture {
    name: &'static str,
    is_dry: bool,
    molar_mass: KindPhys,
}

static FIXTURES: &[Fixture] = &[
    Fixture { name: "Q",      is_dry: false, molar_mass: 18.016 },
    Fixture { name: "CLDLIQ", is_dry: true,  molar_mass: 18.016 },
    Fixture { name: "O3",     is_dry: true,  molar_mass: 47.998 },
];

// Test-only knob: when non-zero, stubs return this as errcode along
// with a canned error message. Tests flip this before exercising the
// error path and reset it before the next test runs.
static MOLAR_MASS_ERRCODE: AtomicI32 = AtomicI32::new(0);

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
extern "C" fn ccpp_cprop_is_dry(
    _hdl: *mut c_void,
    idx: c_int,
    errcode: *mut c_int,
    errmsg: *mut c_char,
    errmsg_len: c_int,
) -> bool {
    unsafe { *errcode = 0; }
    write_errmsg(errmsg, errmsg_len, "");
    FIXTURES[idx as usize].is_dry
}

#[no_mangle]
extern "C" fn ccpp_cprop_standard_name(
    _hdl: *mut c_void,
    idx: c_int,
    buf: *mut c_char,
    buf_len: c_int,
    errcode: *mut c_int,
    errmsg: *mut c_char,
    errmsg_len: c_int,
) -> c_int {
    unsafe { *errcode = 0; }
    write_errmsg(errmsg, errmsg_len, "");
    let name = FIXTURES[idx as usize].name;
    let bytes = name.as_bytes();
    let cap = buf_len as usize;
    if cap == 0 {
        return bytes.len() as c_int;
    }
    let n = bytes.len().min(cap - 1);
    unsafe {
        for i in 0..n {
            *buf.add(i) = bytes[i] as c_char;
        }
        *buf.add(n) = 0;
    }
    n as c_int
}

#[no_mangle]
extern "C" fn ccpp_cprop_molar_mass(
    _hdl: *mut c_void,
    idx: c_int,
    errcode: *mut c_int,
    errmsg: *mut c_char,
    errmsg_len: c_int,
) -> KindPhys {
    let code = MOLAR_MASS_ERRCODE.load(Ordering::Relaxed);
    unsafe { *errcode = code; }
    if code != 0 {
        write_errmsg(errmsg, errmsg_len, "molar_mass stub: simulated failure");
        return 0.0;
    }
    write_errmsg(errmsg, errmsg_len, "");
    FIXTURES[idx as usize].molar_mass
}

#[test]
fn len_and_iter_match_fixture_count() {
    let props = unsafe { ConstituentProps::from_raw(ptr::null_mut(), 3) };
    assert_eq!(props.len(), 3);
    assert_eq!(props.iter().count(), 3);
}

#[test]
fn empty_when_count_is_zero() {
    let props = unsafe { ConstituentProps::from_raw(ptr::null_mut(), 0) };
    assert!(props.is_empty());
    assert_eq!(props.iter().count(), 0);
}

#[test]
fn getters_route_to_correct_index() {
    MOLAR_MASS_ERRCODE.store(0, Ordering::Relaxed);
    let props = unsafe { ConstituentProps::from_raw(ptr::null_mut(), 3) };
    for (i, fixture) in FIXTURES.iter().enumerate() {
        let p = props.get(i);
        assert_eq!(p.is_dry().expect("is_dry ok"), fixture.is_dry, "is_dry idx {}", i);
        assert_eq!(
            p.standard_name().expect("standard_name ok"),
            fixture.name,
            "standard_name idx {}",
            i
        );
        assert_eq!(
            p.molar_mass().expect("molar_mass ok"),
            fixture.molar_mass,
            "molar_mass idx {}",
            i
        );
    }
}

#[test]
fn molar_mass_propagates_errcode() {
    MOLAR_MASS_ERRCODE.store(7, Ordering::Relaxed);
    let props = unsafe { ConstituentProps::from_raw(ptr::null_mut(), 3) };
    let err = props.get(0).molar_mass().expect_err("should be Err");
    assert_eq!(err.code, 7);
    assert_eq!(err.message, "molar_mass stub: simulated failure");
    MOLAR_MASS_ERRCODE.store(0, Ordering::Relaxed);
}

#[test]
#[should_panic(expected = "ConstituentProps::get: idx=3 out of bounds (count=3)")]
fn get_panics_on_out_of_bounds() {
    let props = unsafe { ConstituentProps::from_raw(ptr::null_mut(), 3) };
    let _ = props.get(3);
}

#[test]
fn standard_name_uses_c_buffer_correctly() {
    // Round-trip the bytes through a CStr to confirm NUL termination
    // is honored on the Fortran side of the contract.
    let props = unsafe { ConstituentProps::from_raw(ptr::null_mut(), 3) };
    let mut buf = [0u8; 32];
    let mut errcode: c_int = 0;
    let mut errbuf = [0u8; 64];
    let n = ccpp_cprop_standard_name(
        ptr::null_mut(),
        1, // CLDLIQ
        buf.as_mut_ptr() as *mut c_char,
        buf.len() as c_int,
        &mut errcode,
        errbuf.as_mut_ptr() as *mut c_char,
        errbuf.len() as c_int,
    );
    assert_eq!(n, 6);
    assert_eq!(errcode, 0);
    let s = unsafe { CStr::from_ptr(buf.as_ptr() as *const c_char) };
    assert_eq!(s.to_str().unwrap(), "CLDLIQ");
    // Avoid unused-warning on `_ = props.get(...)`.
    let _ = props.get(1);
}

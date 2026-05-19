// rust_demo.rs -- Demo Rust CCPP physics scheme
// This demo showcases:
// 1) init and run phases
// 2) errmsg, errflg handling (via return)
// 3) 2D arrays including tendencies
// 4) constituent properties pointer
// 5) constituent index lookup (ccpp_scheme_utils equivalent)
// 6) host-side logging (write to iulog)
use ccpp_rs::{
    constituent_index, log, ConstituentProps, ErrmsgBuf, Field2D, Field3D, KindPhys,
};
use std::os::raw::{c_char, c_int, c_void};

// standard names for constituent index lookup
const NAME_WATER_VAPOR: &str =
    "water_vapor_mixing_ratio_wrt_moist_air_and_condensed_water";
const NAME_GRAUPEL: &str =
    "graupel_water_mixing_ratio_wrt_moist_air_and_condensed_water";

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
    // Otherwise leave it unchanged.
    //
    // The conditional exists to exercise
    // the logical(c_bool) -> bool conversion path and a real integer
    // computation through capgen's generated FFI glue.
    let shift: c_int = if do_shift { 1 } else { 0 };
    let candidate = trop_cloud_top_lev + shift;
    let result = if candidate <= pver { candidate } else { trop_cloud_top_lev };
    unsafe { *top_lev = result; }

    // Success: empty errmsg, errflg = 0.
    0
}

/// rust_demo_run -- Phase 2 demo. Reads air_temperature(ncol, nlev),
/// iterates the host's constituent properties array, prints a few
/// diagnostic lines to the host log on the master rank, and emits a
/// tiny constant heating tendency (1e-6 J kg-1 s-1) so the
/// downstream Fortran apply_heating_rate scheme has something to
/// apply. This is the mixed Rust-Fortran SDF demo (Phase 2, §8.4.2).
#[no_mangle]
pub extern "C" fn rust_demo_run(
    // Hoisted dims first (Phase 2 ABI cleanup): every distinct array
    // dimension is emitted once at the head of the signature. The
    // names are sourced from whatever the cap's scope already calls
    // each dim's standard_name. Here `pver` is a host scalar with
    // standard_name=vertical_layer_dimension; `ncol` and `ncnst` are
    // explicit scheme args (their standard_names have no host scalar
    // binding in CAM-SIMA, so the scheme declares them).
    pver:             c_int,           // host scalar (hoisted)
    ncol:             c_int,           // explicit scheme arg (also a dim)
    ncnst:            c_int,           // explicit scheme arg (also a dim)
    t_ptr:            *const KindPhys, // air_temperature pointer (in)
    heating_rate_ptr: *mut KindPhys,   // dry-air enthalpy tendency (out)
    q_ptr:            *const KindPhys, // ccpp_constituents pointer (in)
    cprops_hdl:       *mut c_void,     // constituent props handle (in)
    cprops_count:     c_int,
    log_unit:         c_int,
    masterproc:       bool,
    errmsg:           *mut c_char,
    errmsg_len:       c_int,
) -> c_int {
    if t_ptr.is_null() && (ncol > 0 && pver > 0) {
        return write_err(errmsg, errmsg_len, "rust_demo_run: null t with positive extents");
    }
    if heating_rate_ptr.is_null() && (ncol > 0 && pver > 0) {
        return write_err(errmsg, errmsg_len,
                         "rust_demo_run: null heating_rate with positive extents");
    }
    if q_ptr.is_null() && (ncol > 0 && pver > 0 && ncnst > 0) {
        return write_err(errmsg, errmsg_len,
                         "rust_demo_run: null q with positive extents");
    }

    // Rust-enabled capgen guarantees each array is column-major contiguous
    // and lives for the duration of this call. KindPhys matches the
    // Fortran c_kind_phys on both sides by construction (gen_rust_kinds).
    let t = unsafe { Field2D::from_raw(t_ptr as *mut KindPhys, ncol, pver) };
    let mut heating_rate = unsafe {
        Field2D::from_raw(heating_rate_ptr, ncol, pver)
    };
    let q = unsafe { Field3D::from_raw(q_ptr as *mut KindPhys, ncol, pver, ncnst) };
    let props = unsafe { ConstituentProps::from_raw(cprops_hdl, cprops_count) };

    // Emit a tiny constant heating tendency into heating_rate
    // to be applied by Fortran scheme apply_heating_rate to demonstrate
    // the Rust <-> Fortran bridge is working properly
    let tendency: KindPhys = 1.0e-6;
    for slot in heating_rate.as_slice_mut() {
        *slot = tendency;
    }

    log!(
        masterproc,
        log_unit,
        "rust_demo_run: T shape=({}, {}); T(0,0)={}; heating_rate={} J kg-1 s-1",
        t.d1(),
        t.d2(),
        if t.d1() > 0 && t.d2() > 0 { t.get(0, 0) } else { 0.0 },
        tendency
    );

    log!(
        masterproc,
        log_unit,
        "rust_demo_run: {} constituent(s)",
        props.len()
    );
    for (i, cp) in props.iter().enumerate() {
        // Each getter returns Result<T, SchemeError>; render Err inline
        // rather than failing the scheme so the demo log shows what the
        // façade reported. Real schemes typically `?`-propagate.
        let name = match cp.standard_name() {
            Ok(s) => s,
            Err(e) => format!("<err {}: {}>", e.code, e.message),
        };
        let is_dry = match cp.is_dry() {
            Ok(d) => format!("{}", d),
            Err(e) => format!("<err {}: {}>", e.code, e.message),
        };
        let molar_mass = match cp.molar_mass() {
            Ok(mw) => format!("{}", mw),
            Err(e) => format!("<err {}: {}>", e.code, e.message),
        };
        log!(
            masterproc,
            log_unit,
            "rust_demo_run:   const[{}] {} (is_dry={}, molar_mass={})",
            i,
            name,
            is_dry,
            molar_mass
        );
    }

    // Exercise ccpp_scheme_utils::ccpp_constituent_index via the Rust
    // façade. water_vapor is expected to be registered (happy path);
    // graupel is typically absent in the demo configuration (failure
    // path). Either result is logged but never raised as a scheme
    // error: both paths are explicitly part of the demonstration.
    //
    // On the happy path we also dereference the 3D ccpp_constituents
    // array at (column 0, layer 0, constituent idx_qv) to show that
    // water vapor's index can be obtained dynamically (CAM-SIMA does
    // not guarantee Q is constituent 1) and that the 3D array is
    // accessible by Rust without taking the cprops handle.
    //
    // The ccpp_constituent_index call returns a 1-based Fortran
    // index; convert to a 0-based Rust index before indexing q.
    log!(
        masterproc,
        log_unit,
        "rust_demo_run: q shape=({}, {}, {})",
        q.d1(), q.d2(), q.d3()
    );
    for name in [NAME_WATER_VAPOR, NAME_GRAUPEL] {
        match constituent_index(name) {
            Ok(idx) => {
                log!(
                    masterproc,
                    log_unit,
                    "rust_demo_run: constituent_index({}) = {}",
                    name,
                    idx
                );
                let zero_based = (idx as i64) - 1;
                if zero_based >= 0
                    && (zero_based as usize) < q.d3()
                    && q.d1() > 0
                    && q.d2() > 0
                {
                    let r = zero_based as usize;
                    log!(
                        masterproc,
                        log_unit,
                        "rust_demo_run:   q(col=0, lev=0, const={}) = {}",
                        r,
                        q.get(0, 0, r)
                    );
                }
            }
            Err(e) => log!(
                masterproc,
                log_unit,
                "rust_demo_run: constituent_index({}) failed (code={}): {}",
                name,
                e.code,
                e.message
            ),
        }
    }

    0
}

fn write_err(buf: *mut c_char, buf_len: c_int, msg: &str) -> c_int {
    let mut b = unsafe { ErrmsgBuf::from_raw(buf, buf_len) };
    b.write(msg);
    1
}

// Load-bearing column-major correctness tests for ccpp_rs::Field1D,
// Field2D, Field3D.
//
// The Fortran/Rust convention is column-major:
//   1D (d1)            -> data[i]
//   2D (d1, d2)        -> data[i + k*d1]
//   3D (d1, d2, d3)    -> data[i + k*d1 + n*d1*d2]
// Populating the buffer with a distinct stamp at each (i, k, n) and
// verifying get(...) recovers it catches every kind of dimension-swap
// or stride bug in one shot. Per RUST_DESIGN.md §7.5 + §9.1.

use ccpp_rs::{Field1D, Field2D, Field3D, KindPhys};
use std::os::raw::c_int;

fn stamp(i: usize, k: usize) -> KindPhys {
    // Deliberately asymmetric so swapping (i, k) is detectable.
    100.0 * (i as KindPhys) + (k as KindPhys)
}

fn make_buffer(d1: usize, d2: usize) -> Vec<KindPhys> {
    let mut buf = vec![0.0 as KindPhys; d1 * d2];
    for k in 0..d2 {
        for i in 0..d1 {
            // Fortran-order: index in flat buffer is i + k*d1.
            buf[i + k * d1] = stamp(i, k);
        }
    }
    buf
}

#[test]
fn round_trips_every_cell_column_major() {
    let d1 = 5usize;
    let d2 = 3usize;
    let mut buf = make_buffer(d1, d2);
    let f = unsafe { Field2D::from_raw(buf.as_mut_ptr(), d1 as c_int, d2 as c_int) };
    assert_eq!(f.d1(), d1);
    assert_eq!(f.d2(), d2);
    for k in 0..d2 {
        for i in 0..d1 {
            assert_eq!(
                f.get(i, k),
                stamp(i, k),
                "mismatch at (i={}, k={})", i, k
            );
        }
    }
}

#[test]
fn set_writes_through_to_underlying_buffer() {
    let d1 = 4usize;
    let d2 = 2usize;
    let mut buf = vec![0.0 as KindPhys; d1 * d2];
    {
        let mut f =
            unsafe { Field2D::from_raw(buf.as_mut_ptr(), d1 as c_int, d2 as c_int) };
        f.set(2, 1, 42.5);
    }
    // 2 + 1*4 = 6.
    assert_eq!(buf[6], 42.5);
    for (idx, v) in buf.iter().enumerate() {
        if idx == 6 {
            continue;
        }
        assert_eq!(*v, 0.0, "buf[{}] should be unchanged", idx);
    }
}

#[test]
fn for_each_level_iterates_in_k_order_with_d1_slices() {
    let d1 = 3usize;
    let d2 = 4usize;
    let mut buf = make_buffer(d1, d2);
    let f = unsafe { Field2D::from_raw(buf.as_mut_ptr(), d1 as c_int, d2 as c_int) };
    let mut seen_k: Vec<usize> = Vec::new();
    f.for_each_level(|k, row| {
        assert_eq!(row.len(), d1);
        for i in 0..d1 {
            assert_eq!(row[i], stamp(i, k));
        }
        seen_k.push(k);
    });
    assert_eq!(seen_k, (0..d2).collect::<Vec<_>>());
}

#[test]
fn level_borrows_contiguous_row() {
    let d1 = 6usize;
    let d2 = 2usize;
    let mut buf = make_buffer(d1, d2);
    let f = unsafe { Field2D::from_raw(buf.as_mut_ptr(), d1 as c_int, d2 as c_int) };
    let row0 = f.level(0);
    let row1 = f.level(1);
    assert_eq!(row0.len(), d1);
    assert_eq!(row1.len(), d1);
    for i in 0..d1 {
        assert_eq!(row0[i], stamp(i, 0));
        assert_eq!(row1[i], stamp(i, 1));
    }
}

#[test]
fn negative_extents_produce_empty_view() {
    let mut buf = vec![1.0 as KindPhys; 4];
    let f = unsafe { Field2D::from_raw(buf.as_mut_ptr(), -1, 4) };
    assert_eq!(f.d1(), 0);
    assert_eq!(f.d2(), 4);
}

// -- Field1D ---------------------------------------------------------------

#[test]
fn field1d_round_trips_every_cell() {
    let d1 = 7usize;
    let mut buf: Vec<KindPhys> = (0..d1).map(|i| i as KindPhys).collect();
    let f = unsafe { Field1D::from_raw(buf.as_mut_ptr(), d1 as c_int) };
    assert_eq!(f.d1(), d1);
    for i in 0..d1 {
        assert_eq!(f.get(i), i as KindPhys);
    }
}

#[test]
fn field1d_set_writes_through() {
    let mut buf = vec![0.0 as KindPhys; 4];
    {
        let mut f = unsafe { Field1D::from_raw(buf.as_mut_ptr(), 4) };
        f.set(2, 9.5);
    }
    assert_eq!(buf, vec![0.0, 0.0, 9.5, 0.0]);
}

// -- Field3D ---------------------------------------------------------------

fn stamp3(i: usize, k: usize, n: usize) -> KindPhys {
    // Distinct per (i, k, n) so dimension swaps are detectable.
    10000.0 * (n as KindPhys) + 100.0 * (i as KindPhys) + (k as KindPhys)
}

#[test]
fn field3d_round_trips_every_cell_column_major() {
    let d1 = 3usize;
    let d2 = 4usize;
    let d3 = 2usize;
    let mut buf = vec![0.0 as KindPhys; d1 * d2 * d3];
    for n in 0..d3 {
        for k in 0..d2 {
            for i in 0..d1 {
                buf[i + k * d1 + n * d1 * d2] = stamp3(i, k, n);
            }
        }
    }
    let f = unsafe {
        Field3D::from_raw(
            buf.as_mut_ptr(),
            d1 as c_int,
            d2 as c_int,
            d3 as c_int,
        )
    };
    assert_eq!((f.d1(), f.d2(), f.d3()), (d1, d2, d3));
    for n in 0..d3 {
        for k in 0..d2 {
            for i in 0..d1 {
                assert_eq!(
                    f.get(i, k, n),
                    stamp3(i, k, n),
                    "mismatch at (i={}, k={}, n={})", i, k, n
                );
            }
        }
    }
}

#[test]
fn field3d_plane_borrows_contiguous_slab() {
    let d1 = 2usize;
    let d2 = 3usize;
    let d3 = 4usize;
    let mut buf = vec![0.0 as KindPhys; d1 * d2 * d3];
    for n in 0..d3 {
        for k in 0..d2 {
            for i in 0..d1 {
                buf[i + k * d1 + n * d1 * d2] = stamp3(i, k, n);
            }
        }
    }
    let f = unsafe {
        Field3D::from_raw(
            buf.as_mut_ptr(),
            d1 as c_int,
            d2 as c_int,
            d3 as c_int,
        )
    };
    for n in 0..d3 {
        let p = f.plane(n);
        assert_eq!(p.len(), d1 * d2);
        for k in 0..d2 {
            for i in 0..d1 {
                assert_eq!(p[i + k * d1], stamp3(i, k, n));
            }
        }
    }
}

// Safe wrappers for 1D / 2D / 3D Fortran arrays of `KindPhys` passed
// across the capgen-emitted FFI boundary.
//
// Capgen emits a `(c_ptr, d1, ..., dN)` tuple per array argument; the
// pointer references the head of a Fortran-order (column-major)
// contiguous slab. `Field{1,2,3}D::from_raw` reassembles that slab
// into a safe Rust view that respects Fortran indexing convention:
//
//   1D: (i)       -> data[i]
//   2D: (i, k)    -> data[i + k*d1]                  (typical: ncol, nlev)
//   3D: (i, k, n) -> data[i + k*d1 + n*d1*d2]         (typical: ncol, nlev, ncnst)
//
// The lifetime `'a` is tied to the scheme call duration — the Fortran
// caller owns the storage; the Rust side never frees it.
//
// Per RUST_DESIGN.md §7.5 and §9.1. Column-major indexing is load-
// bearing: a swap of (i, k) would silently corrupt numerics. Test
// coverage in tests/field2d.rs exercises every cell against a stamped
// buffer so layout bugs cannot pass undetected.

use std::os::raw::c_int;
use std::slice;

use crate::generated::KindPhys;

// ---------------------------------------------------------------------------
// Field1D — typically (ncol).
// ---------------------------------------------------------------------------
pub struct Field1D<'a> {
    data: &'a mut [KindPhys],
}

impl<'a> Field1D<'a> {
    /// Wrap a raw `(*mut KindPhys, c_int)` pair from Fortran.
    ///
    /// # Safety
    /// `ptr` must reference at least `d1` contiguous `KindPhys`
    /// elements. The storage must not be aliased and must outlive
    /// the returned `Field1D`. Negative extents are clamped to zero.
    pub unsafe fn from_raw(ptr: *mut KindPhys, d1: c_int) -> Self {
        let d1 = if d1 < 0 { 0 } else { d1 as usize };
        Self {
            data: slice::from_raw_parts_mut(ptr, d1),
        }
    }

    pub fn d1(&self) -> usize {
        self.data.len()
    }

    pub fn get(&self, i: usize) -> KindPhys {
        self.data[i]
    }

    pub fn set(&mut self, i: usize, value: KindPhys) {
        self.data[i] = value;
    }

    pub fn as_slice(&self) -> &[KindPhys] {
        self.data
    }

    pub fn as_slice_mut(&mut self) -> &mut [KindPhys] {
        self.data
    }
}

// ---------------------------------------------------------------------------
// Field2D — typically (ncol, nlev) or (ncol, nlev_interface).
// ---------------------------------------------------------------------------
pub struct Field2D<'a> {
    data: &'a mut [KindPhys],
    d1: usize,
    d2: usize,
}

impl<'a> Field2D<'a> {
    /// Wrap a raw `(*mut KindPhys, c_int, c_int)` triple from Fortran.
    /// `d1` is the fast (first / horizontal) dimension, `d2` is the
    /// slow (second / vertical) dimension.
    ///
    /// # Safety
    /// `ptr` must reference at least `d1 * d2` contiguous `KindPhys`
    /// elements laid out in Fortran (column-major) order. The storage
    /// must not be aliased and must outlive the returned `Field2D`.
    /// Negative extents are clamped to zero.
    pub unsafe fn from_raw(ptr: *mut KindPhys, d1: c_int, d2: c_int) -> Self {
        let d1 = if d1 < 0 { 0 } else { d1 as usize };
        let d2 = if d2 < 0 { 0 } else { d2 as usize };
        let n = d1.checked_mul(d2).unwrap_or(0);
        Self {
            data: slice::from_raw_parts_mut(ptr, n),
            d1,
            d2,
        }
    }

    pub fn d1(&self) -> usize {
        self.d1
    }

    pub fn d2(&self) -> usize {
        self.d2
    }

    fn linear(&self, i: usize, k: usize) -> usize {
        debug_assert!(i < self.d1, "i={} out of bounds (d1={})", i, self.d1);
        debug_assert!(k < self.d2, "k={} out of bounds (d2={})", k, self.d2);
        i + k * self.d1
    }

    pub fn get(&self, i: usize, k: usize) -> KindPhys {
        self.data[self.linear(i, k)]
    }

    pub fn set(&mut self, i: usize, k: usize, value: KindPhys) {
        let idx = self.linear(i, k);
        self.data[idx] = value;
    }

    pub fn as_slice_mut(&mut self) -> &mut [KindPhys] {
        self.data
    }

    pub fn level(&self, k: usize) -> &[KindPhys] {
        assert!(k < self.d2, "k={} out of bounds (d2={})", k, self.d2);
        let start = k * self.d1;
        &self.data[start..start + self.d1]
    }

    pub fn level_mut(&mut self, k: usize) -> &mut [KindPhys] {
        assert!(k < self.d2, "k={} out of bounds (d2={})", k, self.d2);
        let start = k * self.d1;
        &mut self.data[start..start + self.d1]
    }

    pub fn for_each_level<F: FnMut(usize, &[KindPhys])>(&self, mut f: F) {
        for k in 0..self.d2 {
            let start = k * self.d1;
            f(k, &self.data[start..start + self.d1]);
        }
    }
}

// ---------------------------------------------------------------------------
// Field3D — typically (ncol, nlev, ncnst).
// ---------------------------------------------------------------------------
pub struct Field3D<'a> {
    data: &'a mut [KindPhys],
    d1: usize,
    d2: usize,
    d3: usize,
    plane: usize,   // d1 * d2, cached
}

impl<'a> Field3D<'a> {
    /// Wrap a raw `(*mut KindPhys, c_int, c_int, c_int)` from Fortran.
    /// `d1` fast, `d2` middle, `d3` slow.
    ///
    /// # Safety
    /// `ptr` must reference at least `d1 * d2 * d3` contiguous
    /// `KindPhys` elements in Fortran (column-major) order. Storage
    /// must not be aliased and must outlive the returned `Field3D`.
    /// Negative extents are clamped to zero.
    pub unsafe fn from_raw(
        ptr: *mut KindPhys,
        d1: c_int,
        d2: c_int,
        d3: c_int,
    ) -> Self {
        let d1 = if d1 < 0 { 0 } else { d1 as usize };
        let d2 = if d2 < 0 { 0 } else { d2 as usize };
        let d3 = if d3 < 0 { 0 } else { d3 as usize };
        let plane = d1.checked_mul(d2).unwrap_or(0);
        let n = plane.checked_mul(d3).unwrap_or(0);
        Self {
            data: slice::from_raw_parts_mut(ptr, n),
            d1,
            d2,
            d3,
            plane,
        }
    }

    pub fn d1(&self) -> usize {
        self.d1
    }

    pub fn d2(&self) -> usize {
        self.d2
    }

    pub fn d3(&self) -> usize {
        self.d3
    }

    fn linear(&self, i: usize, k: usize, n: usize) -> usize {
        debug_assert!(i < self.d1, "i={} out of bounds (d1={})", i, self.d1);
        debug_assert!(k < self.d2, "k={} out of bounds (d2={})", k, self.d2);
        debug_assert!(n < self.d3, "n={} out of bounds (d3={})", n, self.d3);
        i + k * self.d1 + n * self.plane
    }

    pub fn get(&self, i: usize, k: usize, n: usize) -> KindPhys {
        self.data[self.linear(i, k, n)]
    }

    pub fn set(&mut self, i: usize, k: usize, n: usize, value: KindPhys) {
        let idx = self.linear(i, k, n);
        self.data[idx] = value;
    }

    pub fn as_slice_mut(&mut self) -> &mut [KindPhys] {
        self.data
    }

    /// Borrow the (d1 x d2) plane at constituent index `n` as a flat
    /// slice in column-major order. Length is `d1 * d2`.
    pub fn plane(&self, n: usize) -> &[KindPhys] {
        assert!(n < self.d3, "n={} out of bounds (d3={})", n, self.d3);
        let start = n * self.plane;
        &self.data[start..start + self.plane]
    }

    pub fn plane_mut(&mut self, n: usize) -> &mut [KindPhys] {
        assert!(n < self.d3, "n={} out of bounds (d3={})", n, self.d3);
        let start = n * self.plane;
        &mut self.data[start..start + self.plane]
    }
}

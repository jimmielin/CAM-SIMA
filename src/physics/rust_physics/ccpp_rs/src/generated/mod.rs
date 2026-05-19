// Wire the build-generated kind.rs into the crate. The file itself is
// emitted by cime_config/gen_rust_kinds.py (or, for standalone cargo
// test, by build.rs as a default-f64 fallback). Per RUST_DESIGN.md §7.2.

pub mod kind;

pub use kind::KindPhys;

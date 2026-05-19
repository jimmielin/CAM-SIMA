// ccpp_rs: support crate for Rust CCPP schemes.
//
// Public surface re-exports the modules a Rust scheme needs to interoperate
// with capgen-emitted bind(C) glue. Per RUST_DESIGN.md §8.6 and §9 (Phase 2).

pub mod constituent;
pub mod errmsg;
pub mod error;
pub mod field2d;
pub mod generated;
pub mod logging;
pub mod scheme_utils;

pub use constituent::{ConstituentPropRef, ConstituentProps};
pub use errmsg::ErrmsgBuf;
pub use error::SchemeError;
pub use field2d::{Field1D, Field2D, Field3D};
pub use generated::KindPhys;
pub use logging::println_log;
pub use scheme_utils::constituent_index;

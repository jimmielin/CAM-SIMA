// ccpp_rs: support crate for Rust CCPP schemes.
//
// Public surface re-exports the modules a Rust scheme needs to interoperate
// with capgen-emitted bind(C) glue. Per RUST_DESIGN.md §8.6.

pub mod errmsg;

pub use errmsg::ErrmsgBuf;

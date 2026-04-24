# pfUnit unit tests for ccpp_rs_marshal_mod.
#
# The module under test lives in the ccpp_framework submodule
# (ccpp-framework/src/ccpp_rs_marshal_mod.F90). It is the Fortran
# half of the string FFI contract used by every capgen-emitted Rust
# scheme cap, per RUST_DESIGN.md §7.4.
#
# The framework's own CMake build pulls this file into the
# ccpp_framework static library, but linking that library here would
# also drag in MPI / OpenMP from ccpp_types.F90 — overkill for a
# pure-Fortran helper. Instead we compile just the one source file
# into a small object library local to this test.

set(MARSHAL_SRC
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../ccpp_framework/src/ccpp_rs_marshal_mod.F90)

add_library(ccpp_rs_marshal STATIC ${MARSHAL_SRC})
set_target_properties(ccpp_rs_marshal PROPERTIES
    Fortran_MODULE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/mod)

add_pfunit_ctest(ccpp_rs_marshal_tests
                 TEST_SOURCES test_ccpp_rs_marshal.pf
                 LINK_LIBRARIES ccpp_rs_marshal OpenMP::OpenMP_Fortran)
target_include_directories(ccpp_rs_marshal_tests PRIVATE
    ${CMAKE_CURRENT_BINARY_DIR}/mod)

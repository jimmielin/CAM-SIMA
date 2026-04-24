find_program(CARGO_EXECUTABLE cargo
             HINTS $ENV{HOME}/.cargo/bin
             REQUIRED)

set(RUST_LIB_DIR ${CMAKE_CURRENT_BINARY_DIR}/rust_target)
set(RUST_LIB_PATH ${RUST_LIB_DIR}/release/librust_ffi_sandbox.a)

add_custom_command(
  OUTPUT ${RUST_LIB_PATH}
  COMMAND ${CARGO_EXECUTABLE} build --release
          --manifest-path ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml
          --target-dir ${RUST_LIB_DIR}
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/lib.rs
          ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml
  COMMENT "Building Rust FFI sandbox staticlib"
)
add_custom_target(rust_ffi_sandbox_build DEPENDS ${RUST_LIB_PATH})

# Capture the required native libs via --print native-static-libs
execute_process(
  COMMAND ${CARGO_EXECUTABLE} rustc --release
          --manifest-path ${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml
          --target-dir ${RUST_LIB_DIR}
          -- --print native-static-libs
  OUTPUT_VARIABLE RUST_NATIVE_LIBS_OUT
  ERROR_VARIABLE  RUST_NATIVE_LIBS_ERR
)
string(REGEX MATCH "native-static-libs:([^\n]*)" _match "${RUST_NATIVE_LIBS_ERR}")
set(RUST_NATIVE_LIBS "${CMAKE_MATCH_1}")
separate_arguments(RUST_NATIVE_LIBS)

add_pfunit_ctest(test_rust_ffi_sandbox
  TEST_SOURCES test_rust_ffi.pf
  LINK_LIBRARIES ${RUST_LIB_PATH} ${RUST_NATIVE_LIBS}
)
add_dependencies(test_rust_ffi_sandbox rust_ffi_sandbox_build)

# Rust FFI Sandbox — Phase 0 Notes

This file is the Phase 0 deliverable per RUST_DESIGN §6.8. It captures the
exact toolchain versions, link-time native library list, and any
compiler/platform quirks observed while bringing the sandbox up.

The sandbox is permanent (RUST_DESIGN D8): it remains in the repo as a
regression test for the FFI toolchain. Update this file whenever the
sandbox is exercised on a new platform/compiler.

## Toolchain pin

- `rust-toolchain.toml` channel: `1.90.0`
- Reason: LTS-style floor newer than the original RUST_DESIGN §6.3 pin
  (1.75.0, Jan 2024) but not bleeding-edge. Resolves PROGRESS.md OQ-1.

## How to build & run

From `~/devel/CAM-SIMA`:

```sh
LIBOMP=/opt/homebrew/opt/libomp
PATH="$HOME/.cargo/bin:$PATH" \
PFUNIT_DIR=/Users/hplin/devel/pfUnit/build/installed \
cmake -S test/unit/fortran -B build \
  -DCAM_SIMA_ENABLE_RUST_TESTS=ON \
  -DOpenMP_C_FLAGS="-Xpreprocessor -fopenmp -I${LIBOMP}/include" \
  -DOpenMP_C_LIB_NAMES=omp \
  -DOpenMP_omp_LIBRARY=${LIBOMP}/lib/libomp.dylib \
  -DOpenMP_Fortran_FLAGS="-fopenmp" \
  -DOpenMP_Fortran_LIB_NAMES=omp
cmake --build build
ctest --test-dir build -R rust_ffi_sandbox --output-on-failure
```

The OpenMP overrides are needed because pfUnit's CMake config requires
`find_package(OpenMP)`, and on macOS AppleClang does not ship OpenMP
detection — Homebrew `libomp` provides it. Linux platforms with GCC do
not need these overrides.

## Laptop (gfortran on macOS arm64) — VERIFIED 2026-04-23

- `rustc --version`: `rustc 1.90.0 (1159e78c4 2025-09-14)` (auto-fetched
  by rustup from the `rust-toolchain.toml` pin)
- `cargo --version`: `cargo 1.90.0 (840b83a10 2025-07-30)`
- Host triple: `aarch64-apple-darwin`
- Fortran compiler: `GNU Fortran (Homebrew GCC 15.2.0_1) 15.2.0`
- C/linker: AppleClang 21.0.0 + macOS ld
- pfUnit version: `PFUNIT-4.17`
- cmake: `cmake version 4.3.1`

`cargo rustc --release ... -- --print native-static-libs` (verbatim):

```
note: native-static-libs: -lSystem -lc -lm
```

Final cmake link line that worked (from
`build/src/rust_ffi_sandbox/CMakeFiles/test_rust_ffi_sandbox.dir/link.txt`):

```
/opt/homebrew/bin/gfortran -g \
  CMakeFiles/test_rust_ffi_sandbox.dir/test_rust_ffi.F90.o \
  CMakeFiles/test_rust_ffi_sandbox.dir/test_rust_ffi_sandbox_driver.F90.o \
  -o test_rust_ffi_sandbox \
  -L/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib/swift \
  rust_target/release/librust_ffi_sandbox.a -lSystem -lc -lm \
  /Users/hplin/devel/pFUnit/build/installed/PFUNIT-4.17/lib/libfunit.a \
  /opt/homebrew/opt/libomp/lib/libomp.dylib \
  .../libgftl-shared-v2-as-default.a \
  .../libfargparse.a \
  .../libgftl-shared-v2.a
```

Test result (`./build/src/rust_ffi_sandbox/test_rust_ffi_sandbox`):

```
....
Time:         0.000 seconds

 OK
 (4 tests)
```

All four pfUnit sub-tests pass: `identity`, `doubled`, `logical`,
`string`. Clean rebuild from `rm -rf build` also succeeds.

### Quirks observed

1. **pfUnit `assertTrue/assertFalse` does not accept `logical(c_bool)`.**
   The generic only resolves for default-kind `logical`. Tests must
   convert via `logical(x)` before asserting. Aligns with the in-cap
   conversion convention from RUST_DESIGN §7.3 (caps will convert
   `c_bool` → default logical at the boundary, never propagate `c_bool`
   into Fortran scheme bodies).
2. **macOS linker warns `ignoring duplicate libraries: '-lSystem'`.**
   Harmless: `--print native-static-libs` reports `-lSystem` and the
   macOS ld also adds it implicitly. Safe to ignore; documenting so
   future readers don't chase it.
3. **OpenMP must be supplied to cmake on macOS** (see "How to build &
   run" above). pfUnit pulls it in via `CMakeFindDependencyMacro`.

## Derecho (ifx on Linux x86_64) — VERIFIED 2026-04-23

- `rustc` / `cargo`: from `/glade/u/home/hplin/.cargo/bin/`
  (versions to be filled in on next Derecho session — `ctest` ran clean
  on first try).
- Fortran compiler: `ifx`
- pfUnit: as installed on Derecho
- Build dir: `/glade/derecho/scratch/hplin/260423_exp/CAM-SIMA.dev/build`

Test result: all four pfUnit sub-tests pass (Test #1
`test_rust_ffi_sandbox` — Passed, 0.02s).

### Quirk on ifx: warning #5472 (informational, not fatal)

The `logical(c_bool)` test triggers two compile-time warnings:

```
warning #5472: When passing logicals to C, specify '-fpscomp logicals'
to get the zero/non-zero behavior of FALSE/TRUE.
```

The warnings fire on the `logical(rust_ffi_sandbox_not(...))`
conversions inside `@assertTrue`/`@assertFalse`. They are
**informational** — the test passes anyway because Rust's `bool` always
returns 0 or 1, and Intel's default LOGICAL representation interprets
those values correctly (it tests bit 0). Tests still pass on ifx
without the flag.

**Why we are *not* adding `-fpscomp logicals`:**

- It is an Intel-specific flag. CAM-SIMA also builds with GNU and
  NVHPC/PGI; the sandbox's CMakeLists should stay compiler-agnostic.
- A grep of `cime_config/` and `~/devel/cime/` finds no existing
  `-fpscomp` usage. Adding it here would diverge from CIME convention.
- The warning *is* useful signal — it tells the reader of any future
  Phase 1 cap-generated code that `c_bool` ↔ default-logical conversions
  on Intel rely on bit-0 semantics. The right place to address that is
  the cap pattern itself (RUST_DESIGN §7.3: explicit `if (cbool_val)
  then; default_logical = .true.; else; default_logical = .false.;
  endif`), which is bit-perfect on every compiler and emits no warning.

If `-fpscomp logicals` is ever needed (e.g., a future Intel release
upgrades #5472 to an error), the fix is one cmake clause:

```cmake
if(CMAKE_Fortran_COMPILER_ID MATCHES "Intel")
  target_compile_options(test_rust_ffi_sandbox PRIVATE -fpscomp logicals)
endif()
```

## Lessons learned

To inform Phase 1 (capgen + buildlib):

- The `--print native-static-libs` regex match in `CMakeLists.txt`
  (`native-static-libs:([^\n]*)`) parses cleanly out of cargo 1.90.0
  stderr. Phase 1's `_capture_rust_native_libs` helper can use the same
  pattern.
- `find_program(CARGO_EXECUTABLE cargo HINTS $ENV{HOME}/.cargo/bin)`
  works without requiring callers to munge `PATH` first.
- `panic = "abort"` in both `[profile.release]` and `[profile.dev]`
  produces clean staticlibs for both build modes — no symptom of
  unwinding-related link failures.
- `logical(c_bool)` round-trip succeeds in both directions through the
  `bind(C)` boundary on gfortran *and* ifx. ifx warns (#5472) on the
  implicit `logical(c_bool_val)` kind conversion but the values come
  through correctly because Rust returns 0/1 only. RUST_DESIGN §7.3's
  prescription — caps emit explicit `if (cbool) ... else ... endif`
  rather than relying on intrinsic kind conversion — is the right
  pattern: it sidesteps the warning entirely and is bit-perfect for any
  integer payload, not just 0/1.

# M4 differential harness — real `tracer_data.F90` vs the executable oracle

The model-to-code bridge for `test/verification/models/m4_tracer_data`:
the real CAM-SIMA tracer_data bracketing machine, compiled against
recording stubs, replays the oracle's scenario inputs and its observable
actions are compared against `trc_oracle.py`'s prediction. This closes the
oracle README's declared blind spot ("until the differential harness
exists, drift between this model and the Fortran would go unnoticed"):
every oracle scenario that can run on real code now runs on real code.

Run it (requires gfortran only — no NetCDF, no submodules):

```
python3 test/verification/harnesses/m4_tracer_data/run_m4_harness.py
```

Full runtime is about 10 seconds: a one-time gfortran build, one fresh
process per scenario, and one 4-second watchdog wait on the livelock
scenario. 18 tests, 5 expected failures (the open-defect ratchets).

## What is real and what is stubbed

Compiled real, unmodified from the repository:

- `src/utils/tracer_data.F90` — the machine under test: `trcdata_init`,
  `advance_trcdata`, `read_next_trcdata`, `find_times`, `check_files`,
  `incr_filename`, `advance_file`, `set_cycle_indices`, `findplb`, the
  INTERP_MISSING_MONTHS fill path and the interpolation-weight
  computation. Compiled with `-finit-integer` so the undefined locals
  F-INPUTS-3 exposes read as a deterministic out-of-range sentinel
  (the oracle's arbitrary-but-fixed UNDEF, made concrete).
- `src/utils/string_utils.F90` + `src/core_utils/string_core_utils.F90` —
  the real `increment_string`, so the ccm-style filename increment is the
  production code path.
- The filelist branch of `incr_filename` performs its real Fortran `open`:
  scenario filelists are real text files in a per-scenario directory, and
  the F-INPUTS-4 abort fires through a genuinely failing open.

Stubbed (`stubs/`), recording to stdout as `EV|` lines:

- `pio` + `cam_pio_utils` + `ioFileMod`: an in-memory dataset registry
  (name + date/datesec coordinates — the information a real file
  carries); open binds a descriptor, `pio_get_var` serves the time
  coordinate, close records. A missing dataset aborts like a missing
  file.
- `cam_field_read`: the read recorder. Every record read emits
  `EV|read|<file>|<recno>` — the oracle's `StepResult.reads` observable —
  and fills the field with `1000*file_index + recno`, so the final field
  value exposes the interpolation and blend weights without instrumenting
  the real code. Out-of-range record numbers record as `badrec`.
- `time_manager`: driver-set calendar date; the date<->float mapping is
  transcribed from `src/utils/time_manager.F90` with line citations,
  including the NO_LEAP-only Feb 29 repair (`:279-281`) and the chkrc
  abort for invalid GREGORIAN dates (`:282-283, 1244-1249`).
- `cam_abortutils`: `endrun` emits an abort event and stops with a
  distinct exit code (structured outcome, no message matching).
- Trivia: serial `spmd_utils`, `shr_*`, `physconst`, `perf_mod`,
  `vert_coord`/`physics_grid` (4 columns, unstructured — which steers
  the reads onto the recorded path and makes every scenario field a
  surface field), `ref_pres`, `ccpp_kinds`, `cam_logfile` (stderr), and
  compile-only `interpolate_data`/`horizontal_interpolate`/
  `ccpp_tuvx_utils` (the lat/lon/vertical interpolation paths the
  unstructured surface-field scenarios never reach).

The driver (`driver.F90`) registers datasets, sets the calendar and
clock, runs the real `trcdata_init` once, and calls the real
`advance_trcdata` per step the way a host-model run loop would. After
each advance it emits the bracket state (`curr_mod_time`, `datatimem`,
`datatimep`, `interp_recs`, current/next filename, `datatimes(1:4)`) and
the field value.

## Guarantee statement

### 1. Property

For every replayable oracle scenario, the real code's observable behavior
equals the oracle's prediction with the same fix-flag configuration:
the same records read from the same files in the same order, the same
bracket and model time, the same interpolation/blend weights (observed
through the encoded field values), the same aborts, and the livelock
exactly where the oracle livelocks. This is simultaneously a fidelity
check on the oracle (the transcription cannot drift from the Fortran
unnoticed) and a concrete replay of the audit's counterexamples through
production code.

### 2. Assumptions

- The recording stubs are faithful at the recorded boundary: time
  coordinates reach the code only through the registry, record reads only
  through `cam_read_field`, aborts only through `endrun`.
- The stub time_manager's date<->float mapping (and its Feb 29 / chkrc
  semantics) transcribes the real `src/utils/time_manager.F90`; the float
  origin matches the oracle's Calendar, so time floats agree exactly.
- `-finit-integer` pins the F-INPUTS-3 undefined locals to one
  deterministic resolution (out-of-range, recorded as `badrec`); state
  downstream of an undefined value is not compared, matching the oracle's
  rule that no verdict depends on choices downstream of UNDEF.
- The livelock observable is the fresh process surviving to its watchdog
  timeout (the real loop's state is provably unchanged per round, so
  non-termination is deterministic).
- gfortran with `-O0`; one field per file ('TESTFLD'), surface data on an
  unstructured grid.

### 3. Checked domain

The oracle's scenario inputs, minus the five `fixed` companions (fix
flags cannot be turned on in the real code): six legal scenarios and the
five finding scenarios, over SERIAL / CYCLICAL / FIXED /
INTERP_MISSING_MONTHS, NO_LEAP and GREGORIAN, one- and two-file windows,
ccm-style and filelist increments. Vertical/horizontal interpolation,
PS-driven pressure reconstruction, `datesec` sub-day records,
CYCLICAL_LIST and restart paths are outside the replayed domain (see
blind spots).

### 4. Connection to production code

Executes the real code (list above). The defect scenarios are the Nov
2026 audit's documented counterexamples (F-INPUTS-1/-2/-3a/-3b/-4,
`state_machine_audit_nov26/sections/INPUTS.md`) firing through the
compiled machine:

| Fidelity test (must pass) | Ratchet (expectedFailure) | Fix group | Finding |
|---|---|---|---|
| `test_finputs2_fidelity_fill_two_file` | `test_ratchet_trc_file_window` | trc-file-window | F-INPUTS-2 |
| `test_finputs3a_fidelity_livelock` | `test_ratchet_trc_search_contract_livelock` | trc-search-contract | F-INPUTS-3a |
| `test_finputs3b_fidelity_undefined_recnos` | `test_ratchet_trc_search_contract_decadal` | trc-search-contract | F-INPUTS-3b |
| `test_finputs1_fidelity_feb29_gregorian` | `test_ratchet_calendar_mapping` | calendar-date-mapping | F-INPUTS-1 |
| `test_finputs4_fidelity_unset_filelist` | `test_ratchet_unset_sentinel` | trc-file-window | F-INPUTS-4 |

The fidelity tests compare against the oracle with fix flags OFF and must
pass today — they pin the defects' concrete behavior. The ratchets
compare the same runs against the flag-ON oracle (the fix group's target
semantics) and must fail today. When a fix group lands: its fidelity
test starts failing AND its ratchet flips to unexpected success — in the
fix PR, delete the fidelity test, retire the ratchet into a plain legal
comparison, and apply the oracle README's fix-flag retirement procedure.

Admission evidence: the five fidelity scenarios are historical
counterexamples firing through production code today; the five ratchets
fail against the target semantics; `test_comparator_detects_mutations`
tampers the event stream in each compared dimension (reads, record
numbers, bracket state, field values, abort) and must produce a diff.
Live catch: the harness's first run caught a transcription error in the
oracle itself — `incr_filename`'s filelist path joins
`<datapath>/<list>` whenever datapath is *present* (which `check_files`
always satisfies), not whenever it is nonempty, so an empty datapath
really opens the absolute path `/<list>` and aborts; the oracle had
modeled the emptiness branch and its filelist scenario ran with an empty
datapath. The oracle was corrected to the real semantics (see
`trc_oracle.py` `incr_filename`), which is exactly the drift this
harness exists to catch.

### 5. Blind spots

- F-INPUTS-1's abort fires in the stub time_manager (a cited
  transcription of the real `set_time_float_from_date`), not in compiled
  real code — ESMF cannot be linked here. The ratchet still encodes the
  fix group's target semantics; the transcription is the trust anchor.
- Data values and vertical/horizontal interpolation are not exercised
  (surface fields on the matching grid; weights only, via the encoded
  values). PS-driven hybrid-pressure reconstruction is unexercised.
- `datesec` sub-day records are elided (all scenario records are
  midnight), as in the oracle.
- CYCLICAL_LIST, the restart write/read path, and `stepTime` are out of
  scope on both sides.
- State downstream of an undefined value (F-INPUTS-3b's tail) is
  deliberately uncompared; the pinned observable is the undefined record
  reads themselves.
- The oracle's five `fixed` companion scenarios cannot replay against
  today's code; their semantics bind only through the ratchets.

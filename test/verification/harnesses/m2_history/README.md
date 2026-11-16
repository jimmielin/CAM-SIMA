# M2 differential harness — real `hist_file_t` vs the executable reference model

The model-to-code bridge for `test/verification/models/m2_history`: the
real CAM-SIMA history-volume code, compiled against recording stubs, is
driven through scenario operation sequences and its observable actions are
compared against an executable Python port of the M2 model's fixed (FG-3)
protocol. TLC counterexamples from the model replay here as concrete
failing sequences against the unfixed code, which is what makes a model
violation actionable as a code test.

Run it (requires gfortran and the `src/history/buffers` submodule,
`bin/git-fleximod update history`):

```
python3 test/verification/harnesses/m2_history/run_m2_harness.py
```

Full runtime is about 5 seconds, of which most is the one-time gfortran
build; 8 tests, 3 expected failures (the open-defect ratchets).

## What is real and what is stubbed

Compiled real, unmodified from the repository:

- `src/history/cam_hist_file.F90` — the protocol under test (configure,
  override commit, split routing, define, write, filenames, close).
- `src/history/cam_history_support.F90` (`parse_multiplier`, `fillvalue`,
  coordinate bookkeeping) and `src/utils/cam_filenames.F90` (filename
  interpolation), `src/utils/string_utils.F90`, `src/utils/datetime.F90`,
  `src/core_utils/string_core_utils.F90`.
- The ESMCI history buffer library (`src/history/buffers` at the submodule
  pin): `hist_api`, `hist_field`, `hist_buffer`, hash table, message
  handler — accumulate/normalize arithmetic is the real thing.

Stubbed (`stubs/`), recording to stdout as `EV|` lines:

- `pio` + `cam_pio_utils`: file create/close and variable definition are
  recorded; attributes and header `put_var`s are accepted and dropped.
  Creating an existing name truncates it, as PIO_CLOBBER does.
- `cam_grid_support`: one serial unstructured grid with 4 columns;
  `cam_grid_write_dist_array` is the field-data sink and records every
  written value.
- `time_manager`: model time is driver-set state (nstep, step size), so
  scenarios control dates deterministically; NO_LEAP arithmetic.
- `cam_abortutils`: `endrun` emits an abort event and stops with a
  distinct exit code (structured outcome, no message matching).
- Trivia: `spmd_utils` (serial masterproc), `shr_*`, `mpi` constants plus
  a no-op F77 `mpi_bcast` (linked, never called), `perf_mod`, `physconst`,
  `cam_control_mod`, `cam_initfiles`, `runtime_obj`, `cam_logfile`
  (routes the model log to stderr so stdout carries only events).

The driver (`driver.F90`) replays the per-volume slice of
`history_write_files` (`src/history/cam_history.F90:209-241`) and the
wrap-up close (`:865-879`): frame-boundary filename allocation and define,
the time-sample write, close when full. Field registration mirrors
`history_add_field_nd`, sampling mirrors `history_out_field_1d`. The
volume's own protocol — routing, buffers, filenames, sample counting — is
entirely the real code's.

## Guarantee statement

### 1. Property

For every scenario, the real code's observable event stream equals the
reference model's prediction: the same split files created per open round,
every produced file name unique within the run, each scenario field
defined in exactly its split file, and every (field, file generation,
frame) write carrying the expected accumulated value when the interval was
sampled and `_FillValue` when it was not. The reference model
(`reference_model.py`) is the FG-3 protocol of the M2 TLA+ spec made
executable; `lst`/`avg`/`min`/`max` accumulation arithmetic is predicted
exactly (scenario values are chosen so means are exact in binary).

### 2. Assumptions

- The recording stubs are faithful at the recorded boundary: files exist
  iff created, data reaches files only through `cam_grid_write_dist_array`
  on the open descriptor, aborts only through `endrun`.
- The driver's write choreography matches `history_write_files` for a
  single volume at step-based frequencies (the lines cited above).
- F-HIST-5's observable relies on each scenario running in a fresh
  process: the uninitialized normalization buffer then cannot hold a
  stale `_FillValue` pattern, so "not fill" is deterministic even though
  the garbage value itself is not.
- gfortran with `-O0`; the pinned buffers submodule.

### 3. Checked domain

Six scenarios over one volume of up to three 1-D (4-column) fields:
inst/avg/min/max lists, `1*nsteps` and `2*nsteps` cadences, 1/2/4 frames
per file, healthy and `%s`-less filename specs, sampled and unsampled
intervals, file rollover. Fixed sequences only — no generated operation
sequences yet (a Hypothesis strategy over op scripts is the natural
extension once FG-3 lands).

### 4. Connection to production code

Executes the real code (see the list above). The three defect scenarios
are the TLC counterexamples of the M2 model replayed concretely:

| Scenario | TLC counterexample | Audit finding | Status |
|---|---|---|---|
| `fhist1_avg_onestep` | `M2_prefix_fhist1_*` (RoutingComplete, NoDroppedData) | F-HIST-1 | expectedFailure ratchet |
| `fhist5_unsampled_interval` | `M2_prefix_fhist5_undef` (NoUndefinedData) | F-HIST-5 | expectedFailure ratchet |
| `fhist2_filename_reuse` | `M2_prefix_fhist2_clobber` (NoFilenameClobber) | F-HIST-2 | expectedFailure ratchet |

When an FG-3 fix lands, its ratchet flips to "unexpected success" and
fails the harness until the marker is removed — retire the ratchet, the
matching model `prefix` scenario's expectation, and the baseline entry (if
any) in the fix PR.

Admission evidence: the ratchets are historical counterexamples firing
through production code today; `test_comparator_detects_mutations` tampers
the event stream in each compared dimension (definition, write presence,
written values) and must produce a diff; the three legal scenarios are the
passing cases, including the shipped-testmod shape.

### 5. Blind spots

- Single volume; the cross-volume duplicate-name check in
  `history_write_files` is not exercised (the name-uniqueness check here
  is per-run, as the FG-3 registry would be).
- `write_nstep0`, restart write/read, the month/year triggers
  (F-HIST-4), interpolated/patch output, multi-rank decomposition and
  per-column fill are out of scope.
- Attribute contents (units, cell_methods, mdims) are dropped by the
  stubs, so metadata regressions are invisible here.
- Time-coordinate values (time, time_bounds, date) are not compared, only
  field data; the accumulated file's mid-interval dating is unchecked.
- The stub grid has one horizontal dimension; multi-grid volumes and
  3-D fields are not driven (the buffer library's own pFUnit tests cover
  3-D normalize semantics separately per the Nov audit plan).

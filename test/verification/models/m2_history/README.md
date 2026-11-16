# M2 — history-volume lifecycle model (TLA+)

A finite model of one CAM-SIMA history volume's lifecycle — configure,
set-up (the accumulate-type override commit), sample, write, buffer clear,
file rollover, and filename allocation — checked exhaustively with TLC.
The pre-fix protocol reproduces audit findings F-HIST-1, F-HIST-2 and
F-HIST-5 as invariant violations; the FG-3 protocol (Nov 2026
state-machine audit fix group) passes all invariants and the liveness
property, validating the fix design before it is implemented.

Run it (requires Java and tla2tools.jar, see "Tooling" below):

```
python3 test/verification/models/m2_history/run_m2.py
```

The driver runs every scenario and fails unless each one ends in exactly
its declared verdict. Full local runtime is about 8 seconds (eleven JVM
starts; each state space is tiny).

## Guarantee statement

### 1. Property

Safety, checked on every reachable state of each scenario:

- **SplitFlagsConsistent** — the define-time predicates
  (`has_instantaneous`/`has_accumulated`) agree with the committed
  accumulate types: a split flag is set iff some field routes to that
  split. One committed accumulate type drives both define and write.
- **RoutingComplete** — while a file set is open, every field of the
  volume is defined in a created split file (no field silently skipped).
- **NoDroppedData** — a field that accumulated samples is never skipped
  by a scheduled write.
- **NoUndefinedData** — write implies samples > 0 or `_FillValue`: no
  write emits the contents of an unsampled, non-fill buffer.
- **SampledDataIsWritten** — an interval that sampled a field writes the
  data, not fill (rules out the trivial always-fill implementation).
- **NoFilenameClobber** — a run never produces the same file name twice.

Liveness, under weak fairness: **AllScheduledWritesOccur** — every
scheduled write eventually happens (rules out the never-writing
implementation).

### 2. Assumptions

- The Fortran call order is configure → set_up_fields → (sample* →
  write)* with define-on-first-write, as read from the sources cited
  below at CAM-SIMA `43235026`; the model is hand-derived from that
  reading, not extracted mechanically.
- The buffer library behavior (normalize assigns a value only when
  `nacc > 0` or `flag_xyfill`) matches ESMCI/history_output at the
  submodule pin `56d9992`.
- Filename collision structure is abstracted to a time-key quotient: a
  "coarse" spec maps nearby opens to one name. This stands in for any
  user `hist_filename_spec` whose tokens do not advance between opens.
- TLC exit codes and the "Invariant X is violated" line are stable for
  the pinned tla2tools v1.7.4 (TLC 2.19).

### 3. Checked domain

One volume; one or two fields drawn from {inst-list, avg-list} with
avg/min/max/var collapsed to one "avg" kind; per-field `flag_xyfill` and
conditional-vs-unconditional sampling; write periods 1 and 2; horizons of
4–6 steps; 1–2 frames per file; fine vs coarse filename specs. Sampling
is fully nondeterministic for conditional fields, so TLC explores every
sampled/unsampled interleaving within the horizon. State spaces are 4–11
distinct states per scenario — small because buffers clear at writes;
the protocol's reachable abstract states genuinely collapse.

### 4. Connection to production code

This is a model of the code, not the code. Anchors at CAM-SIMA
`43235026` (unfixed, so "pre-fix" = current production protocol):

- Configure-time split flags from namelist list counts:
  `src/history/cam_hist_file.F90:877-883` (inst fields become `'lst'` at
  `:900`).
- The `1*nsteps` override commit, after which `has_*` are never
  recomputed (F-HIST-1): `src/history/cam_hist_file.F90:1066-1070`.
- File creation gated on `has_*`: `src/history/cam_hist_file.F90:1288-1296`.
- Define-loop and write-loop routing by current accumulate type, and the
  per-field buffer clear after write: `src/history/cam_hist_file.F90:1811-1824`,
  `:2274-2286`.
- Unsampled-buffer normalize (F-HIST-5): `buff_{1d,2d,3d}_value` in
  `src/history/buffers/src/hist_buffer.F90` at pin `56d9992` assigns
  `norm_val` only when `nacc > 0` or `flag_xyfill`.
- Filename allocation and the duplicate check that skips the volume
  itself (F-HIST-2): `src/history/cam_history.F90:212-230`.

The first bridge is the M2 differential harness at
`test/verification/harnesses/m2_history/`: real `hist_file_t` operations
against an executable reference model (the FG-3 protocol of this spec,
`reference_model.py`) with recording PIO/grid stubs. The TLC
counterexamples of the three `prefix` scenarios replay there as concrete
failing sequences (expectedFailure ratchets until FG-3 lands). The second
bridge — runtime assertions derived from these invariants, each naming its
model invariant — lands with the FG-3 fix PRs. The model and the harness
reference model must change together; a green model run alone constrains
the design, not the Fortran.

### 5. Blind spots

- `write_nstep0` and the nstep-0 buffer clear are unmodeled; F-HIST-2's
  nstep0-file trigger variant is represented only by the coarse-name
  trigger.
- Single volume: cross-volume filename interactions (including the
  spurious-abort case in the existing check) are out of scope.
- `sampled_on_subcycle` fields are unmodeled; the override is applied to
  every field.
- Restart write/read, interpolated output, patch output, accumulation
  arithmetic (avg vs min vs max vs var produce one abstract "data"), and
  per-column fill are all abstracted away.
- The month/year trigger arithmetic (F-HIST-4) is not modeled; write
  scheduling is a plain step modulus.
- MPI rank structure is absent; the model is the masterproc view.

## Scenarios

| Scenario | Protocol | Expected verdict |
|---|---|---|
| `M2_prefix_fhist1_routing` | pre-fix, avg-only at `1*nsteps` | violates `RoutingComplete` (F-HIST-1) |
| `M2_prefix_fhist1_dropped` | same | violates `NoDroppedData` (F-HIST-1) |
| `M2_prefix_fhist1_flags` | pre-fix, mixed volume at `1*nsteps` | violates `SplitFlagsConsistent` (F-HIST-1, empty split file) |
| `M2_prefix_fhist5_undef` | pre-fix, conditional avg field, 2-step interval | violates `NoUndefinedData` (F-HIST-5) |
| `M2_prefix_fhist2_clobber` | pre-fix, coarse filename spec, mfilt=1 | violates `NoFilenameClobber` (F-HIST-2) |
| `M2_prefix_legal_testmod` | pre-fix, unconditional inst-only fields | passes — the shape of every shipped `1*nsteps` testmod, i.e. why CI never fired |
| `M2_fixed_full` | FG-3, mixed volume at `1*nsteps`, conditional sampling | passes all invariants + liveness |
| `M2_fixed_avg_interval` | FG-3, the F-HIST-5 shape | passes all invariants + liveness |
| `M2_fixed_coarse_names` | FG-3, the F-HIST-2 shape | passes — registry halts loudly instead of clobbering |
| `M2_mutation_alwaysfill` | FG-3 + fault injection | violates `SampledDataIsWritten` |
| `M2_mutation_neverwrites` | FG-3 + fault injection | violates `AllScheduledWritesOccur` (liveness) |

Admission evidence per rule 3 of `test/verification/README.md`: the five
pre-fix scenarios are the historical counterexamples (the findings are
live in the current sources); the two mutations demonstrate the liveness
companions can fail; the three fixed scenarios and the pre-fix legal
scenario are the passing legal cases.

## Tooling

- Any Java 11+ runtime (locally: `brew install openjdk`; the driver
  finds the keg-only Homebrew java automatically).
- `tla2tools.jar` pinned to release v1.7.4 (TLC 2.19),
  sha256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`,
  from https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4 — set
  `$TLA2TOOLS_JAR` or place it at `~/devel/tla/tla2tools.jar`.

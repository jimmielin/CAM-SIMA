# M4: tracer_data time-bracketing oracle

An executable reference model (Python, stdlib only) of the tracer_data
time-bracketing machine — `src/utils/tracer_data.F90`'s `advance_trcdata` /
`read_next_trcdata` core: `find_times`, `check_files`, `incr_filename`,
`advance_file`, `set_cycle_indices`, `findplb`, the INTERP_MISSING_MONTHS
fill path, and the interpolation weights. State machines SM-INPUTS-1/2/3/4
of the Nov 2026 state-machine audit; fix groups `calendar-date-mapping`,
`trc-file-window`, `trc-search-contract` (FG-9 umbrella).

- `trc_oracle.py` — the model library. Every routine cites the Fortran
  lines it transcribes (CAM-SIMA `146ccde1`; this core is unchanged since
  audit base `27639b49`).
- `run_m4_oracle.py` — the scenario driver. Every scenario declares its
  verdict; the run fails on any mismatch.

## Guarantee statement

- **Property**: the bracketing machine's observable behavior per step —
  which records are read from which file, the bracket
  `(datatimem, datatimep)`, the interpolation and blend weights, and every
  abort/livelock — as a deterministic function of (mode, calendar, file
  time coordinates, model date). Legal scenarios assert the protocol facts
  the audit verified in the real code (first advance always reads;
  `datatimem <= t < datatimep` after a SERIAL read; the cyclical Dec→Jan
  wrap brackets and weights; FIXED freezes after the first read;
  STALE-CURR persists until a failed search advances the window; the
  single-file fill lands each series in its own year). Finding scenarios
  assert the four documented defects fire exactly as documented.
- **Assumptions**: file time coordinates are strictly increasing within a
  file and across the `curr ++ next` concatenation; `datesec` handling and
  the PIO layer are elided (dates carry the information); Fortran
  undefined locals are modeled as an UNDEF sentinel whose ordering
  comparisons return False (one arbitrary-but-fixed resolution; no
  scenario verdict depends on a choice downstream of UNDEF); the model's
  Livelock detector (state-unchanged search round) is exactly the real
  loop's non-termination condition, since the loop body is deterministic
  in that state.
- **Checked domain**: the 16-scenario table below — modes SERIAL,
  CYCLICAL, FIXED, INTERP_MISSING_MONTHS (single- and multi-file) ×
  calendars NO_LEAP, GREGORIAN × the audit's trigger dates. CYCLICAL_LIST
  is out of scope (latent: not offered by any a_p `valid_values`); the
  model aborts (`MODEL_SCOPE`) if it is reached.
- **Connection to production code**: a line-by-line transcription with
  line citations, validated against the audit's live-code traces (the
  F-INPUTS-2 trace in `sections/INPUTS.md` is reproduced verbatim,
  including its two-call prefetch precondition). It does NOT execute the
  Fortran itself: that bridge is the differential harness
  (`test/verification/harnesses/m4_tracer_data`), which compiles the real
  `tracer_data.F90` against recording stubs and replays every replayable
  scenario of this table against the compiled code.
- **Blind spots**: data values and vertical/horizontal interpolation
  (weights only are modeled); restart paths (F-INPUTS-7, not implemented
  upstream); CYCLICAL_LIST; `datesec` sub-day records; the `stepTime`
  mode (never set in SIMA). Drift between this model and the Fortran is
  caught by the differential harness, which replays this table against
  the compiled code (it caught one transcription error on its first run:
  the `incr_filename` datapath join, see the harness README). Still treat
  model changes like code changes (cite lines).

## Scenario table

| scenario | kind | verdict asserted |
|---|---|---|
| serial_two_file | legal | brackets/weights hold; prefetch at boundary; STALE-CURR until a failed search; then advance |
| serial_filelist | legal | filenames_list increment path opens the listed next file |
| cyclical_wrap | legal | Dec→Jan wrapped bracket; no spurious re-read; weights in [0,1] |
| fixed_frozen | legal | FROZEN after first read; no clock read; stable rounded weight |
| fill_single_file | legal | series land in their own years; blends in [0,1]; remapped bracket contains t |
| feb29_noleap | legal | NO_LEAP repairs Feb 29 to Feb 28 |
| fill_two_file_wrong_years | F-INPUTS-2 | second call reads 1980/1990 instead of 1990/2000; blend extrapolates |
| fill_two_file_fixed | fixed | `fix_file_window`: window normalized; correct years; blends in range |
| cyclical_single_record_livelock | F-INPUTS-3a | search loop livelocks on a one-record cycle year |
| cyclical_single_record_fixed | fixed | `fix_search_contract`: loud abort instead |
| fill_decadal_undefined | F-INPUTS-3b | stale times_found passes the unreachable guards; UNDEFINED record indices |
| fill_decadal_fixed | fixed | `fix_search_contract`: loud abort instead |
| feb29_gregorian_aborts | F-INPUTS-1 | GREGORIAN + non-leap cycle year aborts (CHKRC) on mapped Feb 29 |
| feb29_gregorian_fixed | fixed | `fix_calendar_mapping`: clamps to Feb 28; run continues |
| unset_filelist_aborts | F-INPUTS-4 | 'UNSET' sentinel opens `<datapath>/UNSET` and aborts |
| unset_filelist_fixed | fixed | `fix_unset_sentinel`: sentinel normalized; increment path proceeds |

## Admission evidence

The four finding scenarios are the admission evidence: each reproduces a
documented counterexample of the Nov 2026 audit (F-INPUTS-1/-2/-3a/-3b/-4,
`state_machine_audit_nov26/sections/INPUTS.md`), all confirmed against the
real code at `27639b49` during that audit and unchanged at `146ccde1`. The
legal scenarios are the passing cases, taken from the audit's
considered-and-refuted traces.

## Fix flags and the retirement procedure

Each fix flag encodes the target semantics of its fix group, so the fix PR
inherits its expected behavior from the `fixed` scenarios:

- When a fix group lands upstream, its pre-fix finding scenario starts
  failing ("did the code get fixed?"). In the fix PR: make the flag's
  behavior the model's only behavior (delete the flag), delete the pre-fix
  scenario, and keep the `fixed` scenario as a plain legal scenario.
- The differential harness replays this table against the compiled
  Fortran: each finding scenario runs there twice, as a fidelity test
  (real == flags-off oracle, must pass today) and as an expectedFailure
  ratchet against the flag-ON target semantics — retire both together
  with the fix flag (`harnesses/m4_tracer_data/README.md`).

## Run

```
python3 test/verification/models/m4_tracer_data/run_m4_oracle.py
```

Ends `run_m4_oracle: ok (16 scenarios)`; nonzero exit on any verdict
mismatch. Pure stdlib; no submodules, no NetCDF, no PIO.

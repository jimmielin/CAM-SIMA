# ledger/ — the capgen v0-vs-v1 assumption ledger

The CCPP code generator is the one interface this verification tree must
treat as volatile: capgen-v1 reaches CAM-SIMA through a compatibility shim
([atmospheric_physics #463](https://github.com/ESCOMP/atmospheric_physics/pull/463),
[nusbaume/CAM-SIMA `capgen-v1`](https://github.com/nusbaume/CAM-SIMA/tree/capgen-v1))
and is already known to change constituent ordering at CAM-SIMA scale
(round-off answer changes). This directory writes down the host-visible
guarantees CAM-SIMA relies on from generated code as numbered assumptions,
each with an executable check that runs against **both** generators, so a
v1 behaviour change surfaces as a named assumption failure instead of a
downstream mystery.

**Lifecycle**: deliberately transient scaffolding, like the shim it
mirrors. When capgen-v1 lands in CAM-SIMA and v0 retires, the v0 column
and the staging shims here go away; assumptions still worth watching
migrate into the regular suites or runtime assertions.

## Running

```
python3 test/verification/ledger/run_ledger.py              # v0 + v1 if present
python3 test/verification/ledger/run_ledger.py --require-v1 # CI: fail if v1 missing
```

v0 is the in-repo `ccpp_framework` submodule pin (populate with
`bin/git-fleximod update ccpp-framework`). v1 is a checkout of
NCAR/ccpp-framework `feature/capgen-v1` at the pin recorded in
`run_ledger.py` (`V1_PIN`, the same commit CAM-SIMA's capgen-v1 branch
pins), found via `$CAPGEN_V1_ROOT` or `~/devel/ccpp-framework-capgen-v1`:

```
git clone --filter=blob:none https://github.com/NCAR/ccpp-framework ccpp-framework-capgen-v1
git -C ccpp-framework-capgen-v1 checkout <V1_PIN>
```

Requires gfortran. A missing v1 checkout skips the v1 half with a notice;
an off-pin checkout runs with a warning (the recorded expectations may not
apply).

## The fixture

One synthetic mini-host (`fixtures/`), accepted by both generators, driven
through three scenarios per generator, each in a fresh process:

| Scenario | Drives |
|---|---|
| `clean` | full choreography, 3 timesteps |
| `fail` | `ldg_order_b` reports errflg 42 at step 2 |
| `violate` | a run call before any timestep_init |

- `ledger_host_mod.F90/.meta` — host module data (dims, step counter, a
  temperature field the host rewrites each step).
- `ledger_host.meta` — the v0 `type = host` table; `ledger_control.meta` —
  the v1 `type = control` table (v1-only, mirrors CAM-SIMA's
  `src/data/ccpp_control_vars.meta`).
- `ldg_order_a/b/c`, `ldg_const` — stub schemes emitting `EV|` events;
  `ldg_const` registers one dynamic constituent, declares one
  auto-promoted (`advected = .true.`) one, and writes per-constituent
  markers through the scheme-side index lookup.
- `ledger_suite.xml` — two groups: alpha (`ldg_order_a`, `ldg_const`),
  beta (`ldg_order_b`, `ldg_order_c`).
- `main_v0.F90` / `main_v1.F90` — per-generation drivers (staged as the
  host source `ledger_host.F90`); same choreography and events, different
  cap API, mirroring `cam_comp`/`phys_comp`: register, constituents,
  init, per step timestep_init → run per group → timestep_final, final,
  aborting on any nonzero errflg.

## Assumptions

Status: `PASS` = holds, checked every run. All assumptions currently hold
identically on both generators; a divergence would appear here as an
expected-divergent entry with its consequence.

| ID | Assumption | CAM-SIMA reliance | v0 | v1 |
|---|---|---|---|---|
| A0 | suite-trace's capgen-nx backend agrees with the pinned framework capgen on resolution verdicts for all shipped SDFs | the instrument behind local suite tracing and the audits | deferred | n/a |
| A1 | capgen generates, and its datatable file list suffices to compile and link, a working host cap; every host-cap call of a legal run succeeds | `cam_autogen.py` (generation + datatable-driven build) | PASS | PASS |
| A2 | schemes execute in SDF order within each phase; phases follow register → init → (timestep_init → run per group → timestep_final)\* → final; host-module data is seen per step | suite definitions are the scientific contract; `phys_comp.F90` phase calls | PASS | PASS |
| A3 | a scheme's nonzero errflg skips the rest of its group+phase and reaches the host intact with a message | `cam_comp.F90`/`phys_comp.F90` check-and-endrun after every phase call | PASS | PASS |
| A4 | host-side and scheme-side constituent index lookups agree; the properties vector matches; metadata-promoted constituent args alias the constituents array | constituent coupling (dycore advection, `cam_constituents`) | PASS | PASS |
| A5 | host-side constituent index order is stable per generator (recorded baseline; **not** registration order on either side) | restarts, ICs, answer reproducibility; the documented capgen-v1 reorder is this assumption breaking at CAM-SIMA scale | PASS | PASS* |
| A6 | generated caps reject out-of-protocol phase calls (run before timestep_init) with nonzero errflg | defense in depth behind `phys_comp`'s own sequencing | PASS | PASS |
| A7 | suite-internal variables persist across group boundaries within a timestep | every multi-group SDF interstitial | PASS | PASS |

A0 is deferred: suite-trace is a local tool (not in CI) and its planned
`-v1` adapter does not exist yet; the check lands with that adapter. The
definition is fixed now so the slot does not drift: for every shipped SDF,
`suite-trace status` and a real capgen run must agree on resolves/fails
and on the set of unresolved standard names.

*A5 on v1: on this 4-constituent fixture v1 happens to produce the same
order as v0, so the recorded baselines coincide; the CAM-SIMA-scale
reorder is documented upstream but not reproduced at this fixture size
(see blind spots).

## Recorded interface divergences (absorbed, not failures)

Differences the fixture hit between the generators, absorbed here exactly
where CAM-SIMA's capgen-v1 branch absorbs them. Each names its absorber;
when CAM-SIMA migrates off the absorber, the matching staging shim in
`run_ledger.py` goes with it.

| ID | Divergence | Absorbed by |
|---|---|---|
| D1 | metadata table taxonomy: `type = module` rejected by v1 (becomes `type = host`); the v0 `type = host` control surface becomes a `type = control` table with no backing Fortran, and v1 requires the control variables (suite/group name, thread counts, loop bounds, errmsg/errcode) declared there | shim's parse-time rewriter + `src/data/ccpp_control_vars.meta` on the capgen-v1 branch; here: `stage_fixture()` + `ledger_control.meta` |
| D2 | host-cap entry surface: v0 `<host>_ccpp_physics_*` / positional errors; v1 generic `ccpp_*` entry points, keyword `errcode`, every physics phase takes group name, column bounds and thread counts, and framework init/final are separate calls (`ccpp_init`/`ccpp_final`) | CAM-SIMA host driver updates on the capgen-v1 branch; here: `main_v0.F90` vs `main_v1.F90` |
| D3 | datatable reports: v0 `--ccpp-files` is gone; v1 splits it into `--capgen-files` + `--utility-files` + `--dependencies` | `capgen_compat/_cap_database.py`; here: `cap_file_list()` |
| D4 | v1 rejects intent(out) constituent-flagged args outside the register phase unless named `tendency_of_*`; new base constituents must come from register-phase `ccpp_constituent_properties_t` registration (this is what moved scalars/constituents into `_register` subroutines across atmospheric_physics #463) | scheme metadata migration in a_p #463; here: the fixture declares its auto-promoted constituent `intent = inout` in the run phase, legal on both |
| D5 | v1 only accepts CAM-SIMA's current conventions behind transient CLI shims: `--legacy-mode` (`horizontal_loop_extent` rewriting) and `--legacy-auto-clone-constituents` (metadata-declared constituents) | `capgen_compat/_framework_env.py` defaults both True; here: `generate_caps()` passes both |
| D6 | generated-file layout: v1 emits per-group caps, a suite data module and `ccpp_host_constituents.F90` instead of one monolithic suite cap | nothing needs absorbing — the datatable file list covers it (A1) |

## Guarantee statement

1. **Property**: assumptions A1–A7 above, checked as contracts over the
   recorded event stream of real generated code driven through its
   phases; identical checks against the v0 pin and the v1 branch pin.
2. **Assumptions**: the fixture's staging differences (D1–D5) faithfully
   mirror how CAM-SIMA's capgen-v1 branch drives each generator; gfortran
   semantics; the framework pins named in `.gitmodules` and `V1_PIN`.
3. **Checked domain**: one 2-group, 4-scheme, 4-constituent suite over
   3 timesteps and 4x3 grid cells; three scenarios per generator; each
   scenario a fresh process.
4. **Connection to production code**: executes the real generators and
   the real generated caps plus real framework support sources
   (constituent machinery, scheme utils), unmodified; the stub host
   mirrors `cam_comp`/`phys_comp` choreography. No CAM-SIMA Fortran is
   linked — this ledger checks the generator contract, not CAM-SIMA.
5. **Blind spots**: constituent populations large enough to expose the
   documented v1 reorder (A5 passes at fixture scale); the capgen_compat
   Python-API surface (covered by that branch's own
   `test/unit/python/capgen_compat` suite, not here); DDT host
   variables; subcycles and suite parts beyond plain groups; OpenMP
   threading (caps compiled without `-fopenmp`, thread guards inert);
   unit conversions; optional/conditional metadata variables;
   `write_init_files`/init-mark semantics (CAM-SIMA-side generator,
   exercised by its own unit tests on both branches).

**Admission evidence**: `test_admission_mutations` doctors the real event
streams in every observable dimension (call order, resurrection of a
skipped scheme, swallowed errflg, crossed index lookup, broken slice
aliasing, permuted constituent order, stale host data, silenced protocol
guard) and requires every checker to fire. The D4 rejection above is a
live historical counterexample caught by this fixture during admission:
the first fixture draft used a v0-legal `intent = out` constituent in an
init phase and v1 refused to generate.

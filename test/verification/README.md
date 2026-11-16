# test/verification — lightweight formal methods for CAM-SIMA infrastructure

Executable verification artifacts for CAM-SIMA's infrastructure (control,
history, utils, cpl, data, and the cime_config Python generators): protocol
models, property suites, static class checkers, and the harnesses that connect
models to the real code. Physics (`ncar_ccpp`) and `ccpp_framework` are out of
scope; the host-visible capgen contract is covered by the assumption ledger
instead (see `ledger/`).

The governing roadmap (rationale, bug-class mapping against the 2026 audits,
phasing) is maintained outside the repository for now; this README carries the
rules every artifact in this tree must follow, so the tree stands on its own.

## Layout

| Directory | Contents |
|---|---|
| `checkers/` | small static class checkers (stdlib Python; one class per checker) |
| `properties/` | Hypothesis property suites over the generators (`cam_autogen`, registry, buildnml) |
| `models/` | TLA+/Alloy protocol specs, one subdirectory per model with its README |
| `harnesses/` | differential harnesses connecting a model to the real code (reference model + recording stubs) |
| `ledger/` | the capgen assumption ledger: numbered assumptions A0..An, each with an executable check run against both the capgen-v0 pin and the capgen-v1 shim |

## Guarantee statement (required for every artifact)

Each layer checks; none proves. Every artifact carries a guarantee statement —
a header comment for a checker, a README section for a model or suite — naming
five things:

1. **Property**: what it checks, stated as a contract.
2. **Assumptions**: what it relies on being true (pins, metadata fidelity,
   stub behavior).
3. **Checked domain**: the finite model's state space, the Hypothesis
   strategies and example budget, or the set of files actually parsed.
4. **Connection to production code**: does it execute real code or a model of
   it, and if a model, what bridges the two (derived assertions, differential
   harness).
5. **Blind spots**: what it is known not to see.

Static checkers additionally report three verdicts per site — checked,
violated, **unknown** — with coverage counts. Silently skipping unparsed or
unresolved code never counts as success.

## Admission rules

1. **Class quantification.** Properties quantify over an enumerable class (all
   registry variables, all namelist declarations, all volumes x fields, all
   SDFs) so new code is covered automatically. Tests naming one variable are
   only admitted as labeled oracle/instance tests of a documented contract or
   numeric semantics.
2. **Contract assertions only.** Assert structured outcomes: guard fired
   (nonzero errflg, named abort path, exit status), transition rejected, phase
   value, `_FillValue` present. Never assert message prose. To distinguish
   failure causes, match a stable identifier the message necessarily contains
   (variable/scheme/file name), never the sentence around it. No opaque error
   tokens.
3. **Evidence it can fail.** A check is admitted with a demonstrated failure:
   a historical counterexample where one exists (the 2026 audit corpus; run
   the check against CAM-SIMA `27639b49` and it must fire), otherwise a
   deliberate mutation or injected fault — plus at least one legal case that
   must pass.
4. **Transition tests, not resurrection tests.** When a fix makes an invalid
   state unrepresentable, test that illegal transitions are rejected loudly
   and the legal sequence runs end to end; do not reconstruct the old bad
   state through a back door.
5. **No naked fixes.** A fix PR for an audited defect states its anti-pattern
   (P1..P9 of the Nov 2026 state-machine audit) and lands or extends a class
   property in the same PR.

## CI

- Per-PR gates (push/pull_request on this branch): stdlib-Python/gfortran
  checks that run in under a minute — checkers, suite-trace status and
  read-before-write, lint rules.
- Nightly matrix (owned hardware, or workflow_dispatch here): high-example
  Hypothesis runs, generated-cap compiles across suite combinations, the
  dual-pin assumption ledger. Note that GitHub Actions `schedule:` triggers
  fire only on a repository's default branch.
- A check is promoted to a per-PR gate only with its measured runtime; any
  check disabled for more than one release cycle is deleted, not skipped.

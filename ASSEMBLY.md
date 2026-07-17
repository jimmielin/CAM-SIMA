# hplin/cam5_mam4_full — assembly record (CAM-SIMA)

**EPHEMERAL INTEGRATION BRANCH — never a PR.** Rebuild it from the recipe
below whenever an ingredient moves; do not merge updates into it, and never
cherry-pick from this branch back into the unit branches. Master copy of
this record + the full fix register:
`~/devel/design_docs/mam_project_scratchpad/cam5_mam4_assembly_scoping.md`.

Assembled 2026-07-16.

## Ingredients (exact heads)

| Ingredient | Head | Content |
|-|-|-|
| `hplin/modal_aero_4` (base) | `3e8f099` | MAM host wiring: registry, physics_data, coupler, testmods |
| `CAM-SIMA-dycore-update` | `42cd5ce` | SE dycore update = Peter's head + PR #3 (b4b IC-read fixes, SE-CSLAM b4b, memory-leak/constituent-index fix); brings FHISTC_LTso ne16 ncdata defaults + scale_dry_air_mass |
| `pumas_round3` | `f397eb4` | Jesse's + FIX-4 (registry naai/dust-dim renames, ndust param, relvar=2/accre_enhan=1/qsatfac=1 initial values = GAP-G) |
| `hplin/cam5_macrop` | `275b76a` | registry additions for Park macrophysics |
| `hplin/uwshcu` | `548907e` | registry additions + UW testmods |

## Merge order and conflict resolutions

```
git checkout -b hplin/cam5_mam4_full 3e8f099
git merge CAM-SIMA-dycore-update      # clean
git merge --no-commit pumas_round3    # clean; then FIX-7:
git checkout HEAD -- .gitmodules src/physics/ncar_ccpp
git commit                            # keep OUR .gitmodules + ncar_ccpp ptr
git merge hplin/cam5_macrop           # clean
git merge hplin/uwshcu                # clean
# then the FIX-8 registry semantic dedupe commit (f84b86d) — see its
# commit message for the per-name resolutions
```

No textual conflicts occurred; the registry duplicates merged SILENTLY and
were removed by the dedupe commit. After ANY registry-touching re-merge,
re-run the audit:
`grep -oE '(standard_name|local_name)="[^"]*"' src/data/registry.xml | sort | uniq -d`

## Submodules (checked out manually, not by git)

- `src/physics/ncar_ccpp` -> atmospheric_physics `hplin/cam5_mam4_full`
  (checked out manually; .gitmodules deliberately NOT updated since the
  branch is unpushed).
- Inside it, `schemes/pumas/pumas` -> nusbaume/PUMAS @ `c4aec4a`.

## Post-merge work on this branch

- `01a5cb4` FHIST_C5 compset (FIX-9): FHIST component set with CAM50 +
  the `_CAM50` -> `--physics-suites cam5` CAM_CONFIG_OPTS mapping.
- `8a87660` FHIST_C5 lname -> SROF_SGLC (cism not checked out in CAM-SIMA).
- `8385b50` (user) sgh30 registry entry (from hplin/beljaars, already in
  development).
- `90941a5` topography_statics_read (FIX-13): SGH/SGH30/LANDM_COSLAT from
  bnd_topo; durable home = standalone CAM-SIMA PR. Needs bnd_topo set in
  user_nl_cam.
- `3224c87` + follow-up: externals aligned to CAM cam_development pins
  (FIX-16), triggered by cdeps1.0.84 FPE-trapping on NaN stream data in
  debug (urbantv/CLM init; fixed upstream in cdeps1.0.93). Bumped fxtags:
  cdeps 1.0.93, ccs_config 1.0.81, cice cesm3_cice6_6_3_5, cime 6.1.169,
  clm ctsm5.4.024, cmeps 1.1.41, mosart 1.1.13, parallelio pio2_6_8,
  share 1.1.19, CUPiD v0.5.1. ncar-physics deliberately untouched.
  After `git-fleximod update`, RE-CHECKOUT the atmos_phys octopus branch
  in src/physics/ncar_ccpp (fleximod resets it to the pinned hash).

## Validation done at assembly

- Duplicate standard_name/local_name audit clean after dedupe.
- registry generator (generate_registry_data.py, dycore none) runs clean
  against the atmos_phys octopus with the PUMAS submodule present;
  ndust param, relvar_in=2, qsatfac_in=1 initializations confirmed in
  generated physics_types.F90.

Anything else changed here to make the run work MUST be added to the fix
register in the scoping doc with a durable home (our unit branches /
pumas_round3 PR to Cheryl+Jesse / recorded-here-only).

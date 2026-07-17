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
- (no commit, case config) FIX-33: user_nl_cam MUST set
  `drydep_srf_file = '/glade/campaign/cesm/cesmdata/inputdata/atm/cam/chem/trop_mam/atmsrf_ne16pg3_c230520.nc'`
  (the CAM default for ne16pg3). With it UNSET, fraction_landuse_read
  silently leaves the registry fraction_landuse at 0; the drydep
  bottom-level velocity is the landuse-WEIGHTED sum (aero_drydep_core
  wrk3, verbatim CAM), so vlc_dry(pver) = 0 exactly -> zero dry
  deposition flux for EVERY aerosol (DDV nonzero aloft, DDF/GVF = 0;
  dust burden reached 2.5 g/m2 by day 2). CAM cannot hit this (missing
  atmsrf aborts in build-namelist); flag to upstream: the host read
  should WARN on UNSET at least. One of the two missing sinks behind the
  day-3 AOD runaway -> SW crash (the other = FIX-32 convproc bridge,
  atmos_phys).
- (no commit, case config) Dust with CLM Leung_2023: user_nl_cam MUST set
  `zender_soil_erod_from_atm = .false.` -- the aero_emissions XML default
  is .true. (the Zender+atm-erodibility validation shape), which
  multiplies CLM's Fall_flxdst by the soil_erod field; with
  soil_erod_file UNSET that field is all zero, so DSTSFMBL/dst_a*SF come
  out identically 0 while the coupler import is healthy. The flag is the
  documented stopgap for CAM-SIMA not reading drv_flds_in
  dust_emis_inparm; keep it consistent with CLM's dust_emis_method until
  the shr_dust_emis read lands (emissions PR 2). dust_emis_fact = 0.88 is
  the Leung-consistent tuning (Zender FHIST used 1.75).
- `3224c87` + follow-up: externals aligned to CAM cam_development pins
  (FIX-16), triggered by cdeps1.0.84 FPE-trapping on NaN stream data in
  debug (urbantv/CLM init; fixed upstream in cdeps1.0.93). Bumped fxtags:
  cdeps 1.0.93, ccs_config 1.0.81, cice cesm3_cice6_6_3_5, cime 6.1.169,
  clm ctsm5.4.024, cmeps 1.1.41, mosart 1.1.13, parallelio pio2_6_8,
  share 1.1.19, CUPiD v0.5.1. ncar-physics deliberately untouched.
  After `git-fleximod update`, RE-CHECKOUT the atmos_phys octopus branch
  in src/physics/ncar_ccpp (fleximod resets it to the pinned hash).
- `aee42e9` FIX-20: initial_value for the PUMAS external-ice trio
  (effi_external_in = 25 micron, snowice/numsnow_tend_external_in = 0).
  Without one, write_init_files.py makes the ncdata read FATAL. These are
  CAM's do_cldice=.false. inputs — never read here (CAM passes NaN), so
  the values are fail-safe placeholders, not physics. The scoping doc
  records two real upstream PUMAS wiring bugs found while diagnosing this
  (meta `um` vs code `m` in the submodule = flag to Cheryl/Jesse; REI vs
  RE_ICE conflation in dims_pre = deferred, atmos_phys-local).
- `e61be7a` (user) FIX-21/22: more initial_value fixes (ICWMRDP, cldfrc);
  FIX-11 do_clubb hardcode brought down from a stash into the branch;
  removed an un-guarded `DEBUG -JN` loop in the SE dyn_comp (durable home
  = the CAM-SIMA-dycore-update branch — tell Jesse or it returns on the
  next rebuild).
- `136c15d` FIX-23 **REVERTED in `467fc38`** — its premise was false (the
  dycore never reads or marks runtime-registered constituents). Do not
  re-apply that hoist: it breaks snapshot runs.
- `db0a911` FIX-23R/24: runtime-registered advected constituents (all MAM
  aerosols) had NO IC path in a dycore run — read_inidat skipped them (no
  registry entry -> no ic_file_input_names) and physics read them on the
  physics grid while ncdata holds them on the dynamics grid. Fix:
  read_inidat falls back to the constituent's standard name as the IC
  field name; new index-keyed `const_mark_as_initialized` /
  `const_is_initialized` in cam_constituents let the dycore tell physics
  what it already read (phys_vars_init_check cannot — it is name-keyed
  over registry variables only); plus `dbuf3 = 0._r8` when a constituent
  is absent from the file (it used to inherit the previous constituent's
  data). Durable home = standalone CAM-SIMA PR; the read_inidat hunks ride
  the dycore b4b fixes.
- `a0f198c` FIX-25: phys_init marks the constituents an "init" phase scheme
  set (those no longer at the value the constituents object initialized
  them to) so the IC read skips them. Fixes the CFC11 dim mismatch —
  CFC11 is non-advected (rad_climate 'N:CFC11STAR:CFC11'), so the dycore
  skips it while the file still carries it on the dynamics grid, and its
  value was already set by prescribe_radiative_gas_concentrations_init.
  Scoped to non-null dycores to keep the snapshot path (and its b4b)
  unchanged. Durable home = standalone CAM-SIMA PR. The underlying gap
  (init-phase schemes cannot tell the IC read they set a constituent, so
  prescribed gases absent from ncdata are silently zeroed) is upstream and
  being filed by the user.
- FIX-36: registry entries for the four net radiative flux profiles
  (fns/fcns/fnl/fcnl, W m-2, interface-dimensioned, initial 0). The rrtmgp
  calculate_fluxes schemes write them only on radiation steps (FIX-30
  early-return) while heating-rate + diagnostics schemes read them every
  step; as capgen group-locals they were PER-CALL allocatables (fresh heap
  each group invocation, deallocated at exit), so every non-radiation step
  read uninitialized memory -- an FPE lottery that hit at nstep 4 (the
  first non-rad step under irad_always=-1) of the first FIX-34/35 run, and
  that the 5-day run survived only by heap-reuse luck. Host storage =
  CAM's pbuf persistence semantics; no scheme changes. REVISES FIX-30's
  premise: capgen group-local persistence across timesteps is NOT a
  contract (upstream ccpp-framework flag, user files). These entries must
  land WITH the FIX-30 scheme guards in the upstream atmos_phys PR.
- `714a43f` FIX-34 (registry half; schemes = atmos_phys `47cbfb3`): five
  std names renamed to the live-producer spellings (NEVAPR, PRAIN,
  NEVAPR_SHCU, NEVAPR_DPCU precip inputs; pbuf_tke -> tke_at_interfaces).
  ic_file_input_names unchanged, so snapshot suites still read the same
  tape fields. Rides the MAM host PR.
- `0187ca4` FIX-31 (registry half; producer = atmos_phys `631d15d`
  co2_diagnostic_export): co2diag std name co2diag_tbd ->
  diagnostic_volume_mixing_ratio_of_co2_to_coupler (units ppmv), variable
  entry + cam_out_t ddt member. The scheme exports prescribed_co2_vmr*1e6
  each step (CAM camsrfexch convention), so CLM_CO2_TYPE can return to
  'diagnostic' after rebuild. Set `prescribed_co2_vmr = 336.8e-6` in
  user_nl_cam for 1979 (default 367e-6 -- and radiation uses this same
  namelist value). co2prog_tbd stays a placeholder.
  Pre-fix workaround (needed until the rebuild): CASE XML
  `./xmlchange CLM_CO2_TYPE=constant CCSM_CO2_PPMV=336.8`; with CLM's
  default co2_type='diagnostic' the land received Sa_co2diag = 0 ppm and
  LUNA NaN'd at its daily update once its 10-day CO2 running mean decayed
  (LunaMod nue 0/0). A run that hit this must RESTART FROM SCRATCH -- the
  CLM restart carries the poisoned running mean. Full analysis in the fix
  register.

## Validation done at assembly

- Duplicate standard_name/local_name audit clean after dedupe.
- registry generator (generate_registry_data.py, dycore none) runs clean
  against the atmos_phys octopus with the PUMAS submodule present;
  ndust param, relvar_in=2, qsatfac_in=1 initializations confirmed in
  generated physics_types.F90.

Anything else changed here to make the run work MUST be added to the fix
register in the scoping doc with a durable home (our unit branches /
pumas_round3 PR to Cheryl+Jesse / recorded-here-only).

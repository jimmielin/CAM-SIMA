#!/usr/bin/env python3
"""M4 tracer_data oracle scenario driver: every scenario declares its
verdict and the run fails on any mismatch.

Scenario classes (see README.md for the full table):
  - legal scenarios reproduce the audit's refuted-claim traces and must run
    clean with in-range weights;
  - finding scenarios reproduce the documented counterexamples of
    F-INPUTS-1/-2/-3a/-3b/-4 against today's semantics (fix flags off) --
    they are the oracle's admission evidence;
  - fixed companions run the same inputs with the matching fix flag on and
    assert the target semantics, so the eventual fix PR inherits its
    expected behavior from here (retire-the-flag procedure in README.md).

Run: python3 test/verification/models/m4_tracer_data/run_m4_oracle.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# pylint: disable=wrong-import-position
from trc_oracle import (Calendar, Clock, DataFile, Endrun, Filesystem,
                        Livelock, TracerDataModel, is_undef)


def monthly_file(name, year, day=16):
    """Twelve mid-month records for <year>."""
    return DataFile(name, [year * 10000 + mm * 100 + day
                           for mm in range(1, 13)])


def multi_year_file(name, years, day=16):
    """Twelve mid-month records for each year in <years>, concatenated."""
    dates = []
    for year in years:
        dates.extend(year * 10000 + mm * 100 + day for mm in range(1, 13))
    return DataFile(name, dates)


def build(files, clock, cal=None, filelists=None, **flags):
    """A TracerDataModel over the given files, clock and calendar."""
    return TracerDataModel(Filesystem(files, filelists), clock,
                           cal or Calendar("NO_LEAP"), **flags)


def in_unit(fact):
    """True when a weight is defined and within [0,1]."""
    return not is_undef(fact) and 0.0 <= fact <= 1.0


# ---------------------------------------------------------------------------
# Legal scenarios (the audit's refuted-claim traces)
# ---------------------------------------------------------------------------

def scn_serial_two_file():
    """SERIAL across a file boundary: first advance always reads, brackets
    hold every step, weights stay in [0,1]. The window prefetches at the
    boundary and then stays STALE-CURR through the whole next file (the
    documented SM-INPUTS-2 semantics: advance_file only runs from a failed
    search), advancing only when model time passes its last record."""
    clock = Clock(1980, 1, 20, 0)
    model = build([monthly_file("ozone_1980.nc", 1980),
                   monthly_file("ozone_1981.nc", 1981),
                   monthly_file("ozone_1982.nc", 1982)], clock)
    model.trcdata_init("ozone_1980.nc", data_type="SERIAL")
    first = model.advance_trcdata()
    assert first.read_performed, "first advance must read (datatimep=-huge)"
    months = [(1980, mm) for mm in range(2, 13)] + \
             [(1981, mm) for mm in range(1, 13)]
    for year, mon in months:
        clock.set_date(year, mon, 20)
        step = model.advance_trcdata()
        tfile = model.file
        assert tfile.datatimem <= tfile.curr_mod_time < tfile.datatimep, \
            f"bracket violated at {year}-{mon}"
        assert in_unit(step.fact1), f"fact1 out of range at {year}-{mon}"
        if (year, mon) == (1981, 11):
            # STALE-CURR: reading records of the prefetched next file while
            # the 1980 file is still current (harmless for SERIAL).
            assert tfile.curr_filename == "ozone_1980.nc", \
                "window advanced without a failed search"
            assert step.reads and all(f == "ozone_1981.nc"
                                      for f, _ in step.reads)
    # Passing the end of the next file finally fails the search, advances
    # the window, and prefetches the third file.
    assert model.file.curr_filename == "ozone_1981.nc", \
        "window did not advance after passing the next file's records"
    return ("brackets and weights hold; STALE-CURR persists until the "
            "search fails, then the window advances")


def scn_serial_filelist():
    """SERIAL with a real filenames_list: the next file comes from the list.
    The datapath must be nonempty: incr_filename always joins
    <datapath>/<list> (the join guard is present(datapath), which
    check_files satisfies), so an empty datapath opens /<list> and aborts
    -- a latent quirk the differential harness surfaced."""
    clock = Clock(1980, 12, 20, 0)
    model = build([monthly_file("a.nc", 1980), monthly_file("b.nc", 1981)],
                  clock,
                  filelists={"ozone_files": ["a.nc", "b.nc"]})
    model.trcdata_init("a.nc", filelist="ozone_files", datapath="data",
                       data_type="SERIAL")
    model.advance_trcdata()
    assert model.file.next_filename == "b.nc" or \
        model.file.curr_filename == "b.nc", "list increment not taken"
    return "filenames_list increment path opens the listed next file"


def scn_cyclical_wrap():
    """CYCLICAL Dec->Jan wrap: wrapped bracket, no spurious re-read across
    the year boundary, weights in [0,1] on both sides (audit refuted-claim
    trace)."""
    clock = Clock(1995, 12, 20, 0)
    model = build([monthly_file("clim.nc", 1990)], clock)
    model.trcdata_init("clim.nc", data_type="CYCLICAL", cycle_yr=1990)
    step = model.advance_trcdata()
    tfile = model.file
    assert tfile.datatimep < tfile.datatimem, "expected wrapped bracket"
    assert in_unit(step.fact1), "wrap weight out of range (Dec side)"
    clock.set_date(1996, 1, 1)
    step = model.advance_trcdata()
    assert not step.read_performed, "spurious re-read across the wrap"
    assert in_unit(step.fact1), "wrap weight out of range (Jan side)"
    clock.set_date(1996, 1, 20)
    step = model.advance_trcdata()
    assert step.read_performed, "no re-read after passing datatimep"
    assert tfile.datatimem <= tfile.curr_mod_time < tfile.datatimep
    return "wrapped bracket and weights agree with the refuted-claim trace"


def scn_fixed_frozen():
    """FIXED data freezes after the first read: no clock read, no re-read,
    identical rounded weights (audit refuted-claim trace)."""
    clock = Clock(1, 1, 1, 0)
    model = build([monthly_file("fix.nc", 1980)], clock)
    model.trcdata_init("fix.nc", data_type="FIXED", fixed_ymd=19800615)
    first = model.advance_trcdata()
    assert first.read_performed
    frozen_time = model.file.curr_mod_time
    clock.set_date(1, 3, 1)
    second = model.advance_trcdata()
    assert not second.read_performed, "FROZEN state re-read"
    assert model.file.curr_mod_time == frozen_time, "FROZEN read the clock"
    assert second.fact1 == first.fact1, "FROZEN weight drifted"
    return "FROZEN after first read; weight stable"


def scn_fill_single_file():
    """INTERP_MISSING_MONTHS, one file holding 1980 and 1990 months, model
    in 1985: both series land in their own years, the blend is in range,
    and the remapped bracket contains the model time."""
    clock = Clock(1985, 6, 20, 0)
    model = build([multi_year_file("f.nc", [1980, 1990])], clock)
    model.trcdata_init("f.nc", data_type="INTERP_MISSING_MONTHS")
    step = model.advance_trcdata()
    cal = model.cal
    tfile = model.file
    assert step.blended and tfile.interp_recs == 2, "blend not consumed"
    assert cal.date_from_float(tfile.datatimes[0])[0] == 1980, "series1 year"
    assert cal.date_from_float(tfile.datatimes[2])[0] == 1990, "series2 year"
    assert all(in_unit(b1) for b1, _ in step.blend_facts), \
        f"blend weights out of range: {step.blend_facts}"
    assert tfile.datatimem <= tfile.curr_mod_time < tfile.datatimep, \
        "remapped bracket does not contain model time"
    assert in_unit(step.fact1)
    return "series years correct; blend and bracket weights in range"


def scn_feb29_noleap():
    """NO_LEAP calendar repairs Feb 29 (time_manager.F90:279)."""
    cal = Calendar("NO_LEAP")
    clock = Clock(4, 2, 29, 0)
    model = build([monthly_file("clim.nc", 1850)], clock, cal=cal)
    model.trcdata_init("clim.nc", data_type="CYCLICAL", cycle_yr=1850)
    model.advance_trcdata()
    assert model.file.curr_mod_time == cal.time_float(1850, 2, 28, 0)
    return "Feb 29 repaired to Feb 28 under NO_LEAP"


# ---------------------------------------------------------------------------
# Finding scenarios (fix flags off) and their fixed companions
# ---------------------------------------------------------------------------

def _two_file_fill_calls(**flags):
    """F-INPUTS-2 setup (audit scenario 1): curr = 1980 months, next =
    1990+2000 months. The FIRST call sits in the inter-file gap, so
    check_files prefetches without advancing (curr_mod_time <
    next_data_times(1)) and that call's fill is the enforced fid1=curr
    case. The SECOND call at 1995 then brackets entirely inside the
    prefetched next file (STALE-CURR, no failed search)."""
    clock = Clock(1985, 6, 20, 0)
    model = build([monthly_file("file1.nc", 1980),
                   multi_year_file("file2.nc", [1990, 2000])],
                  clock, **flags)
    model.trcdata_init("file1.nc", data_type="INTERP_MISSING_MONTHS")
    first = model.advance_trcdata()
    cal = model.cal
    # First call (enforced case): series years correct, window prefetched.
    assert cal.date_from_float(model.file.datatimes[0])[0] == 1980
    assert cal.date_from_float(model.file.datatimes[2])[0] == 1990
    assert all(in_unit(b1) for b1, _ in first.blend_facts)
    assert model.file.next_data_times is not None, "window not prefetched"
    clock.set_date(1995, 6, 20)
    second = model.advance_trcdata()
    return model, second


def scn_fill_two_file_wrong_years():
    """F-INPUTS-2 fires on the second call: with both bracketing records in
    the prefetched next file, the fill-path cycle indices address the wrong
    years (audit scenario 1 trace) and a blend weight leaves [0,1]."""
    model, step = _two_file_fill_calls()
    cal = model.cal
    tfile = model.file
    assert step.read_performed and tfile.curr_filename == "file1.nc", \
        "expected the STALE-CURR window (no advance before the fill)"
    # series1 (want 1990) bracketed 1980 records of the CURRENT file
    assert cal.date_from_float(tfile.datatimes[0])[0] == 1980, \
        "series1 should (wrongly) land in 1980 -- did the code get fixed?"
    assert ("file1.nc", 12) in step.reads and ("file1.nc", 1) in step.reads, \
        "series1 records should (wrongly) come from the current file"
    # series2 (want 2000) bracketed 1990 records
    assert cal.date_from_float(tfile.datatimes[2])[0] == 1990, \
        "series2 should (wrongly) land in 1990"
    assert any(not in_unit(b1) for b1, _ in step.blend_facts), \
        "expected an extrapolating blend weight"
    return ("series years 1980/1990 instead of 1990/2000; blend "
            "extrapolates (F-INPUTS-2)")


def scn_fill_two_file_fixed():
    """fix_file_window: the second call normalizes the window before the
    fill path, so both series land in their own years with in-range
    blends."""
    model, step = _two_file_fill_calls(fix_file_window=True)
    cal = model.cal
    tfile = model.file
    assert cal.date_from_float(tfile.datatimes[0])[0] == 1990, "series1 year"
    assert cal.date_from_float(tfile.datatimes[2])[0] == 2000, "series2 year"
    assert all(fname == "file2.nc" for fname, _ in step.reads), \
        "all records must come from the advanced current file"
    assert all(in_unit(b1) for b1, _ in step.blend_facts)
    return "normalized window: series years 1990/2000, blends in range"


def _single_record_cyclical_model(**flags):
    """F-INPUTS-3a setup: CYCLICAL onto a cycle year with one record,
    model time (mapped) before that record."""
    clock = Clock(1995, 3, 1, 0)
    annual = DataFile("annual.nc", [19900701])
    model = build([annual], clock, **flags)
    model.trcdata_init("annual.nc", data_type="CYCLICAL", cycle_yr=1990)
    return model


def scn_cyclical_single_record_livelock():
    """F-INPUTS-3a fires: the search loop makes no progress (the real
    do-while never exits; audit scenario 2)."""
    model = _single_record_cyclical_model()
    try:
        model.advance_trcdata()
    except Livelock:
        return "search loop livelocks on a one-record cycle year"
    raise AssertionError("expected Livelock -- did the code get fixed?")


def scn_cyclical_single_record_fixed():
    """fix_search_contract: the same inputs abort loudly instead."""
    model = _single_record_cyclical_model(fix_search_contract=True)
    try:
        model.advance_trcdata()
    except Endrun as err:
        assert err.code in ("CYC_WINDOW_LT2", "SEARCH_NO_PROGRESS"), err.code
        return f"loud abort ({err.code}) instead of livelock"
    raise AssertionError("expected a loud abort")


def _decadal_fill_model(**flags):
    """F-INPUTS-3b setup: INTERP_MISSING_MONTHS onto decadal annual
    records (one record per represented year)."""
    clock = Clock(1995, 6, 20, 0)
    decadal = DataFile("decadal.nc", [19900701, 20000701])
    model = build([decadal], clock, **flags)
    model.trcdata_init("decadal.nc", data_type="INTERP_MISSING_MONTHS")
    return model


def scn_fill_decadal_undefined():
    """F-INPUTS-3b fires: the series search finds nothing but the stale
    times_found skips both the early return and the endrun guards, leaving
    undefined record indices (audit scenario 3)."""
    model = _decadal_fill_model()
    step = model.advance_trcdata()
    assert is_undef(step.reads[0][1]) and is_undef(step.reads[1][1]), \
        f"expected UNDEFINED series records, got {step.reads}"
    assert is_undef(model.file.datatimes[0]), "expected undefined datatimes"
    return "undefined record indices pass the unreachable endrun guards"


def scn_fill_decadal_fixed():
    """fix_search_contract: the same inputs abort loudly in the series
    search instead of proceeding with undefined indices."""
    model = _decadal_fill_model(fix_search_contract=True)
    try:
        model.advance_trcdata()
    except Endrun as err:
        assert err.code == "CYC_WINDOW_LT2", err.code
        return "loud abort (CYC_WINDOW_LT2) instead of undefined reads"
    raise AssertionError("expected a loud abort")


def _feb29_gregorian_model(**flags):
    cal = Calendar("GREGORIAN", **flags)
    clock = Clock(4, 2, 29, 0)        # proleptic-Gregorian leap year 4
    model = build([monthly_file("clim.nc", 1850)], clock, cal=cal)
    model.trcdata_init("clim.nc", data_type="CYCLICAL", cycle_yr=1850)
    return model


def scn_feb29_gregorian_aborts():
    """F-INPUTS-1 fires: GREGORIAN + CYCLICAL with a non-leap cycle year
    aborts (CHKRC) when the model reaches Feb 29 of a leap year."""
    try:
        _feb29_gregorian_model().advance_trcdata()
    except Endrun as err:
        assert err.code == "CHKRC", err.code
        return "ESMF_TimeSet failure (CHKRC) on mapped 1850-02-29"
    raise AssertionError("expected CHKRC -- did the code get fixed?")


def scn_feb29_gregorian_fixed():
    """fix_calendar_mapping: the CAM-style repair clamps Feb 29 to Feb 28
    for the non-leap cycle year; no abort."""
    model = _feb29_gregorian_model(fix_calendar_mapping=True)
    model.advance_trcdata()
    assert model.file.curr_mod_time == \
        model.cal.time_float(1850, 2, 28, 0)
    return "mapped date clamped to 1850-02-28; run continues"


def _unset_filelist_model(**flags):
    """F-INPUTS-4 setup: SERIAL with the a_p default filelist sentinel
    'UNSET'; the next file exists so only the sentinel blocks progress."""
    clock = Clock(1980, 12, 20, 0)
    model = build([monthly_file("ozone_1980.nc", 1980),
                   monthly_file("ozone_1981.nc", 1981)],
                  clock, **flags)
    model.trcdata_init("ozone_1980.nc", filelist="UNSET",
                       datapath="/data", data_type="SERIAL")
    return model


def scn_unset_filelist_aborts():
    """F-INPUTS-4 fires: the 'UNSET' sentinel is treated as a real
    filelist, so the file-boundary crossing aborts trying to open
    <datapath>/UNSET and the filename-increment path is unreachable."""
    try:
        _unset_filelist_model().advance_trcdata()
    except Endrun as err:
        assert err.code == "OPEN_FAIL" and "UNSET" in err.detail, \
            (err.code, err.detail)
        return "aborts opening <datapath>/UNSET (increment unreachable)"
    raise AssertionError("expected OPEN_FAIL on UNSET")


def scn_unset_filelist_fixed():
    """fix_unset_sentinel: the sentinel normalizes to 'no filelist', the
    increment path opens the next file, and the run continues."""
    model = _unset_filelist_model(fix_unset_sentinel=True)
    step = model.advance_trcdata()
    assert step.read_performed
    assert model.file.next_filename == "ozone_1981.nc" or \
        model.file.curr_filename == "ozone_1981.nc", \
        "increment path did not open the next file"
    return "sentinel normalized; filename increment opens the next file"


SCENARIOS = [
    ("legal",   scn_serial_two_file),
    ("legal",   scn_serial_filelist),
    ("legal",   scn_cyclical_wrap),
    ("legal",   scn_fixed_frozen),
    ("legal",   scn_fill_single_file),
    ("legal",   scn_feb29_noleap),
    ("F-INPUTS-2", scn_fill_two_file_wrong_years),
    ("fixed",   scn_fill_two_file_fixed),
    ("F-INPUTS-3a", scn_cyclical_single_record_livelock),
    ("fixed",   scn_cyclical_single_record_fixed),
    ("F-INPUTS-3b", scn_fill_decadal_undefined),
    ("fixed",   scn_fill_decadal_fixed),
    ("F-INPUTS-1", scn_feb29_gregorian_aborts),
    ("fixed",   scn_feb29_gregorian_fixed),
    ("F-INPUTS-4", scn_unset_filelist_aborts),
    ("fixed",   scn_unset_filelist_fixed),
]


def main():
    """Run every scenario and fail on any verdict mismatch."""
    failures = 0
    for kind, scenario in SCENARIOS:
        name = scenario.__name__.replace("scn_", "")
        try:
            verdict = scenario()
            print(f"ok   [{kind}] {name}: {verdict}")
        except AssertionError as err:
            failures += 1
            print(f"FAIL [{kind}] {name}: {err}")
        except (Endrun, Livelock) as err:
            failures += 1
            print(f"FAIL [{kind}] {name}: unexpected {type(err).__name__}: "
                  f"{err}")
    if failures:
        print(f"run_m4_oracle: FAILED ({failures} of {len(SCENARIOS)} "
              "scenarios)")
        return 1
    print(f"run_m4_oracle: ok ({len(SCENARIOS)} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

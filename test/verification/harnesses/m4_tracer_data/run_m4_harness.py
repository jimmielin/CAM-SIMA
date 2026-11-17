#!/usr/bin/env python3
"""M4 differential harness: real tracer_data.F90 vs the executable oracle.

Builds the real CAM-SIMA tracer_data machine (src/utils/tracer_data.F90,
unmodified, plus the real string_utils increment path) against recording
stubs for PIO, the field readers and the time manager, then replays the
M4 oracle's scenario inputs (test/verification/models/m4_tracer_data) and
compares the recorded events against the oracle's prediction:
  - which records are read from which file (EV|read lines),
  - the bracket (datatimem, datatimep) and model time,
  - the interpolation and blend weights, observed through field values the
    stubs encode as f(file, record),
  - every abort and the livelock.

Scenario classes:
  - legal + finding scenarios are compared against the oracle with fix
    flags OFF (today's semantics): all must agree, which is the fidelity
    check that keeps the oracle honest against the real Fortran. The
    finding scenarios reproduce F-INPUTS-1/-2/-3a/-3b/-4 through the real
    code (F-INPUTS-1 is stub-mediated, see README.md) and start failing
    when a fix lands ("did the code get fixed?").
  - ratchet tests compare the same finding inputs against the oracle with
    the matching fix flag ON (the target semantics): expectedFailure until
    the fix group lands, then they flip to unexpected success and fail the
    harness until retired together with the oracle's fix flag.

tracer_data.F90 is compiled with -finit-integer so the undefined locals
F-INPUTS-3 exposes read as a deterministic sentinel (an out-of-range
record number the read stub records as `badrec`), mirroring the oracle's
arbitrary-but-fixed UNDEF. State downstream of an undefined value is not
compared (the oracle's verdicts never depend on it either).

Each scenario runs the driver in a fresh process; the livelock scenario's
observable is the process surviving to its watchdog timeout.

Requires gfortran. Guarantee statement in README.md next to this script.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HARNESS_DIR, "..", "..", "..", ".."))
MODEL_DIR = os.path.join(REPO_ROOT, "test", "verification", "models",
                         "m4_tracer_data")
sys.path.insert(0, MODEL_DIR)

# pylint: disable=wrong-import-position
from trc_oracle import (Calendar, Clock, DataFile, Endrun, Filesystem,
                        Livelock, TracerDataModel, is_undef)

STUBS = [
    "shr_kind_mod", "ccpp_kinds", "runtime_obj", "cam_logfile", "spmd_utils",
    "perf_mod", "physconst", "vert_coord", "ref_pres", "physics_grid",
    "shr_string_mod", "harness_events", "cam_abortutils", "time_manager",
    "pio", "cam_pio_utils", "ioFileMod", "cam_field_read",
    "interpolate_data", "horizontal_interpolate", "ccpp_tuvx_utils",
]

REAL_SOURCES = [
    "src/core_utils/string_core_utils.F90",
    "src/utils/string_utils.F90",
    "src/utils/tracer_data.F90",
]

# Pin tracer_data's undefined integer locals (read when F-INPUTS-3's stale
# times_found skips the search) to a deterministic out-of-range sentinel.
UNDEF_PIN_FLAGS = ("-finit-integer=-987654321",)

ABORT_EXIT_CODE = 17

BUILD_DIR = None
DRIVER = None
RUN_CACHE = {}


def monthly(year, day=16):
    """Twelve mid-month yyyymmdd records for <year>."""
    return [year * 10000 + mm * 100 + day for mm in range(1, 13)]


def multi_year(years, day=16):
    """Twelve mid-month records for each year in <years>, concatenated."""
    dates = []
    for year in years:
        dates.extend(year * 10000 + mm * 100 + day for mm in range(1, 13))
    return dates


def _serial_two_file_steps():
    months = [(1980, mm) for mm in range(2, 13)] + \
             [(1981, mm) for mm in range(1, 13)]
    return [(1980, 1, 20, 0)] + [(yr, mm, 20, 0) for (yr, mm) in months]


# Scenario inputs mirror run_m4_oracle.py one-to-one (same files, clock
# dates and trcdata_init arguments). init = (filename, filelist, datapath,
# data_type, cycle_yr, fixed_ymd, fixed_tod); steps[0] is the clock at
# init time and drives the first advance.
SCENARIOS = {
    "serial_two_file": {
        "files": [("ozone_1980.nc", monthly(1980)),
                  ("ozone_1981.nc", monthly(1981)),
                  ("ozone_1982.nc", monthly(1982))],
        "init": ("ozone_1980.nc", "", "", "SERIAL", 0, 0, 0),
        "steps": _serial_two_file_steps(),
    },
    "serial_filelist": {
        "files": [("a.nc", monthly(1980)), ("b.nc", monthly(1981))],
        "filelists": {"ozone_files": ["a.nc", "b.nc"]},
        "init": ("a.nc", "ozone_files", "data", "SERIAL", 0, 0, 0),
        "steps": [(1980, 12, 20, 0)],
    },
    "cyclical_wrap": {
        "files": [("clim.nc", monthly(1990))],
        "init": ("clim.nc", "", "", "CYCLICAL", 1990, 0, 0),
        "steps": [(1995, 12, 20, 0), (1996, 1, 1, 0), (1996, 1, 20, 0)],
    },
    "fixed_frozen": {
        "files": [("fix.nc", monthly(1980))],
        "init": ("fix.nc", "", "", "FIXED", 0, 19800615, 0),
        "steps": [(1, 1, 1, 0), (1, 3, 1, 0)],
    },
    "fill_single_file": {
        "files": [("f.nc", multi_year([1980, 1990]))],
        "init": ("f.nc", "", "", "INTERP_MISSING_MONTHS", 0, 0, 0),
        "steps": [(1985, 6, 20, 0)],
    },
    "feb29_noleap": {
        "files": [("clim.nc", monthly(1850))],
        "init": ("clim.nc", "", "", "CYCLICAL", 1850, 0, 0),
        "steps": [(4, 2, 29, 0)],
    },
    "fill_two_file_wrong_years": {
        "files": [("file1.nc", monthly(1980)),
                  ("file2.nc", multi_year([1990, 2000]))],
        "init": ("file1.nc", "", "", "INTERP_MISSING_MONTHS", 0, 0, 0),
        "steps": [(1985, 6, 20, 0), (1995, 6, 20, 0)],
    },
    "cyclical_single_record_livelock": {
        "files": [("annual.nc", [19900701])],
        "init": ("annual.nc", "", "", "CYCLICAL", 1990, 0, 0),
        "steps": [(1995, 3, 1, 0)],
        "timeout": 4,
    },
    "fill_decadal_undefined": {
        "files": [("decadal.nc", [19900701, 20000701])],
        "init": ("decadal.nc", "", "", "INTERP_MISSING_MONTHS", 0, 0, 0),
        "steps": [(1995, 6, 20, 0)],
    },
    "feb29_gregorian_aborts": {
        "calendar": "GREGORIAN",
        "files": [("clim.nc", monthly(1850))],
        "init": ("clim.nc", "", "", "CYCLICAL", 1850, 0, 0),
        "steps": [(4, 2, 29, 0)],
    },
    "unset_filelist_aborts": {
        "files": [("ozone_1980.nc", monthly(1980)),
                  ("ozone_1981.nc", monthly(1981))],
        "init": ("ozone_1980.nc", "UNSET", "data", "SERIAL", 0, 0, 0),
        "steps": [(1980, 12, 20, 0)],
    },
}

# Finding scenario -> the fix flag whose oracle semantics the ratchet
# compares against (the fix group's target behavior).
RATCHET_FLAGS = {
    "fill_two_file_wrong_years": {"fix_file_window": True},
    "cyclical_single_record_livelock": {"fix_search_contract": True},
    "fill_decadal_undefined": {"fix_search_contract": True},
    "feb29_gregorian_aborts": {"fix_calendar_mapping": True},
    "unset_filelist_aborts": {"fix_unset_sentinel": True},
}


# ---------------------------------------------------------------------------
# Build and run the driver
# ---------------------------------------------------------------------------

def build_driver():
    """Compile the driver once for the whole run; returns executable path."""
    global BUILD_DIR, DRIVER  # pylint: disable=global-statement
    BUILD_DIR = tempfile.mkdtemp(prefix="m4_harness_")
    fcompiler = os.environ.get("FC", "gfortran")
    base = [fcompiler, "-c", "-ffree-line-length-none", "-O0", "-g",
            "-J", BUILD_DIR]
    objs = []

    def compile_one(path, extra=()):
        obj = os.path.join(
            BUILD_DIR, os.path.basename(path).replace(".F90", ".o"))
        cmd = base + list(extra) + [path, "-o", obj]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=BUILD_DIR, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"compile failed: {path}\n{proc.stderr}")
        objs.append(obj)

    for stub in STUBS:
        compile_one(os.path.join(HARNESS_DIR, "stubs", stub + ".F90"))
    for rel in REAL_SOURCES:
        extra = UNDEF_PIN_FLAGS if rel.endswith("tracer_data.F90") else ()
        compile_one(os.path.join(REPO_ROOT, rel), extra)
    compile_one(os.path.join(HARNESS_DIR, "driver.F90"))

    DRIVER = os.path.join(BUILD_DIR, "m4_driver")
    proc = subprocess.run([fcompiler, "-o", DRIVER] + objs,
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("link failed:\n" + proc.stderr)
    return DRIVER


def make_ops(spec):
    """The driver op script for one scenario."""
    lines = ["dtime 1800", "calendar " + spec.get("calendar", "NO_LEAP")]
    for name, dates in spec["files"]:
        lines.append("datafile " + name + " " +
                     " ".join(str(d) for d in dates))
    first = spec["steps"][0]
    lines.append(f"date {first[0]} {first[1]} {first[2]} {first[3]}")
    fname, flist, dpath, dtype, cyc, fymd, ftod = spec["init"]
    lines.append(f"init {fname} {flist or '-'} {dpath or '-'} {dtype} "
                 f"{cyc} {fymd} {ftod}")
    lines.append("advance")
    for step in spec["steps"][1:]:
        lines.append(f"date {step[0]} {step[1]} {step[2]} {step[3]}")
        lines.append("advance")
    return "\n".join(lines) + "\n"


def _as_text(data):
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def run_scenario(name):
    """Run one scenario in a fresh process (cached); returns
    (events, returncode, timed_out)."""
    if name in RUN_CACHE:
        return RUN_CACHE[name]
    spec = SCENARIOS[name]
    tmpdir = tempfile.mkdtemp(prefix="m4_scn_")
    try:
        # Filelists are real text files at <datapath>/<name>, where
        # incr_filename's list branch does a plain Fortran open relative
        # to the scenario directory.
        listdir = tmpdir
        if spec["init"][2]:
            listdir = os.path.join(tmpdir, spec["init"][2])
            os.makedirs(listdir, exist_ok=True)
        for lname, entries in spec.get("filelists", {}).items():
            listpath = os.path.join(listdir, lname)
            with open(listpath, "w", encoding="utf-8") as handle:
                handle.write("\n".join(entries) + "\n")
        timed_out = False
        returncode = None
        try:
            # The livelock scenario floods the log; discard stderr (the
            # comparator reads only stdout events).
            proc = subprocess.run([DRIVER], input=make_ops(spec),
                                  capture_output=False, text=True,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,
                                  timeout=spec.get("timeout", 30),
                                  cwd=tmpdir, check=False)
            out = proc.stdout
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            out = _as_text(exc.stdout)
            timed_out = True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    events = [line[3:].split("|") for line in out.splitlines()
              if line.startswith("EV|")]
    RUN_CACHE[name] = (events, returncode, timed_out)
    return RUN_CACHE[name]


# ---------------------------------------------------------------------------
# Oracle replay
# ---------------------------------------------------------------------------

def _norm(value):
    """UNDEF -> None (meaning: unspecified, skip the comparison)."""
    return None if is_undef(value) else value


def _norm_reads(step_reads):
    reads = []
    for fname, recno in step_reads:
        name = "?" if is_undef(fname) else fname
        rec = "badrec" if is_undef(recno) else recno
        reads.append((name, rec))
    return reads


def _update_slots(slots, reads, step, ds_index):
    """Mirror the input-slot arithmetic of interpolate_trcdata
    (tracer_data.F90:1796-1817): reads load slots 1..interp_recs with the
    stub-encoded values; a blend folds slots 3/4 into 1/2."""
    for i, (name, rec) in enumerate(reads):
        if name == "?" or rec == "badrec":
            slots[i + 1] = None
        else:
            slots[i + 1] = float(1000 * ds_index[name] + rec)
    if step.blended:
        for pair in range(2):
            bf1, bf2 = step.blend_facts[pair]
            base = slots.get(pair + 1)
            other = slots.get(pair + 3)
            if is_undef(bf1) or base is None or other is None:
                slots[pair + 1] = None
            else:
                slots[pair + 1] = bf1 * base + bf2 * other


def _predict_data(slots, step):
    """The final field value (tracer_data.F90:1891-1899, surface path)."""
    fact1, fact2 = step.fact1, step.fact2
    if fact1 is None or is_undef(fact1):
        return None
    if slots.get(1) is None:
        return None
    if fact2 == 0:
        return fact1 * slots[1]
    if slots.get(2) is None:
        return None
    return fact1 * slots[1] + fact2 * slots[2]


def oracle_trace(name, flags=None):
    """Replay one scenario's inputs through the oracle; returns a list of
    per-op records the comparator checks the real event stream against."""
    flags = flags or {}
    spec = SCENARIOS[name]
    cal = Calendar(spec.get("calendar", "NO_LEAP"),
                   fix_calendar_mapping=flags.get("fix_calendar_mapping",
                                                  False))
    first = spec["steps"][0]
    clock = Clock(first[0], first[1], first[2], first[3], dtime=1800)
    files = [DataFile(fname, dates) for fname, dates in spec["files"]]
    ds_index = {fname: idx + 1
                for idx, (fname, _) in enumerate(spec["files"])}
    model = TracerDataModel(
        Filesystem(files, spec.get("filelists", {})), clock, cal,
        fix_search_contract=flags.get("fix_search_contract", False),
        fix_file_window=flags.get("fix_file_window", False),
        fix_unset_sentinel=flags.get("fix_unset_sentinel", False))

    trace = []
    fname, flist, dpath, dtype, cyc, fymd, ftod = spec["init"]
    try:
        model.trcdata_init(fname, filelist=flist, datapath=dpath,
                           data_type=dtype, cycle_yr=cyc, fixed_ymd=fymd,
                           fixed_tod=ftod)
    except Endrun:
        trace.append({"op": "init", "outcome": "abort"})
        return trace
    trace.append({"op": "init", "outcome": "ok"})

    slots = {}
    for i, step_date in enumerate(spec["steps"]):
        if i > 0:
            clock.set_date(step_date[0], step_date[1], step_date[2],
                           step_date[3])
        try:
            step = model.advance_trcdata()
        except Endrun:
            trace.append({"op": "advance", "outcome": "abort"})
            return trace
        except Livelock:
            trace.append({"op": "advance", "outcome": "livelock"})
            return trace
        reads = _norm_reads(step.reads)
        _update_slots(slots, reads, step, ds_index)
        tfile = model.file
        trace.append({
            "op": "advance", "outcome": "ok",
            "reads": reads,
            "curr_mod_time": _norm(tfile.curr_mod_time),
            "datatimem": _norm(tfile.datatimem),
            "datatimep": _norm(tfile.datatimep),
            "interp_recs": tfile.interp_recs,
            "curr_filename": tfile.curr_filename,
            "next_filename": tfile.next_filename,
            "datatimes": [_norm(v) for v in tfile.datatimes],
            "data": _predict_data(slots, step),
            "undef": any(rec == "badrec" or name == "?"
                         for name, rec in reads),
        })
    return trace


# ---------------------------------------------------------------------------
# Comparator
# ---------------------------------------------------------------------------

def parse_float(text):
    """Parse a Fortran-formatted real, tolerating the dropped exponent
    letter of three-digit exponents and unprintable garbage (None)."""
    token = text.strip()
    try:
        return float(token)
    except ValueError:
        mantissa_end = max(token.rfind("+"), token.rfind("-"))
        if mantissa_end > 0:
            try:
                return float(token[:mantissa_end] + "E" + token[mantissa_end:])
            except ValueError:
                return None
        return None


def _close(expected, got):
    if got is None:
        return False
    if expected < -1.0e307 and got < -1.0e307:
        # Both carry the never-read sentinel (-huge vs the model's 1e308)
        return True
    return abs(expected - got) <= 1.0e-9 + 1.0e-12 * max(abs(expected),
                                                         abs(got), 1.0)


def parse_segments(events):
    """Group the EV| stream into per-op segments."""
    segments = []
    current = None
    for event in events:
        kind = event[0]
        if kind == "op":
            current = {"word": event[1].split()[0], "reads": [],
                       "state": None, "datatimes": None, "data": None,
                       "done": False, "abort": False}
            segments.append(current)
        elif current is None:
            continue
        elif kind == "read":
            current["reads"].append((event[1], event[2]))
        elif kind == "state":
            current["state"] = event[1:]
        elif kind == "datatimes":
            current["datatimes"] = event[1:]
        elif kind == "data":
            current["data"] = event[1]
        elif kind in ("advance_done", "init_done"):
            current["done"] = True
        elif kind == "abort":
            current["abort"] = True
    return [seg for seg in segments if seg["word"] in ("init", "advance")]


def _compare_reads(opidx, rec, seg, diffs):
    expected = rec["reads"]
    got = seg["reads"]
    if len(expected) != len(got):
        diffs.append(f"op {opidx}: {len(got)} reads, expected "
                     f"{len(expected)}: {got} vs {expected}")
        return
    for j, ((ename, erec), (gname, grec)) in enumerate(zip(expected, got)):
        if ename not in ("?", gname):
            diffs.append(f"op {opidx} read {j}: file {gname}, "
                         f"expected {ename}")
        if erec == "badrec":
            if grec not in ("badrec", "closed"):
                diffs.append(f"op {opidx} read {j}: recno {grec}, "
                             "expected undefined")
        elif grec in ("badrec", "closed") or int(grec) != erec:
            diffs.append(f"op {opidx} read {j}: recno {grec}, "
                         f"expected {erec}")


def _compare_advance(opidx, rec, seg, diffs):
    _compare_reads(opidx, rec, seg, diffs)
    if rec["undef"]:
        # Downstream of an undefined value: state and data are unspecified
        # (the oracle's verdicts never depend on them either).
        return
    if not seg["done"]:
        diffs.append(f"op {opidx}: advance did not complete")
        return
    state = seg["state"]
    for label, expected, text in (
            ("curr_mod_time", rec["curr_mod_time"], state[0]),
            ("datatimem", rec["datatimem"], state[1]),
            ("datatimep", rec["datatimep"], state[2])):
        if expected is None:
            continue
        if not _close(expected, parse_float(text)):
            diffs.append(f"op {opidx}: {label} = {text}, "
                         f"expected {expected!r}")
    if rec["interp_recs"] != int(state[3]):
        diffs.append(f"op {opidx}: interp_recs = {state[3]}, "
                     f"expected {rec['interp_recs']}")
    if rec["curr_filename"] != state[4]:
        diffs.append(f"op {opidx}: curr_filename = {state[4]}, "
                     f"expected {rec['curr_filename']}")
    expected_next = rec["next_filename"] or "-"
    if expected_next != state[5]:
        diffs.append(f"op {opidx}: next_filename = {state[5]}, "
                     f"expected {expected_next}")
    for j, expected in enumerate(rec["datatimes"]):
        if expected is None:
            continue
        if not _close(expected, parse_float(seg["datatimes"][j])):
            diffs.append(f"op {opidx}: datatimes({j + 1}) = "
                         f"{seg['datatimes'][j]}, expected {expected!r}")
    if rec["data"] is not None:
        if not _close(rec["data"], parse_float(seg["data"])):
            diffs.append(f"op {opidx}: data = {seg['data']}, "
                         f"expected {rec['data']!r}")


def compare(trace, segments, timed_out):
    """Diff the oracle trace against the real event segments.
    Returns a list of mismatch descriptions (empty = protocols agree)."""
    diffs = []
    undef_tail = False
    for opidx, rec in enumerate(trace):
        if opidx >= len(segments):
            diffs.append(f"op {opidx} ({rec['op']}): missing from the "
                         "real trace")
            return diffs
        seg = segments[opidx]
        if rec["outcome"] == "abort":
            if not seg["abort"]:
                diffs.append(f"op {opidx} ({rec['op']}): expected abort, "
                             "real completed")
            return diffs
        if rec["outcome"] == "livelock":
            if not timed_out:
                diffs.append(f"op {opidx}: expected livelock (watchdog "
                             "timeout), real run terminated")
            elif seg["done"] or seg["abort"]:
                diffs.append(f"op {opidx}: expected livelock, real finished")
            return diffs
        if seg["abort"]:
            if rec.get("undef"):
                # An aborted tail downstream of undefined values is an
                # acceptable resolution of the real code's UB; the reads
                # before it still had to match.
                _compare_reads(opidx, rec, seg, diffs)
                return diffs
            diffs.append(f"op {opidx} ({rec['op']}): real aborted, oracle "
                         "completed")
            return diffs
        if rec["op"] == "advance":
            _compare_advance(opidx, rec, seg, diffs)
            undef_tail = undef_tail or rec.get("undef", False)
    if timed_out:
        diffs.append("real run hit the watchdog timeout, oracle completed")
    elif len(segments) > len(trace) and not undef_tail:
        diffs.append(f"extra ops in the real trace: {len(segments)} vs "
                     f"{len(trace)}")
    return diffs


def run_and_compare(name, flags=None):
    """One scenario end to end; returns the diff list."""
    events, _, timed_out = run_scenario(name)
    return compare(oracle_trace(name, flags), parse_segments(events),
                   timed_out)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class M4HarnessTests(unittest.TestCase):
    """Fidelity tests (real == oracle with today's semantics), ratchets
    (real vs the fix groups' target semantics) and comparator self-checks."""

    def assert_agrees(self, name, flags=None):
        """Real event stream must equal the oracle's prediction."""
        diffs = compare(oracle_trace(name, flags),
                        parse_segments(run_scenario(name)[0]),
                        run_scenario(name)[2])
        self.assertEqual(diffs, [])

    # ---- legal scenarios: real code must match the oracle exactly --------

    def test_legal_serial_two_file(self):
        """SERIAL across a file boundary: brackets, weights, prefetch and
        the documented STALE-CURR window semantics."""
        self.assert_agrees("serial_two_file")

    def test_legal_serial_filelist(self):
        """SERIAL with a real filenames_list text file."""
        self.assert_agrees("serial_filelist")

    def test_legal_cyclical_wrap(self):
        """CYCLICAL Dec->Jan wrap: wrapped bracket, no spurious re-read."""
        self.assert_agrees("cyclical_wrap")

    def test_legal_fixed_frozen(self):
        """FIXED freezes after the first read; stable rounded weight."""
        self.assert_agrees("fixed_frozen")

    def test_legal_fill_single_file(self):
        """INTERP_MISSING_MONTHS, single file: each series in its own
        year, blends in range."""
        self.assert_agrees("fill_single_file")

    def test_legal_feb29_noleap(self):
        """NO_LEAP repairs Feb 29 to Feb 28."""
        self.assert_agrees("feb29_noleap")

    # ---- finding fidelity: real code must reproduce the documented ------
    # ---- defects exactly as the oracle (fix flags off) models them ------
    # These are the oracle's transcription check: when a fix group lands,
    # the matching test here starts failing ("did the code get fixed?") --
    # retire it together with the oracle's pre-fix scenario.

    def test_finputs2_fidelity_fill_two_file(self):
        """F-INPUTS-2: the second call's fill path addresses 1980/1990
        records instead of 1990/2000 and the blend extrapolates."""
        self.assert_agrees("fill_two_file_wrong_years")

    def test_finputs3a_fidelity_livelock(self):
        """F-INPUTS-3a: the search loop never exits on a one-record cycle
        year (observable: the fresh process survives to its watchdog)."""
        self.assert_agrees("cyclical_single_record_livelock")

    def test_finputs3b_fidelity_undefined_recnos(self):
        """F-INPUTS-3b: stale times_found skips the guards and the series
        reads carry undefined record numbers (pinned by -finit-integer)."""
        self.assert_agrees("fill_decadal_undefined")

    def test_finputs1_fidelity_feb29_gregorian(self):
        """F-INPUTS-1 (stub-mediated): GREGORIAN + non-leap cycle year
        aborts on the mapped Feb 29."""
        self.assert_agrees("feb29_gregorian_aborts")

    def test_finputs4_fidelity_unset_filelist(self):
        """F-INPUTS-4: the 'UNSET' sentinel is opened as a real filelist
        and the run aborts."""
        self.assert_agrees("unset_filelist_aborts")

    # ---- defect ratchets: the fix groups' target semantics --------------
    # Each must FAIL until its fix group lands; the fix flips it to an
    # unexpected success, which fails the harness until the ratchet, the
    # fidelity test above and the oracle fix flag retire together.

    @unittest.expectedFailure
    def test_ratchet_trc_file_window(self):
        """FG trc-file-window: a normalized window reads 1990/2000 from
        the advanced current file."""
        self.assert_agrees("fill_two_file_wrong_years",
                           RATCHET_FLAGS["fill_two_file_wrong_years"])

    @unittest.expectedFailure
    def test_ratchet_trc_search_contract_livelock(self):
        """FG trc-search-contract: a sub-two-record cycle window aborts
        loudly instead of livelocking."""
        self.assert_agrees("cyclical_single_record_livelock",
                           RATCHET_FLAGS["cyclical_single_record_livelock"])

    @unittest.expectedFailure
    def test_ratchet_trc_search_contract_decadal(self):
        """FG trc-search-contract: the decadal fill aborts loudly instead
        of proceeding with undefined indices."""
        self.assert_agrees("fill_decadal_undefined",
                           RATCHET_FLAGS["fill_decadal_undefined"])

    @unittest.expectedFailure
    def test_ratchet_calendar_mapping(self):
        """FG calendar-date-mapping: the CAM-style repair clamps Feb 29
        and the run continues."""
        self.assert_agrees("feb29_gregorian_aborts",
                           RATCHET_FLAGS["feb29_gregorian_aborts"])

    @unittest.expectedFailure
    def test_ratchet_unset_sentinel(self):
        """FG trc-file-window (UNSET normalization): the increment path
        opens the next file and the run continues."""
        self.assert_agrees("unset_filelist_aborts",
                           RATCHET_FLAGS["unset_filelist_aborts"])

    # ---- harness self-checks ---------------------------------------------

    def test_comparator_detects_mutations(self):
        """Evidence the equality check can fail: tampering with the real
        event stream in each compared dimension must produce a diff."""
        events, _, timed_out = run_scenario("cyclical_wrap")
        trace = oracle_trace("cyclical_wrap")
        self.assertEqual(compare(trace, parse_segments(events), timed_out),
                         [])

        def mutated(transform):
            return compare(trace, parse_segments(transform(events)),
                           timed_out)

        self.assertTrue(mutated(
            lambda evs: [e for e in evs if e[0] != "read"]),
            "dropped reads not detected")
        self.assertTrue(mutated(
            lambda evs: [e[:2] + ["99"] if e[0] == "read" else e
                         for e in evs]),
            "corrupted record numbers not detected")
        self.assertTrue(mutated(
            lambda evs: [[e[0], e[1], "0.0"] + e[3:] if e[0] == "state"
                         else e for e in evs]),
            "corrupted bracket state not detected")
        self.assertTrue(mutated(
            lambda evs: [[e[0], "0.0"] if e[0] == "data" else e
                         for e in evs]),
            "corrupted field values not detected")
        self.assertTrue(mutated(
            lambda evs: evs + [["abort", "endrun"]]),
            "forged abort not detected")

    def test_finputs4_abort_exit_code(self):
        """Pin the abort observable: the UNSET scenario stops with the
        stub endrun's distinct exit code, no message matching."""
        _, returncode, timed_out = run_scenario("unset_filelist_aborts")
        self.assertFalse(timed_out)
        self.assertEqual(returncode, ABORT_EXIT_CODE,
                         "expected the endrun exit code - has the UNSET "
                         "normalization landed? retire this with the "
                         "F-INPUTS-4 ratchet")


def main():
    """Build, run the suite, clean up."""
    print("building driver (gfortran) ...")
    try:
        build_driver()
    except (RuntimeError, OSError) as exc:
        print(f"run_m4_harness: FAILED - {exc}")
        return 2
    try:
        result = unittest.main(exit=False, verbosity=2).result
    finally:
        if BUILD_DIR:
            shutil.rmtree(BUILD_DIR, ignore_errors=True)
    if not result.wasSuccessful():
        print("run_m4_harness: FAILED")
        return 1
    print(f"run_m4_harness: ok ({result.testsRun} tests, "
          f"expected failures={len(result.expectedFailures)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

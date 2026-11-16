#!/usr/bin/env python3
"""M2 differential harness: real hist_file_t vs the executable reference model.

Builds the real CAM-SIMA history-volume code (cam_hist_file.F90,
cam_history_support.F90, the ESMCI history buffer library, cam_filenames)
against recording stubs for PIO, the grid layer and the time manager, then
drives it through scenario op scripts and compares the recorded events
against reference_model.py - the FG-3 (fixed) protocol of the M2 TLA+
model made executable.

The three defect scenarios are the TLC counterexamples of
test/verification/models/m2_history replayed as concrete operation
sequences; while FG-3 is unfixed they are expectedFailure ratchets, so the
fix PRs must flip them (an unexpected success fails this harness).  Legal
scenarios must match the reference exactly.  A comparator mutation check
provides the evidence that the equality check itself can fail.

Each scenario runs the driver in a fresh process: F-HIST-5's observable is
a write from never-initialized heap memory, which a fresh process makes
deterministic (first allocation of the buffer, so its contents cannot be a
stale fill pattern from an earlier scenario).

Requires gfortran.  Guarantee statement in README.md next to this script.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reference_model
from reference_model import FILLVALUE

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HARNESS_DIR, "..", "..", "..", ".."))
SCENARIO_DIR = os.path.join(HARNESS_DIR, "scenarios")

STUBS = [
    "shr_kind_mod", "runtime_obj", "cam_logfile", "physconst",
    "shr_string_mod", "shr_nl_mod", "mpi", "spmd_utils", "perf_mod",
    "cam_control_mod", "cam_initfiles", "harness_events", "cam_abortutils",
    "time_manager", "pio", "cam_pio_utils", "cam_grid_support",
]

BUFFER_LIB = [
    "src/history/buffers/src/hash/hist_hashable.F90",
    "src/history/buffers/src/util/hist_msg_handler.F90",
    "src/history/buffers/src/hist_buffer.F90",
    "src/history/buffers/src/hist_field.F90",
    "src/history/buffers/src/hash/hist_hash_table.F90",
    "src/history/buffers/src/hist_api.F90",
]

REAL_SOURCES = [
    "src/core_utils/string_core_utils.F90",
    "src/utils/string_utils.F90",
    "src/utils/datetime.F90",
    "src/utils/cam_filenames.F90",
    "src/history/cam_history_support.F90",
    "src/history/cam_hist_file.F90",
]

BUILD_DIR = None
DRIVER = None


def build_driver():
    """Compile the driver once for the whole run; returns executable path."""
    global BUILD_DIR, DRIVER
    BUILD_DIR = tempfile.mkdtemp(prefix="m2_harness_")
    fc = os.environ.get("FC", "gfortran")
    base = [fc, "-c", "-ffree-line-length-none", "-O0", "-g", "-J", BUILD_DIR]
    objs = []

    def compile_one(path, extra=()):
        obj = os.path.join(
            BUILD_DIR, os.path.basename(path).replace(".F90", ".o"))
        cmd = base + list(extra) + [path, "-o", obj]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=BUILD_DIR)
        if proc.returncode != 0:
            raise RuntimeError("compile failed: {0}\n{1}".format(
                path, proc.stderr))
        objs.append(obj)

    for stub in STUBS:
        compile_one(os.path.join(HARNESS_DIR, "stubs", stub + ".F90"))
    for rel in BUFFER_LIB + REAL_SOURCES:
        extra = ()
        if rel.endswith("cam_hist_file.F90"):
            # Its namelist readers call F77-interface MPI_Bcast with mixed
            # argument types, as in production MPI builds
            extra = ("-fallow-argument-mismatch",)
        compile_one(os.path.join(REPO_ROOT, rel), extra)
    compile_one(os.path.join(HARNESS_DIR, "driver.F90"))

    DRIVER = os.path.join(BUILD_DIR, "m2_driver")
    proc = subprocess.run([fc, "-o", DRIVER] + objs, capture_output=True,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError("link failed:\n" + proc.stderr)
    return DRIVER


def run_driver(ops_text):
    """Run one scenario in a fresh process; return (events, exit code)."""
    proc = subprocess.run([DRIVER], input=ops_text, capture_output=True,
                          text=True, timeout=60)
    events = []
    for line in proc.stdout.splitlines():
        if line.startswith("EV|"):
            events.append(line[3:].split("|"))
    return events, proc.returncode


def split_kind(name, unit):
    """Infer a created file's split from the unit+suffix naming convention
    ('i' instantaneous / 'a' accumulated), a stable identifier assigned at
    cam_hist_file.F90:186-187."""
    if unit + "i" in name:
        return "i"
    if unit + "a" in name:
        return "a"
    return "?"


def compare(ops_text, events, unit="h1"):
    """Diff real driver events against the reference model's prediction.
    Returns a list of mismatch descriptions (empty = protocols agree)."""
    expected = reference_model.predict(ops_text)
    scenario_fields = {args[0] for op, args in
                       reference_model.parse_ops(ops_text) if op == "field"}
    diffs = []

    files = {}          # handle -> (name, kind)
    opens = []          # list of sorted kinds per open "round"
    open_defvars = []   # set of (kind, field) per open round
    writes = []         # (field, kind, frame, values)
    names_created = []
    aborted = False

    for ev in events:
        kind = ev[0]
        if kind == "createfile":
            handle, name = ev[1], ev[2]
            files[handle] = (name, split_kind(name, unit))
            names_created.append(name)
            # Group concurrent split creates into one open round: a new
            # round starts when the previous round saw a write already
            if not opens or opens[-1]["done"]:
                opens.append({"kinds": [], "defs": set(), "done": False})
            opens[-1]["kinds"].append(files[handle][1])
        elif kind == "defvar":
            handle, var = ev[1], ev[2]
            if var in scenario_fields and opens:
                opens[-1]["defs"].add((files[handle][1], var))
        elif kind == "writefield":
            handle, var, frame = ev[1], ev[2], int(ev[3])
            values = [float(v) for v in ev[4:]]
            if var in scenario_fields:
                writes.append((var, files[handle][1], len(opens) - 1,
                               frame, values))
            if opens:
                opens[-1]["done"] = True
        elif kind == "closefile":
            if opens:
                opens[-1]["done"] = True
        elif kind == "abort":
            aborted = True

    if aborted:
        diffs.append("driver aborted (endrun)")

    # File-create rounds: kinds per open must match the model
    real_opens = [sorted(o["kinds"]) for o in opens]
    if real_opens != expected.opens:
        diffs.append("open rounds differ: real={0} expected={1}".format(
            real_opens, expected.opens))

    # Name uniqueness across the run (the M2 NoFilenameClobber invariant)
    dupes = {n for n in names_created if names_created.count(n) > 1}
    if dupes:
        diffs.append("file name(s) reused: {0}".format(sorted(dupes)))

    # Field definitions per open round
    real_defs = [o["defs"] for o in opens]
    exp_defs = [{(s, f) for (s, f) in dv} for dv in expected.defvars]
    if real_defs != exp_defs:
        diffs.append("field defvars differ: real={0} expected={1}".format(
            real_defs, exp_defs))

    # Field writes: same set of (field, split, generation, frame) with
    # values matching the expected class (data value or fill, all columns)
    real_idx = {(f, s, g, fr): vals for (f, s, g, fr, vals) in writes}
    for (fname, split, gen, frame, wkind, val) in expected.writes:
        key = (fname, split, gen, frame)
        if key not in real_idx:
            diffs.append("missing write {0}".format(key))
            continue
        vals = real_idx.pop(key)
        if any(abs(v - val) > 1e-9 * max(abs(val), 1.0) for v in vals):
            diffs.append(
                "write {0}: expected {1} value {2}, got {3}".format(
                    key, wkind, val, vals))
    for key in real_idx:
        diffs.append("unexpected write {0}".format(key))

    return diffs


def load_scenario(name):
    with open(os.path.join(SCENARIO_DIR, name + ".ops")) as handle:
        return handle.read()


class M2HarnessTests(unittest.TestCase):

    def run_and_compare(self, scenario):
        ops = load_scenario(scenario)
        events, _ = run_driver(ops)
        self.assertTrue(events, "driver produced no events")
        diffs = compare(ops, events)
        self.assertEqual(diffs, [])

    # ---- legal scenarios: real code must match the reference exactly ----

    def test_legal_inst_onestep(self):
        """Unconditional inst fields at 1*nsteps with rollover: the shape
        of every shipped 1*nsteps testmod."""
        self.run_and_compare("legal_inst_onestep")

    def test_legal_accum_interval(self):
        """avg/min/max fields over multi-step intervals, sampled every
        step: accumulated values match the reference arithmetic."""
        self.run_and_compare("legal_accum_interval")

    def test_legal_mixed_splits(self):
        """Mixed inst+avg volume at an interval cadence routes each field
        to its own split file."""
        self.run_and_compare("legal_mixed_splits")

    # ---- defect ratchets: TLC counterexamples replayed on real code ----
    # Each must FAIL until its FG-3 fix lands; the fix flips it to an
    # unexpected success, which fails the harness until the marker and the
    # corresponding model scenario are updated together.

    @unittest.expectedFailure
    def test_fhist1_avg_onestep(self):
        """F-HIST-1 (TLC: RoutingComplete/NoDroppedData): avg-only volume
        at 1*nsteps loses every field."""
        self.run_and_compare("fhist1_avg_onestep")

    @unittest.expectedFailure
    def test_fhist5_unsampled_interval(self):
        """F-HIST-5 (TLC: NoUndefinedData): an unsampled interval must
        write _FillValue, not uninitialized memory."""
        self.run_and_compare("fhist5_unsampled_interval")

    @unittest.expectedFailure
    def test_fhist2_filename_reuse(self):
        """F-HIST-2 (TLC: NoFilenameClobber): a spec without %s plus
        mfilt=1 reuses the same file name within a run."""
        self.run_and_compare("fhist2_filename_reuse")

    # ---- harness self-checks -------------------------------------------

    def test_comparator_detects_mutations(self):
        """Evidence the equality check can fail: tampering with the real
        event stream in each observable dimension must produce a diff."""
        ops = load_scenario("legal_inst_onestep")
        events, _ = run_driver(ops)
        self.assertEqual(compare(ops, events), [])

        dropped_def = [e for e in events
                       if not (e[0] == "defvar" and e[2] == "F1")]
        self.assertTrue(compare(ops, dropped_def))

        dropped_write = [e for e in events if e[0] != "writefield"]
        self.assertTrue(compare(ops, dropped_write))

        corrupted = [e[:4] + ["0.0"] * (len(e) - 4)
                     if e[0] == "writefield" else e for e in events]
        self.assertTrue(compare(ops, corrupted))

    def test_fhist5_writes_nonfill_garbage(self):
        """Pin the concrete F-HIST-5 observable: the unsampled frame's
        values are not _FillValue (they are whatever the heap held)."""
        ops = load_scenario("fhist5_unsampled_interval")
        events, _ = run_driver(ops)
        frames = [e for e in events if e[0] == "writefield" and e[2] == "F1"]
        self.assertEqual(len(frames), 2)
        unsampled = [float(v) for v in frames[1][4:]]
        self.assertTrue(all(abs(v - FILLVALUE) > 1.0 for v in unsampled),
                        "unsampled frame unexpectedly wrote _FillValue - "
                        "has FG-3 landed? retire this ratchet")


def main():
    print("building driver (gfortran) ...")
    try:
        build_driver()
    except (RuntimeError, OSError) as exc:
        print("run_m2_harness: FAILED - {0}".format(exc))
        return 2
    try:
        result = unittest.main(exit=False, verbosity=2).result
    finally:
        if BUILD_DIR:
            shutil.rmtree(BUILD_DIR, ignore_errors=True)
    if not result.wasSuccessful():
        print("run_m2_harness: FAILED")
        return 1
    print("run_m2_harness: ok ({0} tests, expected failures={1})".format(
        result.testsRun, len(result.expectedFailures)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

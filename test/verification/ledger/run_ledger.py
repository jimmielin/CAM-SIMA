#!/usr/bin/env python3
"""capgen v0-vs-v1 assumption ledger: one stub-host fixture, both generators.

Stages the fixture in fixtures/ for a framework checkout, generates caps
with that framework's own ccpp_capgen CLI, compiles them with gfortran,
drives the generated suite through its phases in three scenarios (clean,
mid-run scheme failure, phase-protocol violation), and checks the numbered
assumptions A1..A7 of README.md against the recorded EV| event streams.

v0 is the ccpp_framework submodule pin; v1 is a checkout of the capgen-v1
framework branch found via $CAPGEN_V1_ROOT (or a conventional local path)
and verified against the recorded SHA pin.  The known v0->v1 interface
divergences (table taxonomy, control table, entry-point surface, CLI and
datatable reports) are absorbed here exactly the way CAM-SIMA's
capgen-v1 branch absorbs them, and are documented as ledger entries
D1..D6 in README.md; every behavioural assumption is then required to
hold identically on both sides, so a v1 change surfaces as a named
assumption failure rather than a downstream mystery.

Admission evidence: the test_admission_* methods doctor the real event
streams in every observable dimension and require each checker to fire.

Requires gfortran.  Guarantee statement in README.md next to this script.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

LEDGER_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(LEDGER_DIR, "fixtures")
REPO_ROOT = os.path.abspath(os.path.join(LEDGER_DIR, "..", "..", ".."))

# The capgen-v1 framework commit the v1 expectations were recorded at
# (NCAR/ccpp-framework feature/capgen-v1); CAM-SIMA's capgen-v1 branch
# pins the same commit in .gitmodules.
V1_PIN = "fcd4251da77801fd59549ae9d767121fce53bce4"

# The fixture suite, as declared in fixtures/ledger_suite.xml.
GROUP_SCHEMES = (("alpha", ("ldg_order_a", "ldg_const")),
                 ("beta", ("ldg_order_b", "ldg_order_c")))
SCHEME_PHASES = {
    "ldg_order_a": {"init", "timestep_init", "run", "timestep_final",
                    "final"},
    "ldg_const": {"register", "init", "run"},
    "ldg_order_b": {"init", "run", "final"},
    "ldg_order_c": {"run"},
}
TRACKED = ("ldg_host_wet_mixing_ratio", "ldg_host_dry_mixing_ratio",
           "ldg_cloud_dry_mixing_ratio", "ldg_dyn_mixing_ratio")

# Observed host-side constituent index order (A5), recorded per version.
# Not registration order on either side: v0 orders by its hash-table
# iteration; v1 happens to coincide on this four-constituent fixture.
# The CAM-SIMA-scale reordering documented for capgen-v1 (round-off
# answer changes) does not reproduce at this fixture size - a declared
# blind spot of the checked domain (README.md, A5).
ORDER_BASELINE = {
    "v0": ["ldg_dyn_mixing_ratio", "ldg_cloud_dry_mixing_ratio",
           "ldg_host_dry_mixing_ratio", "ldg_host_wet_mixing_ratio"],
    "v1": ["ldg_dyn_mixing_ratio", "ldg_cloud_dry_mixing_ratio",
           "ldg_host_dry_mixing_ratio", "ldg_host_wet_mixing_ratio"],
}

NSTEPS = 3
FAIL_STEP = 2
FAIL_CODE = 42  # fixture-owned errflg set by ldg_order_b

# Lazily-populated per-version build/run cache:
#   {"exe": path, "events": {scenario: [event, ...]}, "builddir": path}
BUILDS = {}
KEEP_BUILD = False


# ---------------------------------------------------------------------------
# Framework location and per-version invocation
# ---------------------------------------------------------------------------

def find_framework(version):
    """Return the framework root for <version>, or None if unavailable."""
    if version == "v0":
        root = os.path.join(REPO_ROOT, "ccpp_framework")
        probe = os.path.join(root, "scripts", "ccpp_capgen.py")
        return root if os.path.exists(probe) else None
    root = os.environ.get("CAPGEN_V1_ROOT", "")
    if not root:
        root = os.path.expanduser("~/devel/ccpp-framework-capgen-v1")
    probe = os.path.join(root, "capgen", "ccpp_capgen.py")
    return root if os.path.exists(probe) else None


def v1_sha_warning(root):
    """Warn (not fail) when the v1 checkout drifted off the recorded pin."""
    try:
        proc = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        sha = proc.stdout.strip()
    except OSError:
        return
    if proc.returncode == 0 and sha and sha != V1_PIN:
        print("run_ledger: WARNING capgen-v1 checkout at {0}; the ledger "
              "expectations were recorded at {1}".format(sha[:9],
                                                         V1_PIN[:9]))


def stage_fixture(version, stage_dir):
    """Copy the fixture into <stage_dir> in the staging the given capgen
    generation accepts; the differences mirror CAM-SIMA's capgen-v1
    branch (ledger entries D1/D2 in README.md)."""
    names = ["ledger_events.F90", "ledger_host_mod.F90",
             "ledger_host_mod.meta", "ledger_suite.xml"]
    for grp, schemes in GROUP_SCHEMES:
        for scheme in schemes:
            names += [scheme + ".F90", scheme + ".meta"]
    for name in names:
        shutil.copy(os.path.join(FIXTURE_DIR, name), stage_dir)
    if version == "v0":
        # v0: type=host table paired with the driver source.
        shutil.copy(os.path.join(FIXTURE_DIR, "ledger_host.meta"),
                    stage_dir)
        shutil.copy(os.path.join(FIXTURE_DIR, "main_v0.F90"),
                    os.path.join(stage_dir, "ledger_host.F90"))
        return ["ledger_host_mod.meta", "ledger_host.meta"]
    # v1: host module tables are 'type = host' (the same parse-time
    # rewrite CAM-SIMA's capgen_compat shim applies), and the control
    # variables live in a type=control table with no backing Fortran.
    mod_meta = os.path.join(stage_dir, "ledger_host_mod.meta")
    with open(mod_meta) as src:
        text = src.read()
    with open(mod_meta, "w") as dst:
        dst.write(text.replace("  type = module\n", "  type = host\n"))
    shutil.copy(os.path.join(FIXTURE_DIR, "ledger_control.meta"), stage_dir)
    shutil.copy(os.path.join(FIXTURE_DIR, "main_v1.F90"),
                os.path.join(stage_dir, "ledger_host.F90"))
    return ["ledger_host_mod.meta", "ledger_control.meta"]


def generate_caps(version, fw_root, stage_dir, out_dir, host_metas):
    """Run the framework's own ccpp_capgen CLI on the staged fixture."""
    if version == "v0":
        capgen = os.path.join(fw_root, "scripts", "ccpp_capgen.py")
        extra = []
    else:
        capgen = os.path.join(fw_root, "capgen", "ccpp_capgen.py")
        # The flags CAM-SIMA's capgen_compat shim enables by default.
        extra = ["--legacy-mode", "--legacy-auto-clone-constituents"]
    schemes = ",".join(os.path.join(stage_dir, s + ".meta")
                       for _, ss in GROUP_SCHEMES for s in ss)
    hosts = ",".join(os.path.join(stage_dir, m) for m in host_metas)
    cmd = [sys.executable, capgen,
           "--host-files", hosts,
           "--scheme-files", schemes,
           "--suites", os.path.join(stage_dir, "ledger_suite.xml"),
           "--host-name", "ledger_host",
           "--output-root", out_dir,
           "--kind-type", "kind_phys=REAL64"] + extra
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=stage_dir, timeout=300)
    datatable = os.path.join(out_dir, "datatable.xml")
    if proc.returncode != 0 or not os.path.exists(datatable):
        raise RuntimeError("{0} capgen failed:\n{1}\n{2}".format(
            version, proc.stdout[-2000:], proc.stderr[-2000:]))
    return datatable


def cap_file_list(version, fw_root, datatable):
    """The Fortran the build must compile, from the framework's own
    datatable tool.  v0 reports it as --ccpp-files; v1 split that into
    --capgen-files plus --dependencies (ledger entry D3)."""
    if version == "v0":
        datafile = os.path.join(fw_root, "scripts", "ccpp_datafile.py")
        reports = [["--ccpp-files"]]
    else:
        datafile = os.path.join(fw_root, "capgen", "ccpp_datafile.py")
        reports = [["--capgen-files"], ["--dependencies"]]
    files = []
    for report in reports:
        proc = subprocess.run([sys.executable, datafile, datatable]
                              + report, capture_output=True, text=True,
                              timeout=60)
        if proc.returncode != 0:
            raise RuntimeError("ccpp_datafile {0} failed:\n{1}".format(
                report[0], proc.stderr[-1000:]))
        files += [f for f in proc.stdout.strip().split(",") if f]
    return files


def build_fixture(version):
    """Stage, generate, compile and link one version; cache the result."""
    fw_root = find_framework(version)
    build_root = tempfile.mkdtemp(prefix="ledger_{0}_".format(version))
    stage_dir = os.path.join(build_root, "stage")
    out_dir = os.path.join(build_root, "ccpp")
    obj_dir = os.path.join(build_root, "build")
    for path in (stage_dir, out_dir, obj_dir):
        os.makedirs(path)
    host_metas = stage_fixture(version, stage_dir)
    datatable = generate_caps(version, fw_root, stage_dir, out_dir,
                              host_metas)
    sources = cap_file_list(version, fw_root, datatable)
    sources += [os.path.join(stage_dir, "ledger_events.F90"),
                os.path.join(stage_dir, "ledger_host_mod.F90")]
    sources += [os.path.join(stage_dir, s + ".F90")
                for _, ss in GROUP_SCHEMES for s in ss]
    sources += [os.path.join(stage_dir, "ledger_host.F90")]
    seen = set()
    unique = []
    for src in sources:
        real = os.path.realpath(src)
        if real not in seen:
            seen.add(real)
            unique.append(src)

    fc = os.environ.get("FC", "gfortran")
    base = [fc, "-c", "-ffree-line-length-none", "-O0", "-g", "-J", "."]
    pending = list(unique)
    objs = []
    errors = {}
    # Multi-pass compilation resolves module order without a build system.
    for _ in range(len(unique)):
        still = []
        for src in pending:
            obj = os.path.basename(src)[:-4] + ".o"
            proc = subprocess.run(base + [src, "-o", obj],
                                  capture_output=True, text=True,
                                  cwd=obj_dir)
            if proc.returncode != 0:
                still.append(src)
                errors[src] = proc.stderr
            else:
                objs.append(obj)
        if not still:
            break
        if len(still) == len(pending):
            raise RuntimeError("compile stalled:\n" + "\n".join(
                "{0}:\n{1}".format(s, errors[s][-800:]) for s in still))
        pending = still
    exe = os.path.join(obj_dir, "ledger_main")
    proc = subprocess.run([fc, "-o", exe] + objs, capture_output=True,
                          text=True, cwd=obj_dir)
    if proc.returncode != 0:
        raise RuntimeError("link failed:\n" + proc.stderr[-1500:])
    return {"exe": exe, "builddir": build_root, "events": {}}


def run_scenario(version, scenario):
    """Run one scenario in a fresh process; cache and return its events."""
    build = BUILDS[version]
    if scenario in build["events"]:
        return build["events"][scenario]
    args = {"clean": [str(NSTEPS)],
            "fail": [str(NSTEPS), str(FAIL_STEP)],
            "violate": [str(NSTEPS), "0", "violate"]}[scenario]
    proc = subprocess.run([build["exe"]] + args, capture_output=True,
                          text=True, timeout=120)
    events = [line[3:].split("|") for line in proc.stdout.splitlines()
              if line.startswith("EV|")]
    if not events:
        raise RuntimeError("{0}/{1}: driver produced no events:\n{2}".format(
            version, scenario, proc.stderr[-800:]))
    build["events"][scenario] = events
    return events


# ---------------------------------------------------------------------------
# Checkers: pure functions from event streams to violation lists, so the
# admission tests can run them on doctored streams.
# ---------------------------------------------------------------------------

def schemes_with(phase):
    return [s for _, ss in GROUP_SCHEMES for s in ss
            if phase in SCHEME_PHASES[s]]


def expected_calls(nsteps, fail_at=0):
    """The (scheme, phase, step) sequence the SDF implies, including the
    truncation a mid-run failure causes."""
    seq = [(s, "register", 0) for s in schemes_with("register")]
    seq += [(s, "init", 0) for s in schemes_with("init")]
    for step in range(1, nsteps + 1):
        seq += [(s, "timestep_init", step)
                for s in schemes_with("timestep_init")]
        for _, schemes in GROUP_SCHEMES:
            for scheme in schemes:
                if "run" not in SCHEME_PHASES[scheme]:
                    continue
                seq.append((scheme, "run", step))
                if scheme == "ldg_order_b" and step == fail_at:
                    return seq  # later schemes and phases must not run
        seq += [(s, "timestep_final", step)
                for s in schemes_with("timestep_final")]
    seq += [(s, "final", -1) for s in schemes_with("final")]
    return seq


def observed_calls(events):
    return [(e[1], e[2], int(e[3])) for e in events if e[0] == "call"]


def check_call_order(events, nsteps, fail_at=0):
    """A2 (+A3's skip side): scheme calls match the SDF-implied order."""
    want = expected_calls(nsteps, fail_at)
    got = observed_calls(events)
    if got != want:
        return ["call sequence mismatch:\n  want: {0}\n  got:  {1}".format(
            want, got)]
    return []


def check_error_propagation(events, fail_at):
    """A3: the injected errflg surfaces to the host intact, with a
    message, and the driver abort is honored (nothing runs after)."""
    out = []
    host = [(i, e) for i, e in enumerate(events) if e[0] == "host"]
    failing = [(i, e) for i, e in host if int(e[2]) != 0]
    if len(failing) != 1:
        out.append("expected exactly one failing host call, got {0}".format(
            [e for _, e in failing]))
        return out
    idx, event = failing[0]
    if event[1] != "run:beta":
        out.append("failure surfaced from '{0}', not run:beta".format(
            event[1]))
    if int(event[2]) != FAIL_CODE:
        out.append("errflg {0} reached the host, scheme set {1}".format(
            event[2], FAIL_CODE))
    if event[3] == "-":
        out.append("errmsg did not reach the host")
    tail = [e for e in events[idx + 1:]]
    if tail != [["end", "aborted"]]:
        out.append("events continued after the failure: {0}".format(tail))
    calls = observed_calls(events)
    if ("ldg_order_c", "run", fail_at) in calls:
        out.append("ldg_order_c ran after ldg_order_b failed")
    return out


def check_const_identity(events, nsteps):
    """A4: host-side and scheme-side index lookups agree, the properties
    vector matches, and the markers written through the scheme-side
    index and the promoted slice both land at the host-side index."""
    out = []
    host_idx = {e[2]: int(e[3]) for e in events
                if e[0] == "idx" and e[1] == "host"}
    scheme_lookups = [(e[2], int(e[3])) for e in events
                      if e[0] == "idx" and e[1] == "scheme"]
    if set(host_idx) != set(TRACKED):
        out.append("host lookups missing: {0}".format(
            set(TRACKED) - set(host_idx)))
        return out
    if sorted(host_idx.values()) != list(range(1, len(TRACKED) + 1)):
        out.append("host indices not a 1..{0} permutation: {1}".format(
            len(TRACKED), host_idx))
    per_step = [(name, host_idx[name]) for name in TRACKED]
    if scheme_lookups != per_step * nsteps:
        out.append("scheme-side lookups disagree with host side:"
                   " {0}".format(scheme_lookups))
    meta = {int(e[1]): e[2] for e in events if e[0] == "constmeta"}
    for name, idx in host_idx.items():
        if meta.get(idx) != name:
            out.append("props at index {0} say '{1}', host lookup says "
                       "'{2}'".format(idx, meta.get(idx), name))
    vals = {e[2]: float(e[3]) for e in events
            if e[0] == "val" and e[1] == "constval"}
    want = {TRACKED[0]: 1000.0 + nsteps,
            TRACKED[1]: 2000.0 + nsteps,
            TRACKED[2]: 3000.0 + nsteps + 0.5,  # slice-aliasing probe
            TRACKED[3]: 4000.0 + nsteps}
    for name, expect in want.items():
        if vals.get(name) != expect:
            out.append("marker for {0}: want {1}, host read {2}".format(
                name, expect, vals.get(name)))
    return out


def check_const_order(events, version):
    """A5: the host-side constituent index order matches the recorded
    per-version baseline."""
    meta = sorted((int(e[1]), e[2]) for e in events if e[0] == "constmeta")
    order = [name for _, name in meta]
    if order != ORDER_BASELINE[version]:
        return ["constituent order changed: baseline {0}, got {1}".format(
            ORDER_BASELINE[version], order)]
    return []


def check_data_flow(events, nsteps):
    """A2's data side and A7: schemes see the host-module value set for
    each step, and the suite-internal marker crosses group boundaries."""
    out = []
    temps = [float(e[3]) for e in events
             if e[0] == "val" and e[1] == "a_run"]
    if temps != [300.0 + s for s in range(1, nsteps + 1)]:
        out.append("ldg_order_a saw temp {0}".format(temps))
    markers = [float(e[3]) for e in events
               if e[0] == "val" and e[1] == "b_run"]
    if markers != [10.0 * s + 1 for s in range(1, nsteps + 1)]:
        out.append("ldg_order_b saw marker {0}".format(markers))
    return out


def check_protocol_guard(events):
    """A6: a run call before any timestep_init is rejected by the
    generated cap and no scheme run executes."""
    out = []
    probe = [e for e in events if e[0] == "host"
             and e[1] == "run_before_timestep_init"]
    if len(probe) != 1 or int(probe[0][2]) == 0:
        out.append("protocol violation not rejected: {0}".format(probe))
    if [e for e in observed_calls(events) if e[1] == "run"]:
        out.append("schemes ran inside the rejected run call")
    return out


def check_clean_host_calls(events, version):
    """A1's runtime side: every host-cap call of the clean scenario
    succeeds, the suite exposes the SDF groups in order, and the
    choreography completes."""
    out = []
    bad = [e for e in events if e[0] == "host" and int(e[2]) != 0]
    if bad:
        out.append("host-cap calls failed: {0}".format(bad))
    parts = [e[1] for e in events if e[0] == "parts"]
    if parts != [",".join(g for g, _ in GROUP_SCHEMES)]:
        out.append("suite part list: {0}".format(parts))
    begin = [e[1] for e in events if e[0] == "begin"]
    if begin != ["api=" + version]:
        out.append("driver api tag: {0}".format(begin))
    if [e for e in events if e[0] == "end"] != [["end", "clean"]]:
        out.append("clean scenario did not end clean")
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class LedgerChecks:
    """Assumption checks shared by both framework generations."""
    version = None

    @classmethod
    def setUpClass(cls):
        if find_framework(cls.version) is None:
            if cls.version == "v1":
                raise unittest.SkipTest(
                    "capgen-v1 checkout not found (set CAPGEN_V1_ROOT to a "
                    "checkout of NCAR/ccpp-framework at {0})".format(
                        V1_PIN[:9]))
            raise unittest.SkipTest(
                "ccpp_framework submodule not populated (run "
                "bin/git-fleximod update ccpp-framework)")
        if cls.version == "v1":
            v1_sha_warning(find_framework("v1"))
        if cls.version not in BUILDS:
            BUILDS[cls.version] = build_fixture(cls.version)

    def events(self, scenario):
        return run_scenario(self.version, scenario)

    def test_a1_generate_build_run(self):
        """A1: capgen accepts the fixture, the datatable file list builds
        and links, and every host-cap call of a clean run succeeds."""
        self.assertEqual([], check_clean_host_calls(
            self.events("clean"), self.version))

    def test_a2_call_order_clean(self):
        """A2: phase and scheme order follow the SDF through a clean
        multi-step run."""
        self.assertEqual([], check_call_order(self.events("clean"), NSTEPS))

    def test_a2_data_flow(self):
        """A2/A7: host-module data reaches schemes per step and the
        marker crosses the alpha->beta group boundary."""
        self.assertEqual([], check_data_flow(self.events("clean"), NSTEPS))

    def test_a3_error_propagation(self):
        """A3: a failing scheme truncates its group and the suite, and
        its errflg reaches the host intact."""
        events = self.events("fail")
        self.assertEqual([], check_call_order(events, NSTEPS, FAIL_STEP))
        self.assertEqual([], check_error_propagation(events, FAIL_STEP))

    def test_a4_constituent_identity(self):
        """A4: host/scheme index agreement, property round-trip, and
        marker placement incl. the promoted-slice aliasing probe."""
        self.assertEqual([], check_const_identity(
            self.events("clean"), NSTEPS))

    def test_a5_constituent_order(self):
        """A5: host-side constituent order matches the recorded
        per-version baseline."""
        self.assertEqual([], check_const_order(
            self.events("clean"), self.version))

    def test_a6_phase_protocol_guard(self):
        """A6: the generated cap rejects run before timestep_init."""
        self.assertEqual([], check_protocol_guard(self.events("violate")))

    # ---- admission: every checker must fire on a doctored stream ----

    def test_admission_mutations(self):
        """Evidence the checks can fail: tamper with the real event
        streams in each observable dimension."""
        clean = self.events("clean")
        fail = self.events("fail")
        violate = self.events("violate")

        calls = [i for i, e in enumerate(clean) if e[0] == "call"]
        swapped = list(clean)
        swapped[calls[0]], swapped[calls[1]] = (swapped[calls[1]],
                                                swapped[calls[0]])
        self.assertTrue(check_call_order(swapped, NSTEPS))

        resurrected = list(fail)
        resurrected.insert(len(fail) - 1,
                           ["call", "ldg_order_c", "run", str(FAIL_STEP)])
        self.assertTrue(check_call_order(resurrected, NSTEPS, FAIL_STEP))

        swallowed = [["host", e[1], "0", "-"]
                     if e[0] == "host" and int(e[2]) != 0 else e
                     for e in fail]
        self.assertTrue(check_error_propagation(swallowed, FAIL_STEP))

        crossed = [["idx", "scheme", e[2], "99"]
                   if e[0] == "idx" and e[1] == "scheme"
                   and e[2] == TRACKED[0] else e for e in clean]
        self.assertTrue(check_const_identity(crossed, NSTEPS))

        unaliased = [["val", "constval", e[2], "3003.0"]
                     if e[0] == "val" and e[1] == "constval"
                     and e[2] == TRACKED[2] else e for e in clean]
        self.assertTrue(check_const_identity(unaliased, NSTEPS))

        reordered = [["constmeta", str(5 - int(e[1])), e[2]]
                     if e[0] == "constmeta" else e for e in clean]
        self.assertTrue(check_const_order(reordered, self.version))

        stale = [["val", "a_run", "temp11", "300.0"]
                 if e[0] == "val" and e[1] == "a_run" else e for e in clean]
        self.assertTrue(check_data_flow(stale, NSTEPS))

        unguarded = [["host", e[1], "0", "-"]
                     if e[0] == "host"
                     and e[1] == "run_before_timestep_init" else e
                     for e in violate]
        self.assertTrue(check_protocol_guard(unguarded))


class LedgerV0(LedgerChecks, unittest.TestCase):
    """The ccpp_framework submodule pin (original capgen)."""
    version = "v0"


class LedgerV1(LedgerChecks, unittest.TestCase):
    """The capgen-v1 framework branch, driven with the same legacy flags
    CAM-SIMA's capgen_compat shim enables."""
    version = "v1"


def main():
    global KEEP_BUILD
    argv = list(sys.argv)
    if "--keep-build" in argv:
        KEEP_BUILD = True
        argv.remove("--keep-build")
    require_v1 = "--require-v1" in argv
    if require_v1:
        argv.remove("--require-v1")
    if require_v1 and find_framework("v1") is None:
        print("run_ledger: FAILED - --require-v1 set but no capgen-v1 "
              "checkout (set CAPGEN_V1_ROOT)")
        return 2
    try:
        result = unittest.main(exit=False, argv=argv, verbosity=2).result
    finally:
        for build in BUILDS.values():
            if KEEP_BUILD:
                print("run_ledger: build kept at", build["builddir"])
            else:
                shutil.rmtree(build["builddir"], ignore_errors=True)
    if not result.wasSuccessful():
        print("run_ledger: FAILED")
        return 1
    skip_note = ""
    if result.skipped:
        skip_note = ", skipped={0} ({1})".format(
            len(result.skipped), "; ".join(sorted(
                {reason.split("(")[0].strip()
                 for _, reason in result.skipped})))
    print("run_ledger: ok ({0} tests{1})".format(result.testsRun,
                                                 skip_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())

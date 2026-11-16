#!/usr/bin/env python3
"""Run the M2 history-lifecycle TLA+ scenarios and check every verdict.

Each scenario is a TLC configuration of M2HistoryLifecycle.tla with a
declared expectation: the pre-fix scenarios must violate exactly their
named invariant (the historical counterexamples for F-HIST-1, F-HIST-2
and F-HIST-5), the legal/fixed scenarios must pass exhaustively, and the
mutation scenarios must fail their liveness companion.  Any scenario
ending in an unexpected verdict fails this driver, so a spec edit that
silently weakens an invariant (making a counterexample pass) is caught
the same way as a protocol regression.

Verdicts are judged by TLC's exit status (0 ok, 12 safety, 13 liveness)
plus, for safety violations, the violated invariant's name - an
identifier this suite owns in the spec, not message prose.  The TLC
version is pinned (tla2tools.jar v1.7.4, TLC 2.19), so both signals are
stable.

Requirements: a Java runtime and tla2tools.jar, located through
$TLA2TOOLS_JAR or the search list below.  The full guarantee statement
for the model is in README.md next to this script.
"""

import os
import re
import subprocess
import sys
import tempfile

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE = "M2HistoryLifecycle"

JAR_CANDIDATES = [
    os.environ.get("TLA2TOOLS_JAR", ""),
    os.path.expanduser("~/devel/tla/tla2tools.jar"),
    os.path.expanduser("~/tla2tools.jar"),
    "/usr/local/lib/tla2tools.jar",
    "/opt/tla/tla2tools.jar",
]

JAVA_CANDIDATES = [
    os.environ.get("JAVA", ""),
    "java",
    "/opt/homebrew/opt/openjdk/bin/java",
    "/usr/local/opt/openjdk/bin/java",
]

# (config basename without extension, expectation, violated invariant)
# expectation: "ok" = exhaustive pass, "safety" = the named invariant is
# violated, "liveness" = a temporal property is violated.
SCENARIOS = [
    ("M2_prefix_fhist1_routing", "safety", "RoutingComplete"),
    ("M2_prefix_fhist1_dropped", "safety", "NoDroppedData"),
    ("M2_prefix_fhist1_flags", "safety", "SplitFlagsConsistent"),
    ("M2_prefix_fhist5_undef", "safety", "NoUndefinedData"),
    ("M2_prefix_fhist2_clobber", "safety", "NoFilenameClobber"),
    ("M2_prefix_legal_testmod", "ok", None),
    ("M2_fixed_full", "ok", None),
    ("M2_fixed_avg_interval", "ok", None),
    ("M2_fixed_coarse_names", "ok", None),
    ("M2_mutation_alwaysfill", "safety", "SampledDataIsWritten"),
    ("M2_mutation_neverwrites", "liveness", None),
]

EXIT_OK = 0
EXIT_SAFETY = 12
EXIT_LIVENESS = 13


def find_java():
    for cand in JAVA_CANDIDATES:
        if not cand:
            continue
        try:
            probe = subprocess.run([cand, "-version"], capture_output=True)
        except OSError:
            continue
        # The macOS /usr/bin/java stub exists but fails when no runtime
        # is installed, so a successful -version run is the real test.
        if probe.returncode == 0:
            return cand
    return None


def find_jar():
    for cand in JAR_CANDIDATES:
        if cand and os.path.isfile(cand):
            return cand
    return None


def run_scenario(java, jar, name, expect, invariant):
    cfg = os.path.join(MODEL_DIR, name + ".cfg")
    if not os.path.isfile(cfg):
        return False, "missing config {0}".format(cfg)
    with tempfile.TemporaryDirectory() as metadir:
        proc = subprocess.run(
            [java, "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC",
             "-config", cfg, "-workers", "1", "-metadir", metadir,
             "-cleanup", MODULE],
            cwd=MODEL_DIR, capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    states = re.search(r"(\d+) distinct states found", out)
    detail = "{0} distinct states".format(states.group(1)) if states else "?"

    if expect == "ok":
        if proc.returncode != EXIT_OK:
            return False, "expected pass, TLC exit {0}\n{1}".format(
                proc.returncode, out)
        if "No error has been found" not in out:
            return False, "exit 0 without completion banner\n" + out
        return True, "pass ({0})".format(detail)
    if expect == "safety":
        if proc.returncode != EXIT_SAFETY:
            return False, "expected safety violation, TLC exit {0}\n{1}".format(
                proc.returncode, out)
        needle = "Invariant {0} is violated".format(invariant)
        if needle not in out:
            return False, "violated a different invariant than {0}\n{1}".format(
                invariant, out)
        return True, "violates {0} as expected".format(invariant)
    if expect == "liveness":
        if proc.returncode != EXIT_LIVENESS:
            return False, "expected liveness violation, TLC exit {0}\n{1}".format(
                proc.returncode, out)
        if "Temporal properties were violated" not in out:
            return False, "liveness exit without temporal violation\n" + out
        return True, "violates liveness as expected"
    return False, "unknown expectation {0}".format(expect)


def main():
    java = find_java()
    if java is None:
        print("run_m2: FAILED - no Java runtime found; set $JAVA or install "
              "a JDK (locally: brew install openjdk)")
        return 2
    jar = find_jar()
    if jar is None:
        print("run_m2: FAILED - tla2tools.jar not found; set $TLA2TOOLS_JAR "
              "or place it at ~/devel/tla/tla2tools.jar (pinned release: "
              "tlaplus v1.7.4)")
        return 2

    failures = 0
    for name, expect, invariant in SCENARIOS:
        ok, msg = run_scenario(java, jar, name, expect, invariant)
        tag = "ok  " if ok else "FAIL"
        print("{0} {1}: {2}".format(tag, name, msg))
        if not ok:
            failures += 1
    if failures:
        print("run_m2: FAILED ({0} of {1} scenarios)".format(
            failures, len(SCENARIOS)))
        return 1
    print("run_m2: ok ({0} scenarios)".format(len(SCENARIOS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

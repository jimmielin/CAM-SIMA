"""Shared reporting and baseline machinery for test/verification checkers.

Every checker reports three verdicts per site -- checked, violated, unknown --
plus coverage counts; silently skipping unresolvable code never counts as
success. Violations are compared against the shared baseline file: a finding
not in the baseline fails the run (new violation), and a baseline entry that
no longer fires also fails the run (stale entry -- remove it in the fix PR,
which is what keeps the baseline a ratchet rather than a dumping ground).
Unknowns are reported but never gate.

Exit codes: 0 ok; 1 new violations or stale baseline entries; 2 usage error.
"""

import argparse
import json
import sys
from pathlib import Path


class Finding:
    """One violation. key must be stable across line-number drift (no line
    numbers in keys); file/line are for the human report only."""

    def __init__(self, key, file, line, message):
        self.key = key
        self.file = file
        self.line = line
        self.message = message


def make_parser(description):
    here = Path(__file__).resolve()
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--repo", type=Path, default=here.parents[3],
                   help="repository root to check (default: this checkout)")
    p.add_argument("--baseline", type=Path, default=here.parents[1] / "baseline.json",
                   help="baseline JSON (default: test/verification/baseline.json)")
    p.add_argument("--no-baseline", action="store_true",
                   help="ignore the baseline: exit 1 on any violation")
    p.add_argument("--self-test", action="store_true",
                   help="run the checker's embedded fixtures and exit")
    p.add_argument("--list-keys", action="store_true",
                   help="print violation keys only (for seeding the baseline)")
    return p


def load_baseline(path, checker_name):
    if not path.is_file():
        return {}
    with open(path) as f:
        data = json.load(f)
    entries = data.get(checker_name, {})
    if not isinstance(entries, dict):
        print(f"{checker_name}: baseline section must be an object", file=sys.stderr)
        sys.exit(2)
    return entries


def report(checker_name, args, findings, unknowns, n_checked):
    """Print the report and return the process exit code."""
    for f in findings:
        loc = f"{f.file}:{f.line}" if f.line else f.file
        print(f"VIOLATED {loc} {f.message}")
    for file, line, msg in unknowns:
        loc = f"{file}:{line}" if line else file
        print(f"UNKNOWN  {loc} {msg}")
    print(f"{checker_name}: checked={n_checked} violated={len(findings)} "
          f"unknown={len(unknowns)}")

    if args.list_keys:
        for f in findings:
            print(f.key)
        return 0

    if args.no_baseline:
        return 1 if findings else 0

    baseline = load_baseline(args.baseline, checker_name)
    found_keys = {f.key for f in findings}
    new = sorted(found_keys - set(baseline))
    stale = sorted(set(baseline) - found_keys)
    for k in new:
        print(f"NEW violation not in baseline: {k}")
    for k in stale:
        print(f"STALE baseline entry no longer fires (remove it in the fix PR): {k}")
    if not new and not stale:
        print(f"{checker_name}: ok ({len(found_keys)} baselined)")
    return 1 if (new or stale) else 0

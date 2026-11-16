#!/usr/bin/env python3
"""Init-mark property suite: the initialization-state semantics that
src/data/write_init_files.py encodes into phys_vars_init_check.F90 and
physics_inputs.F90, checked as observable contracts over every variable of
a fixture that holds one variable per initialization class.

Guarantee statement
  Property (each contract quantified over ALL variables of the generated
  files -- the parsed arrays and case arms are compared in full against the
  fixture-derived oracle, so an extra, missing or misclassified entry
  anywhere fails):
    1. Array contracts: phys_var_stdnames holds exactly the suite-required
       module-table variables plus the registry constituents, each exactly
       once, never an excluded framework name; protected_vars is .true. and
       initialized_vars is PARAM exactly for protected variables, both
       UNINITIALIZED/.false. otherwise; input_var_names rows are the
       registry ic_file_input_names when given, else the local name;
       phys_var_num and phys_const_stdnames match.
    2. Read contracts: physics_read_data has a case arm exactly per
       required input variable; readable variables get a read_field call
       ('lev' exactly for vertical dimension); variables with a registry
       initial_value read with error_on_not_found=.false.; protected or
       unreadable variables without an initial value take the endrun path
       and never read; unreadable variables with an initial value neither
       read nor abort.
    3. Set-before-use: suite_sets_before_use lists exactly the variables a
       suite sets (intent out) before reading, and the read loop carries
       the skip.
    4. Check contracts: physics_check_data has a case arm exactly per
       required output variable.
    5. Determinism: regenerating from the same database is byte-identical,
       and the whole chain (gen_registry + capgen + write_init_files) is
       byte-identical across processes with different PYTHONHASHSEED.
  Assumptions: capgen and the framework parser behave per the capgen-v0
    pin (the host-visible capgen contract is the assumption ledger's job);
    the shared simple_host.meta fixture (test/unit/python) provides the
    host dimensions.
  Checked domain: the init_marks fixture (fixtures/init_marks/): a
    registry with one variable per class -- plain 2d with ic names, plain
    1d defaulted, protected, initial_value, set-before-use, unreadable
    with and without initial_value, constituent -- and a two-scheme suite
    (producer sets mark_setout, consumer reads every class).
  Connection to production code: executes the real gen_registry, the real
    capgen (return_db=True) and the real write_init_files; the oracle is
    the EXPECTED table below, derived from the fixture by hand, never from
    generator internals. Assertions parse the generated Fortran and match
    structured tokens (array constructors, case labels, call names, the
    error_on_not_found flag), never message prose.
  Blind spots: the generated Fortran is parsed, not compiled or run (the
    runtime behavior of physics_read_data is host-side Fortran under
    src/core_utils); constituents required by a scheme (advected handling,
    the const_idx path) are not in the fixture; DDT-member and
    array-element host variables are not in the fixture; physics_check_data
    arm bodies are only checked for presence and check_field structure.

Admission evidence (mutations validated before admission, then reverted):
  - write_ic_arrays mapping protected variables to UNINITIALIZED instead of
    PARAM fails contract 1.
  - write_phys_read_subroutine without the vars_init_value suppression
    (error_on_not_found) fails contract 2.
  - Legal case: the green run of the fixture below.

Run: python3 test/verification/properties/test_init_marks.py
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_ROOT = _THIS_FILE.parents[3]
_FIXDIR = _THIS_FILE.parent / "fixtures" / "init_marks"
_SHARED = _ROOT / "test" / "unit" / "python" / "sample_files" / "shared_files"

sys.path.insert(0, str(_ROOT / "src" / "data"))

# generate_registry_data appends the ccpp_framework scripts directory to
# sys.path at import (submodule must be populated via git-fleximod).
# pylint: disable=wrong-import-position
from generate_registry_data import gen_registry                  # noqa: E402
from ccpp_capgen import capgen                                   # noqa: E402
from framework_env import CCPPFrameworkEnv                       # noqa: E402
from write_init_files import write_init_files, _EXCLUDED_STDNAMES  # noqa: E402
# pylint: enable=wrong-import-position

_LOGGER = logging.getLogger("cam_init_marks_prop")
_LOGGER.setLevel(logging.ERROR)
_LOGGER.addHandler(logging.NullHandler())

_SUITE_NAME = "marks_suite"

# The oracle: initialization classes of every fixture variable, derived by
# hand from fixtures/init_marks/. read classes:
#   read       -- read_field call, no error_on_not_found
#   read_opt   -- read_field call with error_on_not_found=.false.
#   endrun     -- no read_field, endrun (protected or unreadable, no init)
#   silent     -- no read_field, no endrun (unreadable but has initial_value)
#   none       -- no case arm (not a required input: registry constituent)
# vert is the vertical-dimension argument expected in the read_field call.
EXPECTED = {
    "mark_theta":          {"protected": False, "ic": ("theta", "pot_temp"),
                            "read": "read", "vert": "lev", "out": True},
    "mark_slp":            {"protected": False, "ic": ("slp_m",),
                            "read": "read", "vert": None, "out": False},
    "mark_prot":           {"protected": True, "ic": ("prot_rho",),
                            "read": "endrun", "vert": None, "out": False},
    "mark_init_only":      {"protected": False, "ic": ("init_only_m",),
                            "read": "read_opt", "vert": None, "out": False},
    "mark_setout":         {"protected": False, "ic": ("setout_m",),
                            "read": "read", "vert": None, "out": True},
    "mark_badpath_init":   {"protected": False, "ic": ("badpath_init_m",),
                            "read": "silent", "vert": None, "out": False},
    "mark_badpath_noinit": {"protected": False, "ic": ("badpath_noinit_m",),
                            "read": "endrun", "vert": None, "out": False},
    "mark_const_q":        {"protected": False,
                            "ic": ("CONSTQ", "cnst_CONSTQ"),
                            "read": "none", "vert": None, "out": False},
}
EXPECTED_SET_BEFORE_USE = {_SUITE_NAME: ["mark_setout"]}


def find_file(filename, search_dirs):
    """write_init_files include-file locator (production signature)."""
    for sdir in search_dirs:
        test_path = os.path.join(sdir, filename)
        if os.path.exists(test_path):
            return test_path
    return None


def build_chain(workdir):
    """Run the production chain into <workdir>/out: gen_registry on the
    fixture registry, capgen on host+registry metadata with the fixture
    suite, then write_init_files. Returns (outdir, cap_database, registry
    returns) for re-generation tests."""
    workdir = Path(workdir)
    srcmods = workdir / "SourceMods"
    srcmods.mkdir()
    outdir = workdir / "out"
    _, _, ic_names, constituents, _, vars_init_value = gen_registry(
        str(_FIXDIR / "marks_reg.xml"), "se", str(outdir), 3, str(srcmods),
        str(_ROOT), logger=_LOGGER, error_on_no_validate=True)
    run_env = CCPPFrameworkEnv(
        _LOGGER,
        host_files=[str(_SHARED / "simple_host.meta"),
                    str(outdir / "marks_types.meta")],
        scheme_files=[str(_FIXDIR / "marks_producer.meta"),
                      str(_FIXDIR / "marks_consumer.meta")],
        suites=str(_FIXDIR / "marks_suite.xml"),
        preproc_directives='', generate_docfiles=False, host_name='cam',
        kind_types=['kind_phys=REAL64'], use_error_obj=False,
        force_overwrite=True, output_root=str(outdir),
        ccpp_datafile=str(outdir / "datatable.xml"))
    cap_database = capgen(run_env, return_db=True)
    write_init_files(cap_database, ic_names, constituents, vars_init_value,
                     str(outdir), find_file,
                     [str(srcmods), str(_ROOT / "src" / "data")], 3, _LOGGER)
    return outdir, cap_database, (ic_names, constituents, vars_init_value)


# ---------------------------------------------------------------------------
# Generated-Fortran parsing helpers
# ---------------------------------------------------------------------------

def joined_lines(text):
    """Fortran source lines with free-form continuations joined."""
    out = []
    buf = ""
    for raw in text.splitlines():
        part = raw.strip()
        if buf and part.startswith("&"):
            part = part[1:].lstrip()
        buf = (buf + " " + part) if buf else part
        if buf.endswith("&"):
            buf = buf[:-1].rstrip() + " "
        else:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _bracket_content(lines, anchor_re):
    """The [...] constructor content of the declaration matching
    <anchor_re> in continuation-joined <lines>."""
    pattern = re.compile(anchor_re)
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(1)
    raise AssertionError(f"no line matches {anchor_re}")


def parse_init_check(text):
    """Parse the five public arrays of phys_vars_init_check.F90.
    Returns (records, const_stdnames, phys_var_num) where records maps each
    standard name to (protected, mark, ic_names)."""
    lines = joined_lines(text)
    num = int(_bracket_content(
        lines, r"integer, public, parameter :: phys_var_num = (\d+)"))
    stdnames = re.findall(r"'([^']*)'", _bracket_content(
        lines, r"phys_var_stdnames\(phys_var_num\) = "
               r"\[character\(len=\d+\) :: (.*)\]"))
    stdnames = [s.strip() for s in stdnames]
    const_names = [s.strip() for s in re.findall(r"'([^']*)'",
                   _bracket_content(
                       lines, r"phys_const_stdnames\(phys_const_num\) = "
                              r"\[(.*)\]"))]
    ic_flat = [s.strip() for s in re.findall(r"'([^']*)'",
               _bracket_content(
                   lines, r"input_var_names\(\d+, phys_var_num\) = "
                          r"reshape\(\[(.*)\], \[\d+, phys_var_num\]\)"))]
    assert len(ic_flat) % len(stdnames) == 0
    ic_per_var = len(ic_flat) // len(stdnames)
    protected = [tok.strip() for tok in _bracket_content(
        lines, r"protected_vars\(phys_var_num\)= \[(.*)\]").split(",")]
    marks = [tok.strip() for tok in _bracket_content(
        lines, r"initialized_vars\(phys_var_num\)= \[(.*)\]").split(",")]
    records = OrderedDict()
    for idx, stdname in enumerate(stdnames):
        ic_names = tuple(n for n in
                         ic_flat[idx * ic_per_var:(idx + 1) * ic_per_var]
                         if n)
        records[stdname] = (protected[idx], marks[idx], ic_names)
    return records, const_names, num


def case_arms(lines, start_idx):
    """Split a select-case body (joined <lines>, select header at
    <start_idx>) into {case label(s): arm text}; stops at the select's own
    'end select' (arms contain no nested selects here)."""
    arms = OrderedDict()
    label = None
    body = []
    for line in lines[start_idx + 1:]:
        if line.startswith("end select"):
            if label is not None:
                arms[label] = "\n".join(body)
            return arms
        match = re.match(r"case \((.*)\)$", line)
        if match:
            if label is not None:
                arms[label] = "\n".join(body)
            label = match.group(1)
            body = []
        elif label is not None:
            body.append(line)
    raise AssertionError("select-case body has no end select")


def read_case_arms(text, subroutine):
    """{standard name: arm text} of <subroutine>'s per-variable select."""
    seg = text.split(f"subroutine {subroutine}(")[1]
    lines = joined_lines(seg)
    for idx, line in enumerate(lines):
        if "select case (trim(phys_var_stdnames(name_idx)))" in line:
            arms = case_arms(lines, idx)
            return OrderedDict((label.strip("'"), body)
                               for label, body in arms.items())
    raise AssertionError(f"no per-variable select in {subroutine}")


def sets_before_use_table(text):
    """{suite name: [standard names]} from suite_sets_before_use."""
    if "function suite_sets_before_use" not in text:
        return {}
    seg = text.split("function suite_sets_before_use")[1]
    lines = joined_lines(seg)
    table = {}
    suite = None
    for line in lines:
        match = re.match(r"case \('([^']+)'\)$", line)
        if match and suite is None:
            suite = match.group(1)
            table[suite] = []
        elif suite is not None and line.startswith("case ("):
            table[suite].extend(re.findall(r"'([^']+)'", line))
        elif line.startswith("end select") and suite is not None:
            suite = None
    return table


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class InitMarkContracts(unittest.TestCase):
    """Contracts over the generated files (one shared chain run)."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)
        cls.workdir = Path(tempfile.mkdtemp(prefix="cam_init_marks_"))
        cls.outdir, cls.cap_database, cls.reg_returns = \
            build_chain(cls.workdir)
        cls.check_text = (cls.outdir / "phys_vars_init_check.F90").read_text()
        cls.input_text = (cls.outdir / "physics_inputs.F90").read_text()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)
        logging.disable(logging.NOTSET)

    def test_array_contracts(self):
        """Contract 1: the five arrays, compared in full."""
        records, const_names, num = parse_init_check(self.check_text)
        expected_records = {
            stdname: ((".true." if exp["protected"] else ".false."),
                      ("PARAM" if exp["protected"] else "UNINITIALIZED"),
                      exp["ic"])
            for stdname, exp in EXPECTED.items()}
        self.assertEqual(dict(records), expected_records)
        self.assertEqual(num, len(EXPECTED))
        self.assertEqual(const_names, sorted(_EXCLUDED_STDNAMES))
        self.assertFalse(set(records) & _EXCLUDED_STDNAMES,
                         "excluded framework names leaked into the arrays")

    def test_read_contracts(self):
        """Contract 2: one case arm per required input, classed."""
        arms = read_case_arms(self.input_text, "physics_read_data")
        expected_arms = {stdname for stdname, exp in EXPECTED.items()
                         if exp["read"] != "none"}
        self.assertEqual(set(arms), expected_arms)
        for stdname, arm in arms.items():
            exp = EXPECTED[stdname]
            reads = "call read_field(" in arm
            aborts = "call endrun(" in arm
            optional = "error_on_not_found=.false." in arm
            has_lev = "'lev'" in arm
            self.assertEqual(reads, exp["read"] in ("read", "read_opt"),
                             f"{stdname}: read_field presence")
            self.assertEqual(optional, exp["read"] == "read_opt",
                             f"{stdname}: error_on_not_found suppression")
            self.assertEqual(aborts, exp["read"] == "endrun",
                             f"{stdname}: endrun path")
            if reads:
                self.assertEqual(has_lev, exp["vert"] == "lev",
                                 f"{stdname}: vertical dimension argument")

    def test_set_before_use(self):
        """Contract 3: the suite_sets_before_use table and the read skip."""
        self.assertEqual(sets_before_use_table(self.input_text),
                         EXPECTED_SET_BEFORE_USE)
        self.assertIn("cycle suite_required_vars", self.input_text)

    def test_check_contracts(self):
        """Contract 4: one case arm per required output variable."""
        arms = read_case_arms(self.input_text, "physics_check_data")
        expected_arms = {stdname for stdname, exp in EXPECTED.items()
                         if exp["out"]}
        self.assertEqual(set(arms), expected_arms)
        for stdname, arm in arms.items():
            self.assertIn("call check_field(", arm, f"{stdname}: check call")

    def test_regeneration_identical(self):
        """Contract 5a: a second write_init_files run from the same capgen
        database is byte-identical."""
        outdir2 = self.workdir / "out2"
        outdir2.mkdir()
        ic_names, constituents, vars_init_value = self.reg_returns
        write_init_files(self.cap_database, dict(ic_names), constituents,
                         vars_init_value, str(outdir2), find_file,
                         [str(self.workdir / "SourceMods"),
                          str(_ROOT / "src" / "data")], 3, _LOGGER)
        for name in ("phys_vars_init_check.F90", "physics_inputs.F90"):
            self.assertEqual((outdir2 / name).read_bytes(),
                             (self.outdir / name).read_bytes(),
                             f"{name}: regeneration differs")


class InitMarkDeterminism(unittest.TestCase):
    """Contract 5b: cross-process, cross-hash-seed determinism."""

    def test_chain_deterministic_across_hash_seeds(self):
        """The generated files must not depend on PYTHONHASHSEED (set/dict
        iteration order anywhere in the chain)."""
        results = {}
        for seed in ("0", "1", "2", "3"):
            workdir = Path(tempfile.mkdtemp(prefix=f"cam_marks_det_{seed}_"))
            try:
                env = dict(os.environ, PYTHONHASHSEED=seed)
                proc = subprocess.run(
                    [sys.executable, str(_THIS_FILE), "--generate",
                     str(workdir)],
                    env=env, capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, 0,
                                 f"--generate failed: {proc.stderr}")
                results[seed] = {
                    name: (workdir / "out" / name).read_bytes()
                    for name in ("phys_vars_init_check.F90",
                                 "physics_inputs.F90")}
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
        baseline = results["0"]
        for seed, outputs in results.items():
            self.assertEqual(outputs, baseline,
                             f"outputs differ between hash seeds 0 and {seed}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--generate":
        logging.disable(logging.CRITICAL)
        build_chain(sys.argv[2])
        sys.exit(0)
    unittest.main(verbosity=2)

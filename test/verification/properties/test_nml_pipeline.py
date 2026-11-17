#!/usr/bin/env python3
"""Namelist/run-type pipeline property suite: every namelist value a user
or CIME run type supplies must reach atm_in exactly once, correctly
formatted, per instance -- or be rejected with a structured error.

The pipeline under test is cime_config/buildnml's per-instance protocol
(construct AtmInParamGen from the namelist definition XML, append
user_nl_cam, reduce against the case + attribute dictionary, write
atm_in) plus the AtmInParamGen class itself on top of CIME's ParamGen
(imported from the cime submodule; atm_in_paramgen.py does its own
sys.path setup for it).

Guarantee statement
  Property:
    1. Round trip (quantified, Hypothesis): for every variable of every
       generated namelist definition (one variable per type x rank class:
       integer/real/logical/character x scalar/vector) and every subset of
       user_nl_cam assignments, the written atm_in is byte-identical to
       the text recomputed independently from the XML spec and the
       user_nl semantics: one sorted group block per group, each variable
       exactly once, user_nl values overriding XML defaults, logical
       spellings normalized to .true./.false., character values quoted,
       numeric values passed through.  Byte equality against a
       spec-derived expectation makes declaration-order and user_nl-order
       invariance corollaries: the expectation does not depend on either
       order, and both orders are drawn.
    2. Run-type routing (F-DRIVER-2, Nov 2026 audit): a buildnml run with
       RUN_TYPE=hybrid must put the refcase initial file into atm_in's
       ncdata, and RUN_TYPE=branch the refcase restart into
       cam_branch_file.  Pinned as expectedFailure ratchets: today the
       values are written to Buildconf/camconf/namelist_infile, which
       nothing reads, and atm_in silently keeps the XML defaults.
    3. Instance isolation (PRIOR:build-python#0, carried as F-DRIVER-7):
       a buildnml run with NINST_ATM=2 must produce atm_in_0001 and
       atm_in_0002, each reflecting exactly its own instance's user_nl
       file (no leakage from instance 1 into instance 2).  Pinned as two
       expectedFailure ratchets, one per historical crash mode: a
       non-empty second user_nl dies in ParamGen.append (reduced vs
       unreduced), an empty one dies in ParamGen.reduce (already
       reduced).  The isolation assertions also pin the documented
       follow-on defect (user_nl values leaking across instances once the
       crash is fixed).
    4. valid_values enforcement (Nov 2026 audit 4.1 #5, fix group FG-2):
       a buildnml run whose user_nl sets an enumerated variable outside
       its declared valid_values must not write that value into atm_in
       (any structured rejection is acceptable).  Pinned as an
       expectedFailure ratchet: today nothing in the pipeline reads
       valid_values and the invalid value lands in atm_in.
    5. user_nl array indexing: distinct whole-variable duplicates and
       genuinely repeated indices are rejected with AtmInParamGenError
       (legal cases, pass today); distinct elements of a multi-dimensional
       array must be accepted (PRIOR:build-python#7 expectedFailure
       ratchet: a repeat in the first checked dimension poisons the
       verdict for all later dimensions); a trailing comma on a character
       array value must be accepted with the listed elements (PRIOR:
       build-python#6 expectedFailure ratchet: today a bare IndexError
       escapes _check_string_quotes; scalar character values already
       strip trailing commas by documented design); an empty mid-array
       element must at worst raise AtmInParamGenError, never an
       uncontrolled exception class (second build-python#6 shape, also an
       expectedFailure ratchet -- Fortran null values are a legitimate
       alternative target semantics, so only the error class is pinned).
  Assumptions: CIME's ParamGen semantics (reduce picks the last matching
    guarded value; append refuses mixed reduced states) are the imported
    contract, not re-verified here; ConfigCAM and HistoryConfig are
    stubbed at the buildnml module boundary, so their internals are
    outside this suite (source generation has its own suites; the
    hist_config suite is deliberately deferred).
  Checked domain: generated namelist definitions with scalar and 1-D
    integer/real/logical/character variables plus deterministic fixtures
    carrying the real protocol groups (physics_nl, vert_coord_nl,
    cam_initfiles_nl) and 2-D arrays; values are comma-free and
    equals-free.  STARTUP/HYBRID/BRANCH run types; NINST_ATM in {1, 2}.
  Connection to production code: executes the real buildnml() function
    loaded from cime_config/buildnml (SourceFileLoader; the script has no
    .py extension) with a stub CIME case object, and the real
    AtmInParamGen append/reduce/write chain; nothing in cime_config is
    mocked except the two class boundaries named above.
  Blind spots: ConfigCAM attribute derivation and ccpp_phys_set
    validation (PRIOR:build-python#12) are stubbed out; hist_config
    appending is stubbed out; commas inside quoted character elements are
    excluded from the domain (write() splits array values on raw commas
    and rejects such legal-Fortran input with a structured
    AtmInParamGenError -- a known sharp edge, observed 2026-11-17, left
    for the fix PR that touches the array writer); whitespace after
    commas in logical arrays is likewise excluded; the generated atm_in
    is never parsed by a Fortran namelist reader here.

Admission evidence:
  - Historical: all five expectedFailure ratchets reproduce Sep/Nov 2026
    audit findings through the real pipeline (buildnml,
    atm_in_paramgen.py and namelist_definition_cam.xml are byte-identical
    between the audit base 27639b49 and HEAD, so firing here is firing at
    the historical base).
  - Mutations (run during development, not kept): doctoring the written
    atm_in (dropping one variable line) fails the round-trip byte
    comparison; appending an extra user_nl assignment the expectation
    does not know about fails it as well, proving the user_nl leg is
    live.  The in-suite anti-vacuity checks (exact group/variable sets in
    the startup pipeline test, byte equality in the round trip) prevent
    vacuous passes.
  - Legal cases: the startup pipeline test and every non-ratchet test
    below pass against production code today.

Ratchet retirement (for the upstream fix PRs):
  - F-DRIVER-2 fix: remove the two run-type expectedFailure markers.
  - build-python#0 / buildnml-instance-loop fix: remove the two
    multi-instance markers (the isolation assertions then gate the
    documented leakage follow-on).
  - FG-2 valid_values enforcement: remove the valid-values marker.
  - build-python#6 fix: remove the trailing-comma marker; if the fix
    rejects trailing commas instead of accepting them, this test fails
    loudly and must become a rejection test.  Remove the empty-element
    marker (it passes for either rejection or null-value semantics).
  - build-python#7 fix: remove the multi-dimensional-index marker.

Run: python3 test/verification/properties/test_nml_pipeline.py
(needs the cime submodule for ParamGen and the ccpp_framework submodule
for buildnml's cam_config import, like the build-cache suite)
"""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_ROOT = _THIS_FILE.parents[3]
_CIME_ROOT = _ROOT / "cime"

# buildnml requires CIMEROOT at load time; the cime package and the
# cime_config modules must both be importable before the script loads.
os.environ.setdefault("CIMEROOT", str(_CIME_ROOT))
sys.path.insert(0, str(_CIME_ROOT))
sys.path.insert(0, str(_ROOT / "cime_config"))

# pylint: disable=wrong-import-position
from atm_in_paramgen import AtmInParamGen, AtmInParamGenError  # noqa: E402
# pylint: enable=wrong-import-position

try:
    from hypothesis import given, settings, HealthCheck
    from hypothesis import strategies as st
    HAVE_HYPOTHESIS = True
    # Keep all Hypothesis storage (example DB and the constants cache,
    # which ignores database=None) out of the repository root.
    import hypothesis.configuration as _hypothesis_config
    _hypothesis_config.set_hypothesis_home_dir(
        tempfile.mkdtemp(prefix="cam_hypothesis_"))
except ImportError:
    HAVE_HYPOTHESIS = False


def _load_buildnml():
    """Load cime_config/buildnml (no .py extension) as a module."""
    path = _ROOT / "cime_config" / "buildnml"
    loader = importlib.machinery.SourceFileLoader("cam_buildnml", str(path))
    spec = importlib.util.spec_from_loader("cam_buildnml", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


_BUILDNML = _load_buildnml()

# The physics suite name the stub ConfigCAM reports; the fixture's pver
# entry carries a matching phys_suite guard so the deterministic pipeline
# test also exercises attribute-guarded value selection.
_STUB_SUITE = "verif_a"

_RUN_REFCASE = "refcase01"
_RUN_REFDATE = "0002-01-01"
_RUN_REFTOD = "00000"

# Deterministic fixture: the three groups buildnml's protocol requires
# (physics_nl, vert_coord_nl, cam_initfiles_nl) plus one verification
# group holding the finding-class variables.  Shapes mirror
# cime_config/namelist_definition_cam.xml (ncdata, cam_branch_file,
# physics_suite, pver, and debug_output's valid_values form).
_FIXTURE_XML = """<?xml version="1.0"?>
<entry_id_pg version="2.0">
  <entry id="ncdata">
    <type>char*256</type>
    <category>initial_conditions</category>
    <group>cam_initfiles_nl</group>
    <desc>Initial-condition file.</desc>
    <values>
      <value>${DIN_LOC_ROOT}/default_ic.nc</value>
    </values>
  </entry>
  <entry id="cam_branch_file">
    <type>char*256</type>
    <category>initial_conditions</category>
    <group>cam_initfiles_nl</group>
    <desc>Branch restart file.</desc>
    <values>
      <value>UNSET_PATH</value>
    </values>
  </entry>
  <entry id="physics_suite">
    <type>char*256</type>
    <category>build</category>
    <group>physics_nl</group>
    <desc>CCPP physics suite.</desc>
    <values>
      <value>UNSET</value>
    </values>
  </entry>
  <entry id="pver">
    <type>integer</type>
    <category>vert_coord</category>
    <group>vert_coord_nl</group>
    <desc>Vertical levels (guarded default).</desc>
    <values>
      <value>30</value>
      <value phys_suite="verif_a">26</value>
    </values>
  </entry>
  <entry id="vp_steps">
    <type>integer</type>
    <category>verification</category>
    <group>vp_main_nl</group>
    <valid_values>0,1,2,3</valid_values>
    <desc>Enumerated option.</desc>
    <values>
      <value>0</value>
    </values>
  </entry>
  <entry id="vp_names">
    <type>char*32(4)</type>
    <category>verification</category>
    <group>vp_main_nl</group>
    <desc>Character array.</desc>
    <values>
      <value>UNSET</value>
    </values>
  </entry>
  <entry id="vp_grid">
    <type>integer(3,4)</type>
    <category>verification</category>
    <group>vp_main_nl</group>
    <desc>Two-dimensional integer array.</desc>
    <values>
      <value>0</value>
    </values>
  </entry>
</entry_id_pg>
"""


class _StubCase:
    """CIME case stand-in: get_value from a fixed dictionary (None for
    unknown names, which sends ParamGen's expansion to the attribute
    dictionary), identity get_resolved_value."""

    def __init__(self, values=None):
        self._values = dict(values or {})

    def get_value(self, name):
        """Return the recorded case value, or None when unset."""
        return self._values.get(name)

    @staticmethod
    def get_resolved_value(line):
        """Identity: the fixtures carry no $CASEVAR references."""
        return line


class _StubHistoryConfig:
    """hist_config boundary stub: no history entries, no output."""

    # The real class takes these keywords; tests never read the instance.
    def __init__(self, filename=None, logger=None):
        self._unused = (filename, logger)

    @staticmethod
    def keys():
        """No history configs."""
        return []

    def output_class_namelist(self, fil):
        """Append nothing to atm_in."""


def _make_stub_config(xml_path):
    """Build a ConfigCAM stand-in bound to one namelist definition file."""

    class _StubConfigCAM:
        """ConfigCAM boundary stub: no config attributes, one namelist
        definition file, no source generation, fixed physics suite."""

        def __init__(self, case, logger):
            self._unused = (case, logger)
            self.config_dict = {}
            self.xml_nml_def_files = {os.path.basename(xml_path):
                                      str(xml_path)}

        @staticmethod
        def generate_cam_src(indent):
            """No generated schemes."""
            del indent
            return []

        @staticmethod
        def ccpp_phys_set(cam_nml_dict, phys_nl_dict):
            """Report the fixture suite as the configured one."""
            del phys_nl_dict
            cam_nml_dict["phys_suite"] = _STUB_SUITE

    return _StubConfigCAM


def _parse_atm_in(path):
    """Parse atm_in into {group: {variable: value-string}}."""
    groups = {}
    group = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("&"):
            group = stripped[1:]
            groups[group] = {}
        elif stripped == "/":
            group = None
        else:
            var, _, val = stripped.partition("=")
            groups[group][var.strip()] = val.strip()
    return groups


def _unquote(value):
    """Strip one layer of matched namelist quotes."""
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1]
    return value


def _run_buildnml(tmp, run_type="startup", ninst=1, user_nls=None,
                  xml_text=_FIXTURE_XML):
    """Drive the real buildnml() in a scratch case; return the run dir."""
    tmp = Path(tmp)
    caseroot = tmp / "case"
    rundir = tmp / "run"
    (caseroot / "SourceMods" / "src.cam").mkdir(parents=True)
    rundir.mkdir()
    xml_path = tmp / "namelist_definition_verif.xml"
    xml_path.write_text(xml_text, encoding="utf-8")
    if user_nls is None:
        user_nls = {"user_nl_cam": ""}
    for name, content in user_nls.items():
        (caseroot / name).write_text(content, encoding="utf-8")
    case = _StubCase({
        "SRCROOT": str(tmp / "src"),
        "RUNDIR": str(rundir),
        "CAM_NAMELIST_OPTS": "",
        "CAM_NML_USE_CASE": "UNSET",
        "NINST_ATM": ninst,
        "RUN_TYPE": run_type,
        "RUN_STARTDATE": "0001-01-01",
        "RUN_REFCASE": _RUN_REFCASE,
        "RUN_REFDATE": _RUN_REFDATE,
        "RUN_REFTOD": _RUN_REFTOD,
        "DIN_LOC_ROOT": "/inputdata",
    })
    orig_config = _BUILDNML.ConfigCAM
    orig_hist = _BUILDNML.HistoryConfig
    _BUILDNML.ConfigCAM = _make_stub_config(xml_path)
    _BUILDNML.HistoryConfig = _StubHistoryConfig
    try:
        _BUILDNML.buildnml(case, str(caseroot), "cam")
    finally:
        _BUILDNML.ConfigCAM = orig_config
        _BUILDNML.HistoryConfig = orig_hist
    return rundir


class TestBuildnmlPipeline(unittest.TestCase):
    """Contracts 2-4: the real buildnml() per-instance protocol."""

    def setUp(self):
        # pylint: disable=consider-using-with
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_startup_values_land(self):
        """Legal case + anti-vacuity: a STARTUP single-instance run
        produces exactly the fixture's groups and variables, with the
        user_nl override, the ${DIN_LOC_ROOT} expansion, and the
        phys_suite-guarded pver default all in place."""
        rundir = _run_buildnml(self.tmp,
                               user_nls={"user_nl_cam": "vp_steps = 2\n"})
        groups = _parse_atm_in(rundir / "atm_in")
        self.assertEqual(groups, {
            "cam_initfiles_nl": {
                "cam_branch_file": '"UNSET_PATH"',
                "ncdata": '"/inputdata/default_ic.nc"',
            },
            "physics_nl": {"physics_suite": '"UNSET"'},
            "vert_coord_nl": {"pver": "26"},
            "vp_main_nl": {
                "vp_grid": "0",
                "vp_names": '"UNSET"',
                "vp_steps": "2",
            },
        })

    @unittest.expectedFailure
    def test_hybrid_refcase_ic_reaches_atm_in(self):
        """F-DRIVER-2 ratchet: RUN_TYPE=hybrid must route the refcase
        initial file into atm_in's ncdata.  Fails today: buildnml writes
        it to camconf/namelist_infile, which nothing reads, and atm_in
        keeps the XML default.  Remove the marker in the fix PR."""
        rundir = _run_buildnml(self.tmp, run_type="hybrid")
        groups = _parse_atm_in(rundir / "atm_in")
        want = f"{_RUN_REFCASE}.cam.i.{_RUN_REFDATE}-{_RUN_REFTOD}.nc"
        self.assertEqual(_unquote(groups["cam_initfiles_nl"]["ncdata"]),
                         want)

    @unittest.expectedFailure
    def test_branch_refcase_restart_reaches_atm_in(self):
        """F-DRIVER-2 ratchet (branch leg): RUN_TYPE=branch must route
        the refcase restart file into cam_branch_file.  Fails today for
        the same reason as the hybrid leg.  Remove the marker in the fix
        PR."""
        rundir = _run_buildnml(self.tmp, run_type="branch")
        groups = _parse_atm_in(rundir / "atm_in")
        want = f"{_RUN_REFCASE}.cam.r.{_RUN_REFDATE}-{_RUN_REFTOD}.nc"
        self.assertEqual(
            _unquote(groups["cam_initfiles_nl"]["cam_branch_file"]), want)

    @unittest.expectedFailure
    def test_multi_instance_namelists(self):
        """build-python#0 ratchet (non-empty mode): NINST_ATM=2 must
        produce atm_in_0001 and atm_in_0002, each with exactly its own
        instance's user_nl values and no leakage from instance 1.  Fails
        today: the single pg_atm object is reused and the second
        append_user_nl_file dies in ParamGen.append (reduced vs
        unreduced).  Remove the marker in the fix PR; the isolation
        assertions then gate the documented leakage follow-on."""
        rundir = _run_buildnml(self.tmp, ninst=2, user_nls={
            "user_nl_cam_0001": "vp_steps = 1\nvp_names = 'alpha'\n",
            "user_nl_cam_0002": "vp_steps = 2\n",
        })
        one = _parse_atm_in(rundir / "atm_in_0001")
        two = _parse_atm_in(rundir / "atm_in_0002")
        self.assertEqual(one["vp_main_nl"]["vp_steps"], "1")
        self.assertEqual(_unquote(one["vp_main_nl"]["vp_names"]), "alpha")
        self.assertEqual(two["vp_main_nl"]["vp_steps"], "2")
        # Instance 1's vp_names setting must not leak into instance 2.
        self.assertEqual(_unquote(two["vp_main_nl"]["vp_names"]), "UNSET")

    @unittest.expectedFailure
    def test_multi_instance_empty_user_nl(self):
        """build-python#0 ratchet (empty mode): an empty second user_nl
        file must still yield a default atm_in_0002.  Fails today: the
        append is skipped and reduce_atm_in dies in ParamGen.reduce
        (already reduced).  Remove the marker in the fix PR."""
        rundir = _run_buildnml(self.tmp, ninst=2, user_nls={
            "user_nl_cam_0001": "vp_steps = 1\n",
            "user_nl_cam_0002": "",
        })
        two = _parse_atm_in(rundir / "atm_in_0002")
        self.assertEqual(two["vp_main_nl"]["vp_steps"], "0")

    @unittest.expectedFailure
    def test_valid_values_enforced(self):
        """FG-2 ratchet (Nov 2026 audit 4.1 #5): a user_nl value outside
        the declared valid_values must not reach atm_in; any structured
        rejection of the run is acceptable.  Fails today: nothing in the
        pipeline reads valid_values and vp_steps=7 lands in atm_in.
        Remove the marker when enforcement lands."""
        try:
            rundir = _run_buildnml(
                self.tmp, user_nls={"user_nl_cam": "vp_steps = 7\n"})
        # Any structured refusal to produce atm_in satisfies the
        # property; the exception class is the fix PR's choice.
        except Exception:  # pylint: disable=broad-except
            return
        groups = _parse_atm_in(rundir / "atm_in")
        self.assertNotEqual(groups["vp_main_nl"]["vp_steps"], "7")


def _chain(tmp, user_nl_text, xml_text=_FIXTURE_XML):
    """The buildnml per-instance chain on AtmInParamGen directly:
    construct from XML, append one user_nl file, reduce, write.
    Returns the parsed atm_in."""
    tmp = Path(tmp)
    xml_path = tmp / "namelist_definition_verif.xml"
    if not xml_path.is_file():
        xml_path.write_text(xml_text, encoding="utf-8")
    user_nl = tmp / "user_nl_cam"
    user_nl.write_text(user_nl_text, encoding="utf-8")
    pg_atm = AtmInParamGen.from_namelist_xml(str(xml_path))
    pg_atm.append_user_nl_file(str(user_nl))
    pg_atm.reduce_atm_in(_StubCase({"DIN_LOC_ROOT": "/inputdata"}),
                         {"phys_suite": _STUB_SUITE})
    atm_in = tmp / "atm_in"
    pg_atm.write(str(atm_in))
    return _parse_atm_in(atm_in)


class TestUserNlArrayHandling(unittest.TestCase):
    """Contract 5: user_nl array indexing and element handling."""

    def setUp(self):
        # pylint: disable=consider-using-with
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_distinct_1d_indices_accepted(self):
        """Legal case: distinct 1-D indexed assignments coexist with the
        whole-array default, each landing as its own atm_in entry."""
        groups = _chain(self.tmp, "vp_names(2) = 'beta'\n"
                                  "vp_names(3) = 'gamma'\n")
        entries = groups["vp_main_nl"]
        self.assertEqual(_unquote(entries["vp_names"]), "UNSET")
        self.assertEqual(_unquote(entries["vp_names(2)"]), "beta")
        self.assertEqual(_unquote(entries["vp_names(3)"]), "gamma")

    def test_whole_variable_duplicate_rejected(self):
        """Legal case: assigning the same variable twice in one user_nl
        file raises the structured error."""
        with self.assertRaises(AtmInParamGenError):
            _chain(self.tmp, "vp_steps = 1\nvp_steps = 2\n")

    def test_repeated_index_rejected(self):
        """Legal case: genuinely assigning one array element twice
        raises the structured error."""
        with self.assertRaises(AtmInParamGenError):
            _chain(self.tmp, "vp_grid(1,1) = 5\nvp_grid(1,1) = 6\n")

    @unittest.expectedFailure
    def test_distinct_multidim_indices_accepted(self):
        """build-python#7 ratchet: distinct elements of a 2-D array must
        be accepted.  Fails today: a repeat in the first checked
        dimension poisons the duplicate verdict for all later dimensions
        and (1,1)/(1,2) is rejected as a false duplicate.  Remove the
        marker in the fix PR."""
        groups = _chain(self.tmp, "vp_grid(1,1) = 5\nvp_grid(1,2) = 6\n")
        entries = groups["vp_main_nl"]
        self.assertEqual(entries["vp_grid(1,1)"], "5")
        self.assertEqual(entries["vp_grid(1,2)"], "6")

    @unittest.expectedFailure
    def test_char_array_trailing_comma_accepted(self):
        """build-python#6 ratchet: a trailing comma on a character-array
        value (legal Fortran namelist, and already stripped by design for
        scalar character values) must be accepted with exactly the listed
        elements.  Fails today: the empty final element escapes into
        _check_string_quotes as a bare IndexError.  Remove the marker in
        the fix PR; if the fix rejects trailing commas instead, convert
        this to a rejection test."""
        groups = _chain(self.tmp, "vp_names = 'a', 'b',\n")
        self.assertEqual(groups["vp_main_nl"]["vp_names"], "'a', 'b'")

    @unittest.expectedFailure
    def test_empty_array_element_is_structured_error(self):
        """build-python#6 ratchet (second shape): an empty mid-array
        element must either be handled (Fortran null-value semantics) or
        rejected with AtmInParamGenError -- never an uncontrolled
        exception class.  Fails today with the same bare IndexError.
        Remove the marker in the fix PR."""
        try:
            _chain(self.tmp, "vp_names = 'a', , 'b'\n")
        except AtmInParamGenError:
            pass


# ----------------------------------------------------------------------
# Contract 1: quantified round trip (Hypothesis).
# ----------------------------------------------------------------------

# One variable per type x rank class; (type, extent) with extent 0 for a
# scalar and a 1-D vector of that extent otherwise.
_VAR_CLASSES = [
    ("integer", 0), ("real", 0), ("logical", 0), ("char*32", 0),
    ("integer", 3), ("real", 2), ("logical", 2), ("char*16", 4),
]

_TRUE_SPELLINGS = ["true", ".true.", "1", "TRUE", ".True."]
_FALSE_SPELLINGS = ["false", ".false.", "0", "FALSE", ".False."]

_ENTRY_TEMPLATE = """  <entry id="{name}">
    <type>{vtype}</type>
    <category>verification</category>
    <group>{group}</group>
    <desc>Round-trip fixture variable.</desc>
    <values>
      <value>{default}</value>
    </values>
  </entry>
"""


def _format_element(vtype, raw):
    """Transcription of _get_nml_value_str for one array element or
    scalar value, for comma-free fixture values."""
    if vtype == "logical":
        if raw.lower() in {"true", ".true.", "1"}:
            return ".true."
        return ".false."
    if vtype.startswith("char"):
        stripped = raw.strip()
        if stripped.endswith(","):
            stripped = stripped[:-1].strip()
        if stripped and stripped[0] in "'\"":
            return stripped
        return f'"{stripped}"'
    # integer/real values pass through unchanged (string inputs never
    # take the Python-int .d0 branch).
    return raw


def _expected_atm_in_text(spec_vars, user_vals):
    """Recompute the atm_in text from the XML spec facts and the user_nl
    assignments alone: groups sorted, variables sorted, arrays split on
    commas and rejoined element-wise."""
    groups = {}
    for name, vtype, extent, group, default in spec_vars:
        raw = user_vals.get(name, default)
        if extent == 0:
            value = _format_element(vtype, raw.strip())
        else:
            value = ", ".join(_format_element(vtype, elem)
                              for elem in raw.split(","))
        groups.setdefault(group, {})[name] = value
    lines = []
    for group in sorted(groups):
        lines.append(f"&{group}")
        for name in sorted(groups[group]):
            lines.append(f"    {name} = {groups[group][name]}")
        lines.append("/")
        lines.append("")
    return "\n".join(lines) + "\n" if lines else ""


if HAVE_HYPOTHESIS:

    _CHAR_ALPHABET = ("abcdefghijklmnopqrstuvwxyz"
                      "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-")

    @st.composite
    def _pipeline_specs(draw):
        """A namelist definition (one variable per drawn class, spread
        over up to two groups), a user_nl subset, and both orders."""
        groups = ["vq_one_nl", "vq_two_nl"]

        def one_value(vtype):
            if vtype == "integer":
                return str(draw(st.integers(-999, 999)))
            if vtype == "real":
                mantissa = draw(st.integers(-9999, 9999))
                exp = draw(st.sampled_from(["", "e2", "d0", "e-3"]))
                return f"{mantissa / 100.0:.2f}{exp}"
            if vtype == "logical":
                return draw(st.sampled_from(_TRUE_SPELLINGS
                                            + _FALSE_SPELLINGS))
            text = draw(st.text(alphabet=_CHAR_ALPHABET, min_size=1,
                                max_size=8))
            if draw(st.booleans()):
                quote = draw(st.sampled_from("'\""))
                return f"{quote}{text}{quote}"
            return text

        spec_vars = []
        for i, (vtype, extent) in enumerate(_VAR_CLASSES):
            if not draw(st.booleans()):
                continue
            name = f"vq_v{i}"
            group = draw(st.sampled_from(groups))
            if extent == 0:
                default = one_value(vtype)
            else:
                count = draw(st.integers(1, extent))
                default = ",".join(one_value(vtype) for _ in range(count))
            spec_vars.append((name, vtype, extent, group, default))
        if not spec_vars:
            spec_vars.append(("vq_v0", "integer", 0, groups[0], "0"))
        user_vals = {}
        for name, vtype, extent, _, _ in spec_vars:
            if not draw(st.booleans()):
                continue
            if extent == 0:
                user_vals[name] = one_value(vtype)
            else:
                count = draw(st.integers(1, extent))
                user_vals[name] = ",".join(one_value(vtype)
                                           for _ in range(count))
        xml_order = draw(st.permutations(range(len(spec_vars))))
        nl_names = sorted(user_vals)
        nl_order = draw(st.permutations(nl_names))
        return spec_vars, user_vals, xml_order, list(nl_order)

    _SETTINGS = settings(max_examples=25, deadline=None, derandomize=True,
                         suppress_health_check=[HealthCheck.too_slow])


class TestRoundTripProperty(unittest.TestCase):
    """Contract 1: spec-derived byte-exact round trip, quantified over
    variable classes, values, declaration order and user_nl order."""

    if HAVE_HYPOTHESIS:

        @_SETTINGS
        @given(case=_pipeline_specs())
        def test_round_trip_bytes(self, case):
            """The written atm_in is byte-identical to the expectation
            recomputed from the spec, for any drawn XML entry order and
            any drawn user_nl line order (order invariance follows: the
            expectation depends on neither order)."""
            spec_vars, user_vals, xml_order, nl_order = case
            entries = "".join(
                _ENTRY_TEMPLATE.format(
                    name=spec_vars[i][0],
                    vtype=(spec_vars[i][1] if spec_vars[i][2] == 0 else
                           f"{spec_vars[i][1]}({spec_vars[i][2]})"),
                    group=spec_vars[i][3],
                    default=spec_vars[i][4])
                for i in xml_order)
            xml_text = ('<?xml version="1.0"?>\n<entry_id_pg '
                        f'version="2.0">\n{entries}</entry_id_pg>\n')
            nl_text = "".join(f"{name} = {user_vals[name]}\n"
                              for name in nl_order)
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                (tmp / "nml.xml").write_text(xml_text, encoding="utf-8")
                (tmp / "user_nl_cam").write_text(nl_text, encoding="utf-8")
                pg_atm = AtmInParamGen.from_namelist_xml(
                    str(tmp / "nml.xml"))
                pg_atm.append_user_nl_file(str(tmp / "user_nl_cam"))
                pg_atm.reduce_atm_in(_StubCase(), {})
                pg_atm.write(str(tmp / "atm_in"))
                written = (tmp / "atm_in").read_text(encoding="utf-8")
            self.assertEqual(written,
                             _expected_atm_in_text(spec_vars, user_vals))

    else:

        @unittest.skip("hypothesis not installed")
        def test_round_trip_bytes(self):
            """Quantified round trip needs hypothesis."""


if __name__ == "__main__":
    unittest.main(verbosity=2)

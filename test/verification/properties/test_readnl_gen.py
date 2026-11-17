#!/usr/bin/env python3
"""Readnl-generator property suite: every namelist reader module that
cime_config/create_readnl_files.py generates must satisfy the same
read-on-root / broadcast-to-all contract that check_readnl_bcast enforces
on the hand-written readers in src/.

Guarantee statement
  Property (quantified over every variable of every generated reader --
  the fixture holds one variable per type x rank class the namelist XML
  <type> grammar admits):
    1. Completeness: the generated reader reads each namelist group under
       the generated root guard (mpi_isroot) and broadcasts every group
       variable; the checker's rule (a) reports no violation and no
       unknown, and its parse saw the full population (every fixture
       variable in its declared group, one broadcast per variable), so a
       clean verdict cannot come from a parse miss.
    2. Count agreement: every generated mpi_bcast count matches the
       generated declaration (checker rule (b)): literal 1 for scalars,
       the extent product for arrays, len() factors for characters.
    3. The multi-dimensional character broadcast is valid Fortran. This
       is build-python#11 (Sep 2026 audit, open at 27639b49 and at HEAD,
       where the generator file is byte-identical): the emitted count
       `len(var(1))*N` subscripts a rank-2 array with one index, which no
       compiler accepts. Pinned as an expectedFailure ratchet; the fix PR
       must remove the marker (if the fix instead rejects multi-dim
       character namelist variables at generation time, the setUpClass
       generation of the m11 fixture fails loudly and this scenario must
       become a rejection test).
  Assumptions: the checker's analysis (imported from
    test/verification/checkers/check_readnl_bcast.py) is the oracle; its
    own admission evidence lives in its self-test. The namelist XML
    validates against cime's entry_id_pg.xsd (the cime submodule provides
    the schema, ccpp_framework the XML/Fortran tooling).
  Checked domain: two generated schemes: verif_legal with one variable per
    legal class (integer/real/logical/character x scalar/vector, integer
    and real rank-2 arrays) across two namelist groups, and verif_m11 with
    the rank-2 character array that triggers build-python#11; plus the
    generated master reader module.
  Connection to production code: executes the real gen_namelist_files on
    the fixture XML and applies the real checker rules to the emitted
    Fortran; nothing is mocked.
  Blind spots: the generated Fortran is statically checked, not compiled
    (build-python#11 is precisely a compile error, caught here by the
    rank check instead); the generated .meta files and the master-module
    dispatch logic are not checked beyond the reader contract; XML values
    and valid_values semantics belong to the namelist pipeline suite, not
    here.

Admission evidence:
  - Historical: the expectedFailure ratchet reproduces build-python#11
    through the real generator (open at HEAD; the generator is unchanged
    since the audit base 27639b49).
  - Mutations (executable here, not reverted fixtures): dropping a
    generated broadcast line must cost the variable its checked verdict
    (it resurfaces as an unknown and the coverage count drops), and
    doctoring a generated count must raise a bcastcount violation. Both
    prove the checker-as-oracle composition can fail.
  - Legal case: the verif_legal fixture must come out clean with the
    exact expected coverage count.

Run: python3 test/verification/properties/test_readnl_gen.py
"""

import logging
import sys
import tempfile
import unittest
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_ROOT = _THIS_FILE.parents[3]
sys.path.insert(0, str(_ROOT / "cime_config"))
sys.path.insert(0, str(_ROOT / "test" / "verification" / "checkers"))

# pylint: disable=wrong-import-position
import check_readnl_bcast as crb
from create_readnl_files import gen_namelist_files
# pylint: enable=wrong-import-position

# One variable per type x rank class of the namelist XML <type> grammar.
_LEGAL_VARS = [
    ("vg_int", "integer", "vg_main_nl"),
    ("vg_real", "real", "vg_main_nl"),
    ("vg_flag", "logical", "vg_main_nl"),
    ("vg_name", "char*24", "vg_main_nl"),
    ("vg_ivec", "integer(3)", "vg_main_nl"),
    ("vg_rvec", "real(2)", "vg_main_nl"),
    ("vg_lvec", "logical(2)", "vg_main_nl"),
    ("vg_cvec", "char*16(4)", "vg_main_nl"),
    ("vg_igrid", "integer(3,2)", "vg_main_nl"),
    ("vg_rgrid", "real(2,2)", "vg_aux_nl"),
    ("vg_tag", "char*8", "vg_aux_nl"),
]
# The build-python#11 class: a rank-2 character array.
_M11_VARS = [
    ("vm_cgrid", "char*16(2,3)", "vm_main_nl"),
]

_ENTRY = """  <entry id="{name}">
    <type>{typ}</type>
    <category>verification</category>
    <group>{group}</group>
    <standard_name>vfx_{name}</standard_name>
    <units>1</units>
    <desc>
      Verification fixture variable ({typ}).
    </desc>
    <values>
      <value>0</value>
    </values>
  </entry>
"""

_XML = """<?xml version="1.0"?>
<entry_id_pg version="2.0">
{entries}
</entry_id_pg>
"""


def _write_xml(path, variables):
    entries = "".join(_ENTRY.format(name=n, typ=t, group=g)
                      for n, t, g in variables)
    path.write_text(_XML.format(entries=entries))


def _generate(scheme, xml_path, outdir):
    logger = logging.getLogger(f"test_readnl_gen.{scheme}")
    logger.setLevel(logging.CRITICAL)
    args = ["--namelist-file-arg", f"{scheme}:{xml_path}",
            "--output-dir", str(outdir), "--quiet"]
    gen_namelist_files(args, str(outdir), logger)
    return outdir / (Path(xml_path).stem + ".F90")


def _check_text(text, rel):
    """Apply the checker rules to one Fortran source text."""
    findings, unknowns, counts = [], [], [0]
    scan = crb.FileScanNl(rel, text)
    crb.check_scan(scan, findings, unknowns, counts)
    return scan, findings, unknowns, counts[0]


class TestGeneratedReaders(unittest.TestCase):
    """The generated readers satisfy the readnl/bcast contract."""

    tmpdir = None
    legal_reader = None
    m11_reader = None
    master_reader = None

    @classmethod
    def setUpClass(cls):
        # pylint: disable=consider-using-with
        cls.tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmpdir.name)
        legal_xml = tmp / "verif_legal_namelist.xml"
        m11_xml = tmp / "verif_m11_namelist.xml"
        _write_xml(legal_xml, _LEGAL_VARS)
        _write_xml(m11_xml, _M11_VARS)
        legal_out = tmp / "legal"
        m11_out = tmp / "m11"
        legal_out.mkdir()
        m11_out.mkdir()
        # A generation failure here (e.g. a future generator that rejects
        # multi-dim character variables) must fail the suite loudly: see
        # the retirement note in the module docstring.
        cls.legal_reader = _generate("verif_legal", legal_xml, legal_out)
        cls.m11_reader = _generate("verif_m11", m11_xml, m11_out)
        cls.master_reader = legal_out / "cam_ccpp_scheme_namelists.F90"

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_generated_reader_reaches_every_rank(self):
        """Contracts 1+2 on the legal fixture, with parse-population
        checks so a clean verdict cannot be vacuous."""
        text = self.legal_reader.read_text()
        scan, findings, unknowns, n_checked = _check_text(
            text, self.legal_reader.name)
        # Full population: every fixture variable in its declared group.
        groups = {g: sorted(info["vars"]) for g, info in scan.groups.items()}
        want = {}
        for name, _, group in _LEGAL_VARS:
            want.setdefault(group, []).append(name)
        want = {g: sorted(v) for g, v in want.items()}
        self.assertEqual(groups, want)
        # Each group is read exactly once, under the generated root guard.
        read_groups = sorted(r[0] for r in scan.reads)
        self.assertEqual(read_groups, sorted(want))
        self.assertTrue(all(guarded for _, _, guarded, _ in scan.reads))
        # One broadcast per variable.
        self.assertEqual(sorted(s.buffer for s in scan.bcasts),
                         sorted(n for n, _, _ in _LEGAL_VARS))
        # Clean verdicts with full coverage: one rule-(a) check per
        # variable plus one rule-(b) check per broadcast site.
        self.assertEqual([f.message for f in findings], [])
        self.assertEqual([u[2] for u in unknowns], [])
        self.assertEqual(n_checked, 2 * len(_LEGAL_VARS))

    def test_master_reader_clean(self):
        """The generated master dispatch module stays out of the rules'
        way: no namelist groups, no broadcasts, no findings."""
        self.assertTrue(self.master_reader.is_file())
        scan, findings, unknowns, _ = _check_text(
            self.master_reader.read_text(), self.master_reader.name)
        self.assertEqual(scan.groups, {})
        self.assertEqual(scan.bcasts, [])
        self.assertEqual([f.message for f in findings], [])
        self.assertEqual([u[2] for u in unknowns], [])

    @unittest.expectedFailure
    def test_multidim_char_broadcast_is_valid_fortran(self):
        """build-python#11 ratchet: the rank-2 character broadcast count
        must agree with the declaration. Fails today: the generator emits
        len(vm_cgrid(1))*6, a one-index subscript of a rank-2 array.
        Remove the marker in the generator fix PR."""
        _, findings, _, _ = _check_text(self.m11_reader.read_text(),
                                        self.m11_reader.name)
        self.assertEqual(
            [f.message for f in findings if f.key.startswith("bcastcount:")],
            [])

    def test_oracle_detects_dropped_broadcast(self):
        """Mutation: deleting one generated broadcast line must cost the
        variable its checked verdict (module-scope variables resurface as
        unknowns, and coverage drops by the site and the variable)."""
        text = self.legal_reader.read_text()
        lines = [ln for ln in text.splitlines()
                 if "mpi_bcast(vg_int," not in ln]
        self.assertEqual(len(text.splitlines()) - len(lines), 1)
        _, findings, unknowns, n_checked = _check_text(
            "\n".join(lines), self.legal_reader.name)
        self.assertEqual([f.message for f in findings], [])
        self.assertTrue(any("vg_int" in msg for _, _, msg in unknowns),
                        unknowns)
        self.assertEqual(n_checked, 2 * len(_LEGAL_VARS) - 2)

    def test_oracle_detects_wrong_count(self):
        """Mutation: doctoring one generated count must raise a
        bcastcount violation."""
        text = self.legal_reader.read_text()
        mutated = text.replace("mpi_bcast(vg_igrid, 6,",
                               "mpi_bcast(vg_igrid, 7,")
        self.assertNotEqual(mutated, text)
        _, findings, _, _ = _check_text(mutated, self.legal_reader.name)
        self.assertEqual([f.key for f in findings],
                         [f"bcastcount:{self.legal_reader.name}:vg_igrid"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""MPI broadcast datatype must agree with the Fortran declaration and the
namelist XML <type>.

Guarantee statement
  Property: (a) at every `call mpi_bcast(buffer, count, datatype, ...)` in
    CAM-SIMA Fortran, the MPI datatype matches the buffer's declared Fortran
    type and kind; (b) every namelist-XML <entry> whose variable appears in a
    Fortran `namelist /group/` statement has a Fortran declaration matching
    the XML <type>. This is the P6 anti-pattern (rank-divergent state from a
    representation mismatch): a wrong datatype broadcasts the wrong bytes and
    non-master ranks keep garbage.
  Assumptions: buffers are declared in the same file as the bcast (same
    program unit or an enclosing module scope); the 8-byte real kinds in use
    are the ones listed in REAL8_KINDS; namelist XML <type> real means
    real(r8) by CAM convention.
  Checked domain: *.F90/*.f90 under src/ excluding the ncar_ccpp submodule;
    namelist_definition*.xml under src/ and cime_config/. Each bcast site and
    each XML entry gets a verdict: checked, violated, or unknown.
  Connection to production code: static analysis of the real sources; no
    execution.
  Blind spots: the count argument is not checked (a character bcast with the
    wrong length, or an array bcast with the wrong extent, passes);
    use-imported buffers, derived-type components, old-style declarations
    without `::`, and non-literal datatype arguments resolve to unknown, never
    to success; preprocessor conditionals are read as flat text (both arms are
    scanned).

Admission evidence: fires on F-se_time-1 (se_dribble_in_rsplit_loop declared
real(r8), broadcast as one mpi_integer, XML type integer) at CAM-SIMA
27639b49 and at 8d34b02c -- rules (a) and (b) each fire on it independently.
The self-test carries synthetic mutations for both rules.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlib

CHECKER = "check_bcast_types"

REAL8_KINDS = {"r8", "kind_phys", "shr_kind_r8", "8", "real64", "rkind",
               "kind_r8", "r8_kind", "kind_dyn"}
INT_DEFAULT_KINDS = {"", "i4", "shr_kind_i4", "4", "int32"}
INT8_KINDS = {"i8", "shr_kind_i8", "int64"}

# Fortran class -> MPI datatypes that agree with it (first entry = the
# conventional spelling in this codebase, used in messages).
AGREES = {
    "real8": ("mpi_real8", "mpi_double_precision"),
    "int": ("mpi_integer",),
    "int8": ("mpi_integer8",),
    "logical": ("mpi_logical",),
    "character": ("mpi_character",),
}

END_NONUNIT = {"do", "if", "select", "type", "interface", "associate",
               "where", "block", "enum", "forall", "team", "critical"}


def strip_comment_and_strings(line):
    """Blank out string literal contents and drop trailing ! comments."""
    out = []
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == quote:
                if i + 1 < len(line) and line[i + 1] == quote:
                    i += 2  # escaped quote inside the literal
                    continue
                quote = None
                out.append(c)
            else:
                out.append(" ")
            i += 1
            continue
        if c in "'\"":
            quote = c
            out.append(c)
        elif c == "!":
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def logical_lines(text):
    """Yield (start_lineno, statement) with continuations joined, strings and
    comments blanked, lowercased, and ;-separated statements split."""
    buf, start = "", None
    for lineno, raw in enumerate(text.splitlines(), 1):
        code = strip_comment_and_strings(raw).strip()
        if not code:
            if not buf:
                continue
            code = ""
        if buf:
            code = code.lstrip("&").lstrip()
        else:
            start = lineno
        if code.endswith("&"):
            buf += code[:-1].rstrip() + " "
            continue
        stmt = (buf + code).lower()
        buf = ""
        for part in split_top_level(stmt, ";"):
            part = part.strip()
            if part:
                yield start, part


def split_top_level(s, sep):
    parts, depth, cur = [], 0, []
    for c in s:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


UNIT_RE = re.compile(
    r"^(?:[a-z_]\w*\s*:\s*)?"                 # optional construct name
    r"(?:(?:pure|elemental|impure|recursive|"
    r"real(?:\([^)]*\))?|integer(?:\([^)]*\))?|logical|"
    r"character(?:\([^)]*\))?|double\s+precision|type\([^)]*\))\s+)*"
    r"(module|program|subroutine|function)\s+([a-z_]\w*)", re.VERBOSE)
DECL_RE = re.compile(
    r"^(real|integer|logical|character|complex|double\s+precision)"
    r"\s*(?:\(([^)]*)\))?\s*((?:,\s*[a-z_]\w*(?:\([^)]*\))?\s*)*)::\s*(.+)$")
END_RE = re.compile(r"^end(?:\s+([a-z]+))?\b")
BCAST_RE = re.compile(r"\bcall\s+mpi_bcast\s*\((.*)\)\s*$")
NAMELIST_RE = re.compile(r"^namelist\s*/\s*([a-z_]\w*)\s*/\s*(.+)$")


def classify_decl(base, kindspec):
    """Map a declaration to a type class, or None if the kind is unrecognized."""
    base = base.replace(" ", "")
    kind = (kindspec or "").replace(" ", "").lower()
    kind = re.sub(r"^kind=", "", kind)
    if base == "doubleprecision":
        return "real8"
    if base == "real":
        if kind in REAL8_KINDS:
            return "real8"
        return None  # default real or unrecognized kind: build-dependent
    if base == "integer":
        if kind in INT_DEFAULT_KINDS:
            return "int"
        if kind in INT8_KINDS:
            return "int8"
        return None
    if base == "logical":
        return "logical" if kind in ("", "4") else None
    if base == "character":
        return "character"
    return None


def decl_names(decl_list):
    """Names from a :: declaration list, dropping initializers and shapes."""
    names = []
    for item in split_top_level(decl_list, ","):
        item = split_top_level(item, "=")[0].strip()
        m = re.match(r"([a-z_]\w*)", item)
        if m:
            names.append(m.group(1))
    return names


class FileScan:
    """Declarations by scope, bcast sites, and namelist statements of one file."""

    def __init__(self, path, text):
        self.path = path
        self.bcasts = []      # (lineno, buffer_expr, datatype, scope_chain)
        self.namelists = {}   # var -> scope_chain where the namelist stmt sits
        scopes = [{}]         # stack of {name: (class_or_None, decl_repr)}
        in_interface = 0
        in_typedef = False
        for lineno, stmt in logical_lines(text):
            if stmt.startswith("interface") or stmt.startswith("abstract interface"):
                in_interface += 1
                continue
            if in_interface:
                if END_RE.match(stmt) and (END_RE.match(stmt).group(1) == "interface"):
                    in_interface -= 1
                continue
            if re.match(r"^type\s*(?:,[^:]*)?(?:::\s*[a-z_]\w*|\s+[a-z_]\w*)\s*$", stmt) \
                    and not stmt.startswith("type("):
                in_typedef = True
                continue
            if in_typedef:
                if END_RE.match(stmt) and END_RE.match(stmt).group(1) == "type":
                    in_typedef = False
                continue
            m = END_RE.match(stmt)
            if m:
                what = m.group(1)
                if (what is None or what in ("module", "subroutine", "function",
                                             "program", "procedure")) and len(scopes) > 1:
                    scopes.pop()
                continue
            m = UNIT_RE.match(stmt)
            if m and "::" not in stmt:
                scopes.append({})
                continue
            m = DECL_RE.match(stmt)
            if m:
                cls = classify_decl(m.group(1), m.group(2))
                for name in decl_names(m.group(4)):
                    scopes[-1][name] = (cls, f"{m.group(1)}({m.group(2) or ''})")
                continue
            m = NAMELIST_RE.match(stmt)
            if m:
                for var in m.group(2).replace("&", " ").split(","):
                    var = var.strip()
                    if re.match(r"^[a-z_]\w*$", var):
                        self.namelists[var] = [dict(s) for s in scopes]
                continue
            m = BCAST_RE.search(stmt)
            if m:
                args = [a.strip() for a in split_top_level(m.group(1), ",")]
                if len(args) >= 3:
                    self.bcasts.append((lineno, args[0], args[2],
                                        [dict(s) for s in scopes]))

    @staticmethod
    def lookup(scope_chain, name):
        for scope in reversed(scope_chain):
            if name in scope:
                return scope[name]
        return None


def check_bcasts(repo):
    findings, unknowns = [], []
    n_checked = 0
    src = repo / "src"
    files = sorted(p for p in src.rglob("*.F90") if "ncar_ccpp" not in p.parts)
    files += sorted(p for p in src.rglob("*.f90") if "ncar_ccpp" not in p.parts)
    scans = {}
    for path in files:
        rel = str(path.relative_to(repo))
        scan = FileScan(rel, path.read_text(errors="replace"))
        scans[rel] = scan
        for lineno, buf, dtype, chain in scan.bcasts:
            if not re.match(r"^mpi_[a-z_0-9]+$", dtype):
                unknowns.append((rel, lineno,
                                 f"bcast of '{buf}': non-literal datatype '{dtype}'"))
                continue
            if "%" in buf:
                unknowns.append((rel, lineno,
                                 f"bcast of derived-type component '{buf}' "
                                 f"as {dtype}: not resolved"))
                continue
            name_m = re.match(r"^([a-z_]\w*)\s*(\(|$)", buf)
            if not name_m:
                unknowns.append((rel, lineno,
                                 f"bcast buffer '{buf}': unsupported expression"))
                continue
            name = name_m.group(1)
            decl = FileScan.lookup(chain, name)
            if decl is None:
                unknowns.append((rel, lineno,
                                 f"bcast of '{name}' as {dtype}: no declaration "
                                 f"in file (use-imported?)"))
                continue
            cls, repr_ = decl
            if cls is None:
                unknowns.append((rel, lineno,
                                 f"bcast of '{name}' as {dtype}: unrecognized "
                                 f"kind in declaration {repr_}"))
                continue
            n_checked += 1
            if dtype not in AGREES[cls]:
                findings.append(vlib.Finding(
                    key=f"bcast:{rel}:{name}",
                    file=rel, line=lineno,
                    message=(f"'{name}' declared {repr_} but broadcast as "
                             f"{dtype} (expected {AGREES[cls][0]})")))
    return findings, unknowns, n_checked, scans


XML_BASE = {"integer": "int", "real": "real8", "logical": "logical",
            "char": "character"}


def check_namelist_xml(repo, scans):
    findings, unknowns = [], []
    n_checked = 0
    xmls = sorted((repo / "src").rglob("namelist_definition*.xml"))
    xmls += sorted((repo / "cime_config").glob("namelist_definition*.xml"))
    xmls = [p for p in xmls if "ncar_ccpp" not in p.parts]
    for xml_path in xmls:
        relx = str(xml_path.relative_to(repo))
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as exc:
            unknowns.append((relx, None, f"XML parse error: {exc}"))
            continue
        for entry in root.iter("entry"):
            eid = (entry.get("id") or "").lower()
            tnode = entry.find("type")
            if not eid or tnode is None or not (tnode.text or "").strip():
                continue
            xml_type = tnode.text.strip().lower()
            base = re.split(r"[*(]", xml_type)[0]
            expect = XML_BASE.get(base)
            if expect is None:
                unknowns.append((relx, None,
                                 f"entry '{eid}': unrecognized XML type '{xml_type}'"))
                continue
            holders = [(rel, s) for rel, s in scans.items() if eid in s.namelists]
            if not holders:
                unknowns.append((relx, None,
                                 f"entry '{eid}' ({xml_type}): no namelist "
                                 f"statement found in src"))
                continue
            for rel, scan in holders:
                decl = FileScan.lookup(scan.namelists[eid], eid)
                if decl is None:
                    unknowns.append((rel, None,
                                     f"namelist var '{eid}': no declaration in file"))
                    continue
                cls, repr_ = decl
                if cls is None:
                    unknowns.append((rel, None,
                                     f"namelist var '{eid}': unrecognized kind "
                                     f"in declaration {repr_}"))
                    continue
                n_checked += 1
                if cls != expect:
                    findings.append(vlib.Finding(
                        key=f"nmlxml:{eid}",
                        file=rel, line=None,
                        message=(f"namelist XML declares '{eid}' as {xml_type} "
                                 f"({relx}) but Fortran declares {repr_}")))
    return findings, unknowns, n_checked


SELF_TEST_F90 = """
module demo_mod
  use shr_kind_mod, only: r8 => shr_kind_r8
  implicit none
  real(r8) :: module_real
  integer  :: se_count
  real(r8) :: bad_var          ! real broadcast as integer: must fire
  character(len=256) :: fname
  logical :: flag
  namelist /demo_nl/ bad_var, se_count
contains
  subroutine readnl(obj)
    type(t), intent(inout) :: obj
    integer :: ierr
    real(r8) :: local_arr(4)
    call mpi_bcast(bad_var, 1, mpi_integer, 0, mpicom, ierr)
    call mpi_bcast(se_count, 1, mpi_integer, 0, mpicom, ierr)
    call mpi_bcast(module_real, 1, mpi_real8, 0, mpicom, ierr)
    call mpi_bcast(local_arr, 4, mpi_real8, 0, mpicom, ierr)
    call mpi_bcast(fname, len(fname), mpi_character, 0, &
                   mpicom, ierr)
    call mpi_bcast(flag, 1, mpi_logical, 0, mpicom, ierr)
    call mpi_bcast(imported_var, 1, mpi_integer, 0, mpicom, ierr)
    call mpi_bcast(obj%member, 1, mpi_integer, 0, mpicom, ierr)
  end subroutine readnl
end module demo_mod
"""

SELF_TEST_XML = """<?xml version="1.0"?>
<entry_id version="2.0">
  <entry id="bad_var"><type>integer</type></entry>
  <entry id="se_count"><type>integer</type></entry>
  <entry id="not_in_fortran"><type>real</type></entry>
</entry_id>
"""


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "src").mkdir()
        (repo / "cime_config").mkdir()
        (repo / "src" / "demo.F90").write_text(SELF_TEST_F90)
        (repo / "src" / "namelist_definition_demo.xml").write_text(SELF_TEST_XML)
        f_a, u_a, n_a, scans = check_bcasts(repo)
        f_b, u_b, n_b = check_namelist_xml(repo, scans)
    keys_a = {f.key for f in f_a}
    assert keys_a == {"bcast:src/demo.F90:bad_var"}, keys_a
    assert n_a == 6, n_a                      # 6 resolvable bcast buffers checked
    assert len(u_a) == 2, u_a                 # imported_var + obj%member
    keys_b = {f.key for f in f_b}
    assert keys_b == {"nmlxml:bad_var"}, keys_b
    assert n_b == 2, n_b                      # bad_var + se_count resolved
    assert any("not_in_fortran" in m for _, _, m in u_b), u_b
    print(f"{CHECKER}: self-test ok")
    return 0


def main():
    args = vlib.make_parser(__doc__.splitlines()[0]).parse_args()
    if args.self_test:
        return self_test()
    f_a, u_a, n_a, scans = check_bcasts(args.repo)
    f_b, u_b, n_b = check_namelist_xml(args.repo, scans)
    return vlib.report(CHECKER, args, f_a + f_b, u_a + u_b, n_a + n_b)


if __name__ == "__main__":
    sys.exit(main())

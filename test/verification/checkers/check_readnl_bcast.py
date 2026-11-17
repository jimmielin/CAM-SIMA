#!/usr/bin/env python3
"""Namelist values read on the root task must reach every rank.

Guarantee statement
  Property: (a) every variable in a Fortran `namelist /group/` statement whose
    group is read under a root-rank guard is either broadcast with `mpi_bcast`
    or provably consumed on the root task only; (b) at every
    `call mpi_bcast(buffer, count, ...)` the count agrees with the buffer's
    declared size (element count times character length); (c) no `mpi_bcast`
    sits inside rank-dependent control flow. This is the completeness
    companion of check_bcast_types (anti-pattern P6, rank-divergent state):
    a read-but-never-broadcast namelist variable silently keeps its default
    on every non-root rank, and a wrong count broadcasts a truncated or
    overrun buffer.
  Assumptions: root-rank guards are spelled with an identifier in ROOT_TOKENS
    (`masterproc` in src/, `mpi_isroot` in generated readers); namelist
    variables and broadcast buffers are declared in the same file; character
    lengths imported from shr_kind_mod have the pinned CESM values in
    SHR_KIND_LEN.
  Checked domain: *.F90/*.f90 under src/ excluding the ncar_ccpp submodule.
    Every namelist-group variable and every mpi_bcast site gets a verdict:
    checked, violated, or unknown.
  Connection to production code: static analysis of the real sources; no
    execution. scan_file()/check_scan() are importable so property suites can
    apply the same rules to generated reader modules.
  Blind spots: consumption of a module-scope namelist variable from another
    file is invisible, so a non-broadcast module variable with only guarded
    in-file uses resolves to unknown, never to success; rank-dependent guards
    not spelled with a ROOT_TOKENS identifier (e.g. `iam == 0`) are not
    recognized; partial-array broadcasts with runtime counts resolve to
    unknown; broadcast datatype agreement is check_bcast_types' rule, not
    this one's; preprocessor conditionals are read as flat text (both arms
    are scanned).

Admission evidence: rule (a) fires on history#9 (Sep 2026 audit) at CAM-SIMA
27639b49 and still at HEAD: hist_interp_out, hist_interp_nlat and
hist_interp_nlon are read from hist_file_config_nl on the root task, never
broadcast, and passed to config_set_up_hist_config on every rank
(src/history/cam_hist_file.F90). Rules (b) and (c) have no historical
instance in src/ (the Nov 2026 audit's scripted sweep found only the
F-se_time-1 datatype mismatch), so the self-test carries synthetic
mutations: a scalar broadcast with count 4, a literal length mismatch, a
len_trim truncation, the rank-mismatched len(v(1)) of build-python#11, and
a root-guarded broadcast. Legal shapes (root-only consumption, all-rank
read, named-constant and size()/len() counts) must pass.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlib
# Shared Fortran lexing: continuation joining, string/comment blanking,
# top-level splitting, and the unit/bcast statement shapes.
import check_bcast_types as fparse

CHECKER = "check_readnl_bcast"

ROOT_TOKENS = ("masterproc", "mpi_isroot")

# Pinned character lengths for names imported from shr_kind_mod. These are
# stable CESM-wide constants; pinning them lets a literal count be compared
# against a declaration spelled with the symbolic name.
SHR_KIND_LEN = {
    "shr_kind_cs": 80, "shr_kind_cm": 160, "shr_kind_cl": 256,
    "shr_kind_cx": 512, "shr_kind_cxx": 4096,
}

USE_RE = re.compile(r"^use\s+([a-z_]\w*)\s*,\s*only\s*:\s*(.+)$")
IF_RE = re.compile(r"^(?:[a-z_]\w*\s*:\s*)?if\s*\(")
ELSEIF_RE = re.compile(r"^else\s*if\s*\(")
ENDIF_RE = re.compile(r"^end\s*if\b")
READ_RE = re.compile(r"^read\s*\(")
NML_KWARG_RE = re.compile(r"\bnml\s*=\s*([a-z_]\w*)")
LEN_FACTOR_RE = re.compile(r"^len\s*\(\s*([a-z_]\w*)\s*(?:\((.*)\))?\s*\)$")
SIZE_FACTOR_RE = re.compile(r"^size\s*\(\s*([a-z_]\w*)\s*\)$")
TRUNC_FACTOR_RE = re.compile(r"^(len_trim\s*\(|len\s*\(\s*trim\s*\()")


def _strip_parens(s):
    """Strip balanced outer parentheses: '((x))' -> 'x'."""
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        for i, c in enumerate(s):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    return s
        s = s[1:-1].strip()
    return s


def _split_op(s, op):
    """Split s on the operator substring at parenthesis depth 0."""
    parts, depth, i, start = [], 0, 0, 0
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0 and s.startswith(op, i):
            parts.append(s[start:i])
            i += len(op)
            start = i
        else:
            i += 1
    parts.append(s[start:])
    return parts


def _take_parens(s):
    """s starts with '('; return (inner_text, remainder_after_close)."""
    depth = 0
    for i, c in enumerate(s):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return s[1:i], s[i + 1:].lstrip()
    return s[1:], ""


def classify_cond(cond):
    """Classify an if-condition for rank dependence.

    Returns (kind, pure): kind is 'root' (executes only on the root task),
    'nonroot' (never on the root task), or 'plain'; pure marks a bare token
    or its bare negation, the only forms whose else-branch is the clean
    complement."""
    c = _strip_parens(cond.strip())
    if c in ROOT_TOKENS:
        return "root", True
    m = re.fullmatch(r"\.not\.\s*(.+)", c)
    if m and _strip_parens(m.group(1)) in ROOT_TOKENS:
        return "nonroot", True
    if len(_split_op(c, ".or.")) > 1:
        return "plain", False
    for part in _split_op(c, ".and."):
        p = _strip_parens(part.strip())
        if p in ROOT_TOKENS:
            return "root", False
        m = re.fullmatch(r"\.not\.\s*(.+)", p)
        if m and _strip_parens(m.group(1)) in ROOT_TOKENS:
            return "nonroot", False
    return "plain", False


class Decl:    # pylint: disable=too-few-public-methods
    """One declared entity: type base, character length, array extents."""

    __slots__ = ("base", "lenspec", "extents", "is_param", "init")

    def __init__(self, base, lenspec, extents, is_param, init):
        self.base = base            # 'integer', 'real', 'character', ...
        self.lenspec = lenspec      # character length spec text, or None
        self.extents = extents      # list of extent spec texts, or None
        self.is_param = is_param
        self.init = init            # initializer text (for parameters)

    def __repr__(self):
        dims = f", dimension({','.join(self.extents)})" \
            if self.extents is not None else ""
        lenp = f"(len={self.lenspec})" if self.lenspec else ""
        return f"{self.base}{lenp}{dims}"


def _char_len(kindspec):
    """Character length from the (...) spec; default length is 1."""
    if not kindspec:
        return "1"
    parts = fparse.split_top_level(kindspec, ",")
    for i, part in enumerate(parts):
        part = part.strip()
        if part.startswith("len="):
            return part[4:].strip() or "1"
        if "=" not in part and i == 0:
            return part
    return "1"


def _parse_entity(item):
    """'name(dims)*len = init' -> (name, dims_list, entity_len, init)."""
    item = item.strip()
    m = re.match(r"([a-z_]\w*)", item)
    if not m:
        return None
    name, rest = m.group(1), item[m.end():].lstrip()
    dims = None
    length = None
    if rest.startswith("("):
        inner, rest = _take_parens(rest)
        dims = [d.strip() for d in fparse.split_top_level(inner, ",")]
    if rest.startswith("*"):
        rest = rest[1:].lstrip()
        if rest.startswith("("):
            length, rest = _take_parens(rest)
        else:
            m2 = re.match(r"\w+", rest)
            if m2:
                length, rest = m2.group(), rest[m2.end():].lstrip()
    init = None
    if rest.startswith("=>"):
        init = rest[2:].strip()
    elif rest.startswith("="):
        init = rest[1:].strip()
    return name, dims, length, init


class Scope:   # pylint: disable=too-few-public-methods
    """One program-unit scope: declarations, parameters, shr_kind imports."""

    def __init__(self, unit_id, is_module):
        self.unit_id = unit_id
        self.is_module = is_module
        self.decls = {}      # name -> Decl
        self.params = {}     # name -> initializer expression text
        self.renames = {}    # local name -> shr_kind_mod name


class BcastSite:    # pylint: disable=too-few-public-methods
    """One mpi_bcast call site."""

    __slots__ = ("lineno", "buffer", "count", "dtype", "rank_dependent",
                 "chain")

    def __init__(self, lineno, buffer, count, dtype, rank_dependent, chain):
        # pylint: disable=too-many-positional-arguments,too-many-arguments
        self.lineno = lineno
        self.buffer = buffer
        self.count = count
        self.dtype = dtype
        self.rank_dependent = rank_dependent
        self.chain = chain


class FileScanNl:   # pylint: disable=too-few-public-methods
    """Single-pass scan: scopes/declarations, namelist groups and their
    reads, mpi_bcast sites, and every other statement with its root-guard
    state (for the use analysis of non-broadcast namelist variables)."""

    def __init__(self, path, text):
        self.path = path
        self.groups = {}      # group -> {"vars", "lineno", "chain", "unit"}
        self.reads = []       # (group, lineno, root_guarded, units)
        self.bcasts = []      # BcastSite
        self.stmts = []       # (lineno, stmt, root_guarded, units)
        self.scopes = [Scope(0, False)]   # stack; all kept via chains
        self._units = [0]     # unit-id stack matching the scope stack
        self._next_unit = 1
        self._ifstack = []    # (kind, pure) per open if-construct
        self._if_base = [0]   # ifstack depth at each unit entry
        self._root_rest = [False]  # unit had 'if (.not. root) return'
        self._walk(text)

    # -- guard state -------------------------------------------------------
    def _root_guarded(self, extra=()):
        kinds = [k for k, _ in self._ifstack] + list(extra)
        return "root" in kinds or self._root_rest[-1]

    def _rank_dependent(self, extra=()):
        kinds = [k for k, _ in self._ifstack] + list(extra)
        return any(k != "plain" for k in kinds) or self._root_rest[-1]

    # -- scan --------------------------------------------------------------
    def _walk(self, text):
        in_interface = 0
        in_typedef = False
        for lineno, stmt in fparse.logical_lines(text):
            if stmt.startswith(("interface", "abstract interface")):
                in_interface += 1
                continue
            if in_interface:
                m = fparse.END_RE.match(stmt)
                if m and m.group(1) == "interface":
                    in_interface -= 1
                continue
            if re.match(r"^type\s*(?:,[^:]*)?(?:::\s*[a-z_]\w*|\s+[a-z_]\w*)\s*$",
                        stmt) and not stmt.startswith("type("):
                in_typedef = True
                continue
            if in_typedef:
                m = fparse.END_RE.match(stmt)
                if m and m.group(1) == "type":
                    in_typedef = False
                continue
            self._statement(lineno, stmt)

    def _statement(self, lineno, stmt, extra_guard=()):
        """Dispatch one logical statement. extra_guard carries the condition
        kinds of enclosing one-line ifs."""
        # pylint: disable=too-many-branches,too-many-return-statements
        if ENDIF_RE.match(stmt):
            if len(self._ifstack) > self._if_base[-1]:
                self._ifstack.pop()
            return
        if ELSEIF_RE.match(stmt) or stmt == "else" or stmt.startswith("else "):
            self._else(lineno, stmt)
            return
        m = IF_RE.match(stmt)
        if m:
            self._if_stmt(lineno, stmt, m, extra_guard)
            return
        m = fparse.END_RE.match(stmt)
        if m:
            what = m.group(1)
            if (what is None or what in ("module", "subroutine", "function",
                                         "program", "procedure")) \
                    and len(self.scopes) > 1:
                self.scopes.pop()
                self._units.pop()
                del self._ifstack[self._if_base.pop():]
                self._root_rest.pop()
            return
        m = fparse.UNIT_RE.match(stmt)
        if m and "::" not in stmt:
            is_module = m.group(1) in ("module", "program")
            self.scopes.append(Scope(self._next_unit, is_module))
            self._units.append(self._next_unit)
            self._next_unit += 1
            self._if_base.append(len(self._ifstack))
            self._root_rest.append(False)
            return
        m = USE_RE.match(stmt)
        if m:
            if m.group(1) == "shr_kind_mod":
                for item in fparse.split_top_level(m.group(2), ","):
                    if "=>" in item:
                        local, src = (p.strip() for p in item.split("=>", 1))
                    else:
                        local = src = item.strip()
                    if re.match(r"^[a-z_]\w*$", local):
                        self.scopes[-1].renames[local] = src
            return
        m = fparse.DECL_RE.match(stmt)
        if m:
            self._decl(m)
            return
        m = fparse.NAMELIST_RE.match(stmt)
        if m:
            grp = m.group(1)
            names = [v.strip() for v in m.group(2).replace("&", " ").split(",")]
            names = [v for v in names if re.match(r"^[a-z_]\w*$", v)]
            if grp in self.groups:
                self.groups[grp]["vars"].extend(names)
            else:
                self.groups[grp] = {"vars": names, "lineno": lineno,
                                    "chain": tuple(self.scopes),
                                    "unit": self._units[-1]}
            return
        if READ_RE.match(stmt):
            grp = self._read_group(stmt)
            if grp:
                self.reads.append((grp, lineno,
                                   self._root_guarded(extra_guard),
                                   tuple(self._units)))
            return
        m = fparse.BCAST_RE.search(stmt)
        if m:
            args = [a.strip() for a in fparse.split_top_level(m.group(1), ",")]
            if len(args) >= 3:
                self.bcasts.append(BcastSite(
                    lineno, args[0], args[1], args[2],
                    self._rank_dependent(extra_guard), tuple(self.scopes)))
            return
        self.stmts.append((lineno, stmt, self._root_guarded(extra_guard),
                           tuple(self._units)))

    def _if_stmt(self, lineno, stmt, m, extra_guard):
        head = stmt[:m.end() - 1]      # construct name + 'if', sans '('
        cond, rest = _take_parens(stmt[len(head):])
        kind, pure = classify_cond(cond)
        # The condition itself reads its variables wherever the if sits.
        self.stmts.append((lineno, cond, self._root_guarded(extra_guard),
                           tuple(self._units)))
        if rest == "then":
            self._ifstack.append((kind, pure))
            return
        # One-line if: the branch statement runs under the condition.
        if rest == "return" and kind == "nonroot" and not self._ifstack \
                and not extra_guard:
            # 'if (.not. root) return' at the top level of a unit body:
            # the rest of the unit executes on the root task only.
            self._root_rest[-1] = True
            return
        if rest:
            self._statement(lineno, rest, extra_guard + (kind,))

    def _else(self, lineno, stmt):
        if len(self._ifstack) <= self._if_base[-1]:
            return
        kind, pure = self._ifstack.pop()
        if pure and kind == "root":
            base = "nonroot"
        elif pure and kind == "nonroot":
            base = "root"
        else:
            base = "plain"
        m = ELSEIF_RE.match(stmt)
        if m:
            cond, _ = _take_parens(stmt[m.end() - 1:])
            # The else-if condition reads its variables outside the branch.
            self.stmts.append((lineno, cond, self._root_guarded(),
                               tuple(self._units)))
            ckind, _ = classify_cond(cond)
            if base == "plain":
                base = ckind
        self._ifstack.append((base, False))

    def _decl(self, m):
        base = m.group(1).replace(" ", "")
        kindspec = m.group(2)
        attrs = (m.group(3) or "").lower()
        is_param = re.search(r"\bparameter\b", attrs) is not None
        attr_dims = None
        dm = re.search(r"dimension\s*\(", attrs)
        if dm:
            inner, _ = _take_parens(attrs[dm.end() - 1:])
            attr_dims = [d.strip() for d in fparse.split_top_level(inner, ",")]
        lenspec = _char_len(kindspec) if base == "character" else None
        scope = self.scopes[-1]
        for item in fparse.split_top_level(m.group(4), ","):
            ent = _parse_entity(item)
            if not ent:
                continue
            name, dims, entity_len, init = ent
            decl = Decl(base, entity_len or lenspec,
                        dims if dims is not None else attr_dims,
                        is_param, init)
            scope.decls[name] = decl
            if is_param and base == "integer" and init:
                scope.params[name] = init

    def _read_group(self, stmt):
        """Group name if stmt is a namelist read of a known group."""
        inner, _ = _take_parens(stmt[stmt.index("("):])
        args = [a.strip() for a in fparse.split_top_level(inner, ",")]
        for arg in args:
            km = NML_KWARG_RE.match(arg)
            if km and km.group(1) in self.groups:
                return km.group(1)
        if len(args) >= 2 and re.fullmatch(r"[a-z_]\w*", args[1]) \
                and args[1] in self.groups:
            return args[1]
        return None

    # -- lookups -----------------------------------------------------------
    @staticmethod
    def lookup(chain, name):
        """(Decl, Scope) for name along a scope chain, or (None, None)."""
        for scope in reversed(chain):
            if name in scope.decls:
                return scope.decls[name], scope
        return None, None


# -- integer expression resolution ------------------------------------------

class _Unresolved(Exception):
    pass


def _resolve_name(name, chain, depth):
    for scope in reversed(chain):
        if name in scope.params:
            return resolve_int(scope.params[name], chain, depth + 1)
        if name in scope.renames:
            return SHR_KIND_LEN.get(scope.renames[name])
    return SHR_KIND_LEN.get(name)


def resolve_int(expr, chain, depth=0):
    """Evaluate an integer expression of literals, local parameters and
    shr_kind constants. Returns an int, or None if anything is opaque."""
    if depth > 8:
        return None
    tokens = re.findall(r"\d+|[a-z_]\w*|[()+\-*/]", expr.replace(" ", ""))
    if "".join(tokens) != expr.replace(" ", ""):
        return None
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        tok = peek()
        pos[0] += 1
        return tok

    def primary():
        tok = take()
        if tok == "(":
            val = addsub()
            if take() != ")":
                raise _Unresolved()
            return val
        if tok == "-":
            return -primary()
        if tok == "+":
            return primary()
        if tok is not None and tok.isdigit():
            return int(tok)
        if tok is not None and re.match(r"^[a-z_]", tok):
            if peek() == "(":           # function reference: opaque
                raise _Unresolved()
            val = _resolve_name(tok, chain, depth)
            if val is None:
                raise _Unresolved()
            return val
        raise _Unresolved()

    def muldiv():
        val = primary()
        while peek() in ("*", "/"):
            if take() == "*":
                val *= primary()
            else:
                rhs = primary()
                if rhs == 0:
                    raise _Unresolved()
                val = int(val / rhs)    # Fortran integer division truncates
        return val

    def addsub():
        val = muldiv()
        while peek() in ("+", "-"):
            if take() == "+":
                val += muldiv()
            else:
                val -= muldiv()
        return val

    try:
        val = addsub()
    except (_Unresolved, IndexError):
        return None
    return val if pos[0] == len(tokens) else None


# -- rule B: the count argument ----------------------------------------------

def _parse_buffer(buf):
    """'v', 'v(:)', 'v(1,2)' -> (name, subscripts or None); else None."""
    m = re.match(r"^([a-z_]\w*)\s*(\()?", buf)
    if not m or "%" in buf:
        return None
    name = m.group(1)
    if not m.group(2):
        return (name, None) if buf.strip() == name else None
    inner, rest = _take_parens(buf[buf.index("("):])
    if rest:
        return None
    return name, [s.strip() for s in fparse.split_top_level(inner, ",")]


def _count_factors(count, bufname, decl):
    """Parse the count into factors. Returns (factors, fatal) where factors
    is a list of ('len'|'size'|'tok', text) and fatal is a violation
    message, or (None, None) when a factor is opaque."""
    factors = []
    for raw in _split_op(count, "*"):
        f = raw.strip()
        if TRUNC_FACTOR_RE.match(f):
            return None, (f"count '{count}' uses len_trim: non-root ranks "
                          f"receive a truncated string")
        m = LEN_FACTOR_RE.match(f)
        if m and m.group(1) == bufname:
            sub = m.group(2)
            if sub is not None:
                rank = len(decl.extents) if decl.extents is not None else 0
                nidx = len(fparse.split_top_level(sub, ","))
                if rank == 0:
                    return None, (f"count factor '{f}' subscripts the scalar "
                                  f"'{bufname}'")
                if nidx != rank:
                    return None, (f"count factor '{f}' gives {nidx} "
                                  f"subscript(s) to rank-{rank} '{bufname}': "
                                  f"invalid Fortran")
            factors.append(("len", f))
            continue
        m = SIZE_FACTOR_RE.match(f)
        if m and m.group(1) == bufname:
            factors.append(("size", f))
            continue
        factors.append(("tok", f.replace(" ", "")))
    return factors, None


def _extent_token(dim):
    """Extent expression for one declared dimension spec, or None."""
    dim = dim.replace(" ", "")
    if dim in (":", "*"):
        return None
    if ":" in dim:
        lo, hi = dim.split(":", 1)
        return f"({hi})-({lo})+1"
    return dim


def _match_factors(factors, exp_len, exp_extents, chain):
    """Match count factors against the expected size. Returns 'ok',
    'violated', or 'unknown'."""
    # pylint: disable=too-many-return-statements,too-many-branches
    expected = []
    if exp_len is not None:
        expected.append(("len", exp_len))
    expected.extend(("ext", _extent_token(d)) for d in exp_extents)

    remaining = list(expected)
    leftovers = []
    for kind, text in factors:
        if kind == "len":
            hit = next((e for e in remaining if e[0] == "len"), None)
            if hit is None:
                return "violated"       # len() factor for a non-character
            remaining.remove(hit)
        elif kind == "size":
            if not any(e[0] == "ext" for e in remaining):
                return "violated"       # size() factor for a scalar
            remaining = [e for e in remaining if e[0] != "ext"]
        else:
            hit = None
            for e in remaining:
                if e[1] is not None and e[1].replace(" ", "") == text:
                    hit = e
                    break
                rv_e = resolve_int(e[1], chain) if e[1] is not None else None
                if rv_e is not None and rv_e == resolve_int(text, chain):
                    hit = e
                    break
            if hit is not None:
                remaining.remove(hit)
            else:
                leftovers.append(text)
    if not remaining and not leftovers:
        return "ok"
    # Fall back to comparing fully resolved products.
    want = 1
    for _, tok in expected:
        val = resolve_int(tok, chain) if tok is not None else None
        if val is None:
            return "unknown"
        want *= val
    got = 1
    for kind, text in factors:
        if kind == "len":
            val = resolve_int(exp_len, chain) if exp_len is not None else None
        elif kind == "size":
            val = 1
            for dim in exp_extents:
                ext = _extent_token(dim)
                dv = resolve_int(ext, chain) if ext is not None else None
                if dv is None:
                    return "unknown"
                val *= dv
        else:
            val = resolve_int(text, chain)
        if val is None:
            return "unknown"
        got *= val
    return "ok" if got == want else "violated"


def check_count(site, decl, chain):
    """Verdict ('ok'|'violated'|'unknown', message) for one bcast count."""
    # pylint: disable=too-many-return-statements,too-many-branches
    parsed = _parse_buffer(site.buffer)
    name, subs = parsed
    factors, fatal = _count_factors(site.count, name, decl)
    if fatal:
        return "violated", fatal
    if factors is None:
        return "unknown", "opaque count factor"
    is_char = decl.base == "character"
    exp_len = decl.lenspec if is_char else None
    extents = decl.extents
    whole = subs is None or (extents is not None
                             and all(s == ":" for s in subs))
    if extents is None or not whole:
        if subs is not None and extents is not None \
                and any(":" in s for s in subs):
            return "unknown", "array-section broadcast not analyzed"
        # Scalar, or an element reference: a single element is expected...
        verdict = _match_factors(factors, exp_len, [], chain)
        if verdict == "ok":
            return "ok", ""
        if subs is not None and extents is not None \
                and all(s == "1" for s in subs):
            # ...but broadcasting the whole array from its first element is
            # the legal F77-style sequence-association shape.
            if _match_factors(factors, exp_len, extents, chain) == "ok":
                return "ok", ""
            return "unknown", "count matches neither one element nor the " \
                              "whole array"
        if extents is not None:
            return "unknown", "partial broadcast from an element not analyzed"
        if verdict == "violated":
            return "violated", (f"'{name}' is scalar "
                                f"({decl!r}) but the count is '{site.count}'")
        return "unknown", f"count '{site.count}' not resolvable"
    verdict = _match_factors(factors, exp_len, extents, chain)
    if verdict == "violated":
        return "violated", (f"count '{site.count}' does not match the "
                            f"declared size of '{name}' ({decl!r})")
    if verdict == "unknown":
        return "unknown", (f"count '{site.count}' vs declaration {decl!r}: "
                           f"not resolvable")
    return "ok", ""


# -- rule A: completeness -----------------------------------------------------

ASSIGN_RE = re.compile(r"^([a-z_]\w*)\s*(\(|=(?!=))")


def _pure_assignment_of(stmt, var):
    """True when stmt assigns to var without reading it (a default)."""
    m = re.match(rf"^{var}\s*(\()?", stmt)
    if not m:
        return False
    rest = stmt[m.end() - 1 if m.group(1) else m.end():]
    if m.group(1):
        subs, rest = _take_parens(rest)
        if re.search(rf"\b{var}\b", subs):
            return False
    rest = rest.lstrip()
    if not rest.startswith("=") or rest.startswith("==") \
            or rest.startswith("=>"):
        return False
    return not re.search(rf"\b{var}\b", rest[1:])


def unguarded_uses(scan, var, decl_unit, read_unit, read_line):
    """Statements that read var where non-root ranks execute. Pre-read
    statements of the reading unit see the uniform default and are skipped."""
    pat = re.compile(rf"\b{var}\b")
    uses = []
    for lineno, stmt, guarded, units in scan.stmts:
        if guarded or decl_unit not in units:
            continue
        if read_unit in units and lineno <= read_line:
            continue
        if not pat.search(stmt):
            continue
        if _pure_assignment_of(stmt, var):
            continue
        uses.append((lineno, stmt))
    return uses


def check_scan(scan, findings, unknowns, counts):
    """Apply all three rules to one scanned file. counts is a single-element
    list holding the running checked total."""
    # pylint: disable=too-many-branches,too-many-locals
    rel = scan.path
    bcast_names = set()
    for site in scan.bcasts:
        parsed = _parse_buffer(site.buffer)
        if parsed:
            bcast_names.add(parsed[0])

    # Rule A: every root-read namelist variable reaches every rank.
    for grp, info in scan.groups.items():
        reads = [r for r in scan.reads if r[0] == grp]
        if not reads:
            unknowns.append((rel, info["lineno"],
                             f"namelist /{grp}/ is never read in this file"))
            continue
        if any(not guarded for _, _, guarded, _ in reads):
            counts[0] += len(info["vars"])   # all ranks read the file
            continue
        _, read_line, _, read_units = reads[0]
        read_unit = read_units[-1]
        for var in info["vars"]:
            if var in bcast_names:
                counts[0] += 1
                continue
            decl, scope = scan.lookup(info["chain"], var)
            if decl is None:
                unknowns.append((rel, info["lineno"],
                                 f"namelist var '{var}' (/{grp}/): no "
                                 f"declaration in file"))
                continue
            uses = unguarded_uses(scan, var, scope.unit_id, read_unit,
                                  read_line)
            if uses:
                findings.append(vlib.Finding(
                    key=f"readnl:{rel}:{var}", file=rel, line=uses[0][0],
                    message=(f"'{var}' in namelist /{grp}/ is read on the "
                             f"root task but never broadcast; used on all "
                             f"ranks (line {uses[0][0]})")))
            elif scope.is_module:
                unknowns.append((rel, info["lineno"],
                                 f"namelist var '{var}' (/{grp}/) is not "
                                 f"broadcast; no unguarded use here, but the "
                                 f"module variable may be used elsewhere"))
            else:
                counts[0] += 1               # root-only consumption

    # Rules B and C over every bcast site.
    for site in scan.bcasts:
        if site.rank_dependent:
            findings.append(vlib.Finding(
                key=f"bcastguard:{rel}:{site.buffer}", file=rel,
                line=site.lineno,
                message=(f"mpi_bcast of '{site.buffer}' sits inside "
                         f"rank-dependent control flow: the collective "
                         f"cannot be reached by all ranks")))
        parsed = _parse_buffer(site.buffer)
        if not parsed:
            unknowns.append((rel, site.lineno,
                             f"bcast buffer '{site.buffer}': unsupported "
                             f"expression"))
            continue
        decl, _ = scan.lookup(site.chain, parsed[0])
        if decl is None:
            unknowns.append((rel, site.lineno,
                             f"bcast of '{parsed[0]}': no declaration in "
                             f"file (use-imported?)"))
            continue
        verdict, msg = check_count(site, decl, site.chain)
        if verdict == "ok":
            counts[0] += 1
        elif verdict == "violated":
            counts[0] += 1
            findings.append(vlib.Finding(
                key=f"bcastcount:{rel}:{parsed[0]}", file=rel,
                line=site.lineno, message=f"bcast of '{site.buffer}': {msg}"))
        else:
            unknowns.append((rel, site.lineno,
                             f"bcast of '{site.buffer}': {msg}"))


def scan_file(path, rel):
    """Scan one Fortran source file."""
    return FileScanNl(rel, path.read_text(errors="replace"))


def check_repo(repo):
    """Scan and check every Fortran file under <repo>/src."""
    findings, unknowns, counts = [], [], [0]
    src = repo / "src"
    files = sorted(p for p in src.rglob("*.F90") if "ncar_ccpp" not in p.parts)
    files += sorted(p for p in src.rglob("*.f90") if "ncar_ccpp" not in p.parts)
    for path in files:
        rel = str(path.relative_to(repo))
        check_scan(scan_file(path, rel), findings, unknowns, counts)
    return findings, unknowns, counts[0]


# -- self-test ----------------------------------------------------------------

SELF_TEST_F90 = """
module demo_nl_mod
  use shr_kind_mod, only: r8 => shr_kind_r8, cl => shr_kind_cl
  implicit none
  private
  integer, parameter :: flen = 16
  integer :: module_opt          ! module-scope, not bcast: unknown
contains
  subroutine demo_readnl(nlfile)
    character(len=*), intent(in) :: nlfile
    integer  :: good_count, lost_nlat, ierr, unitn, idx
    logical  :: lost_out
    real(r8) :: master_only
    character(len=flen) :: good_name
    character(len=cl)   :: short_name       ! bcast with literal 32: fires
    character(len=flen) :: tags(4)
    character(len=flen) :: grid2(2,3)       ! len(grid2(1)) count: fires
    integer  :: vec(3)
    integer  :: file_kind
    namelist /demo_nl/ good_count, lost_out, lost_nlat, master_only,       &
         good_name, short_name, tags, grid2, vec, module_opt
    good_count = 0
    lost_out = .false.
    lost_nlat = 0
    master_only = 0.0_r8
    if (masterproc) then
       open(newunit=unitn, file=trim(nlfile), status='old')
       read(unitn, demo_nl, iostat=ierr)
       close(unitn)
       ! master_only is consumed under the guard: legal, no bcast needed
       if (master_only > 0.0_r8) then
          call note_master(master_only)
       end if
    end if
    call mpi_bcast(good_count, 1, mpi_integer, 0, mpicom, ierr)
    call mpi_bcast(good_name, len(good_name), mpi_character, 0, mpicom, ierr)
    call mpi_bcast(short_name, 32, mpi_character, 0, mpicom, ierr)
    call mpi_bcast(tags, len(tags(1))*4, mpi_character, 0, mpicom, ierr)
    call mpi_bcast(grid2, len(grid2(1))*6, mpi_character, 0, mpicom, ierr)
    call mpi_bcast(vec, 4, mpi_integer, 0, mpicom, ierr)
    if (masterproc) then
       call mpi_bcast(file_kind, 1, mpi_integer, 0, mpicom, ierr)
    end if
    ! lost_out and lost_nlat were never broadcast: these uses diverge
    call configure(lost_out, lost_nlat)
    do idx = 1, good_count
       call apply_tag(tags(idx))
    end do
  end subroutine demo_readnl

  subroutine allrank_readnl(nlfile)
    character(len=*), intent(in) :: nlfile
    integer :: unitn, ierr
    integer :: shared_count
    namelist /allrank_nl/ shared_count
    shared_count = 0
    open(newunit=unitn, file=trim(nlfile), status='old')
    read(unitn, nml=allrank_nl, iostat=ierr)
    close(unitn)
    call configure_counts(shared_count)   ! legal: every rank read the file
  end subroutine allrank_readnl

  subroutine trunc_bcast(nlfile)
    character(len=*), intent(in) :: nlfile
    integer :: unitn, ierr
    character(len=cl) :: trunc_name
    namelist /trunc_nl/ trunc_name
    trunc_name = ''
    if (masterproc) then
       open(newunit=unitn, file=trim(nlfile), status='old')
       read(unitn, trunc_nl, iostat=ierr)
       close(unitn)
    end if
    call mpi_bcast(trunc_name, len_trim(trunc_name), mpi_character, 0,     &
         mpicom, ierr)
  end subroutine trunc_bcast
end module demo_nl_mod
"""


def self_test():
    """Embedded legal + mutation fixture; every rule must fire."""
    # pylint: disable=too-many-locals
    import tempfile                      # pylint: disable=import-outside-toplevel
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "src").mkdir()
        (repo / "src" / "demo_nl.F90").write_text(SELF_TEST_F90)
        findings, unknowns, n_checked = check_repo(repo)
    keys = sorted(f.key for f in findings)
    rel = "src/demo_nl.F90"
    assert keys == [
        f"bcastcount:{rel}:grid2",       # len(grid2(1)) on a rank-2 array
        f"bcastcount:{rel}:short_name",  # 32 vs shr_kind_cl=256
        f"bcastcount:{rel}:trunc_name",  # len_trim truncation
        f"bcastcount:{rel}:vec",         # 4 vs declared vec(3)
        f"bcastguard:{rel}:file_kind",   # collective under if (masterproc)
        f"readnl:{rel}:lost_nlat",       # read on root, used on all ranks
        f"readnl:{rel}:lost_out",
    ], keys
    # Checked: good_count, good_name, short_name, tags, grid2, vec,
    # master_only (root-only use), shared_count (all-rank read), trunc_name's
    # group membership is covered by its bcast, plus the count-ok sites
    # (good_count, good_name, tags, file_kind) and the count-violated sites,
    # which also count as checked.
    assert n_checked == 17, n_checked
    # module_opt: module-scope namelist var without bcast -> unknown.
    assert any("module_opt" in msg for _, _, msg in unknowns), unknowns
    assert not any("master_only" in msg for _, _, msg in unknowns), unknowns
    print(f"{CHECKER}: self-test ok")
    return 0


def main():
    """CLI entry point."""
    args = vlib.make_parser(__doc__.splitlines()[0]).parse_args()
    if args.self_test:
        return self_test()
    findings, unknowns, n_checked = check_repo(args.repo)
    return vlib.report(CHECKER, args, findings, unknowns, n_checked)


if __name__ == "__main__":
    sys.exit(main())

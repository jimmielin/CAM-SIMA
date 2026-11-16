#!/usr/bin/env python3
"""Registry-generator property suite: class properties over
src/data/generate_registry_data.py (gen_registry).

Guarantee statement
  Property (four contracts, each quantified over every variable of every
  checked registry):
    1. Metadata round-trip: every non-private, non-constituent registry
       variable appears in the generated .meta exactly once with matching
       standard_name, units, type, kind, dimensions and protected status
       (protected = XML access "protected" or allocatable "parameter"), both
       when the .meta is parsed back with the framework parser and when it is
       re-ingested through the production <metadata_file> path.
    2. Declaration-order independence: permuting the <variable> declarations
       of a registry leaves every variable's resolved dimensions, the
       generated .meta/.F90 artifacts (as line multisets), and the returned
       ic-name/constituent/restart/initial-value facts unchanged.
    3. Dimension-resolution idempotence: resolving a File's dimensions a
       second time changes no variable's dimensions, provided no local name
       aliases another variable's standard name.
    4. Determinism: generation output is byte-identical across processes
       with different PYTHONHASHSEED values.
  Assumptions: registries are rendered schema-valid (gen_registry runs with
    error_on_no_validate=True, so validation failures are loud); a DDT node
    follows its member variables and precedes variables of the DDT type
    (a parse-order requirement of the registry format, not under test);
    explicit-shape variables only use dimensions provided by variables in
    the same table (production layout).
  Checked domain: deterministic fixture registries below plus (when
    Hypothesis is installed) derandomized draws over variable specs:
    real/integer/logical scalars and arrays, parameter/pointer/allocatable/
    target allocation, public/private/protected access, initial values,
    ic_file_input_names, constituents, restart and tstep-init flags, host
    and parameter dimensions, one optional DDT with an instance variable.
  Connection to production code: executes the real gen_registry (including
    xmllint schema validation), the real framework metadata parser, and the
    real <metadata_file> re-ingest path; expected facts are recomputed from
    the input specs, never from generator internals.
  Blind spots: <array>/<element> nodes and dycore-conditional initial_value
    attributes are not drawn (example-based coverage in test/unit/python);
    character and complex variables are not drawn; the generated Fortran is
    not compiled, so contracts outside the written text (e.g. argument
    mismatches against the real host) are unseen; allocation attributes are
    legitimately absent from metadata, so the round-trip does not compare
    them; re-ingest requires in-table dimension providers, mirroring
    production metadata layout.

Admission evidence
  - Order independence fired historically: before PR #520 (CAM-SIMA
    ce8331c2; audit base 27639b49 predates it), dimensions were resolved
    during parse, so test_param_after_consumer_order_insensitive's base
    order raises CCPPError ("Dimension not found") on the old code while
    the permuted order succeeds. Verified by materializing the 27639b49
    module on PYTHONPATH and replaying the instance.
  - Idempotence can fail: test_alias_corner_detector_fires demonstrates the
    detector on a registry where a parameter's standard name aliases another
    parameter's local name (a second resolution pass rewrites dimensions
    again). If resolve_dimensions is ever made alias-safe, that test fails
    as "unexpectedly idempotent": remove it and add alias draws to the
    quantified class.
  - Round-trip and determinism fail under deliberate mutation (validated
    before admission): dropping the units line in VarBase.write_metadata
    fails round-trip; iterating the known-dimensions set unsorted in
    write_allocate_routine fails determinism across hash seeds.
  - Legal cases: every green run of the fixtures and strategies below.

Run: python3 test/verification/properties/test_registry_gen.py
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_ROOT = _THIS_FILE.parents[3]
sys.path.insert(0, str(_ROOT / "src" / "data"))

# generate_registry_data appends the ccpp_framework scripts directory to
# sys.path at import, so this suite needs the submodule populated
# (git-fleximod), like the build-cache suite.
# pylint: disable=wrong-import-position
from generate_registry_data import gen_registry   # noqa: E402
from framework_env import CCPPFrameworkEnv        # noqa: E402
from metadata_table import parse_metadata_file    # noqa: E402
# pylint: enable=wrong-import-position

try:
    from hypothesis import given, settings, HealthCheck
    from hypothesis import strategies as st
    HAVE_HYPOTHESIS = True
    # Keep all Hypothesis storage (example DB and the constants cache, which
    # ignores database=None) out of the repository root.
    import hypothesis.configuration as _hypothesis_config
    _hypothesis_config.set_hypothesis_home_dir(
        tempfile.mkdtemp(prefix="cam_hypothesis_"))
except ImportError:
    HAVE_HYPOTHESIS = False

_LOGGER = logging.getLogger("cam_registry_prop")
_LOGGER.setLevel(logging.ERROR)
_LOGGER.addHandler(logging.NullHandler())

# Host-model dimensions and the provider variables generated for them when
# an explicit-shape variable needs them resolvable inside the table.
_HOST_DIMS = {"horizontal_dimension": "ncol_prop",
              "vertical_layer_dimension": "pver_prop"}

_MODULE_NAME = "prop_types"
_DDT_NAME = "prop_ddt_t"


@dataclass(frozen=True)
class VarSpec:
    """One registry <variable> entry, as facts (the oracle side)."""
    local_name: str
    standard_name: str
    units: str = "m"
    vtype: str = "real"
    kind: str = ""
    dims: tuple = ()
    allocatable: str = ""
    access: str = "public"
    initial_value: str = ""
    ic_names: tuple = ()
    constituent: bool = False
    restart: bool = False
    tstep_init: bool = False
    ddt_member: bool = False


@dataclass(frozen=True)
class RegSpec:
    """One registry: variables in XML order, an optional DDT over the
    ddt_member variables with an optional instance variable, and optional
    <metadata_file> entries given as (basename, content) pairs."""
    variables: tuple
    ddt_name: str = ""
    instance: object = None
    meta_files: tuple = ()


def render_variable(spec):
    """Render <spec> as registry XML (schema element order)."""
    attrs = [f'local_name="{spec.local_name}"',
             f'standard_name="{spec.standard_name}"',
             f'units="{spec.units}"', f'type="{spec.vtype}"']
    if spec.kind:
        attrs.append(f'kind="{spec.kind}"')
    if spec.allocatable:
        attrs.append(f'allocatable="{spec.allocatable}"')
    if spec.access != "public":
        attrs.append(f'access="{spec.access}"')
    if spec.constituent:
        attrs.append('constituent="true"')
    if spec.restart:
        attrs.append('restart="true"')
    if spec.tstep_init:
        attrs.append('phys_timestep_init_zero="true"')
    body = []
    if spec.dims:
        body.append(f"<dimensions>{' '.join(spec.dims)}</dimensions>")
    if spec.initial_value:
        body.append(f"<initial_value>{spec.initial_value}</initial_value>")
    if spec.ic_names:
        body.append("<ic_file_input_names>"
                    f"{' '.join(spec.ic_names)}</ic_file_input_names>")
    if body:
        inner = "\n      ".join(body)
        return (f'    <variable {" ".join(attrs)}>\n'
                f'      {inner}\n    </variable>')
    return f'    <variable {" ".join(attrs)}/>'


def render_registry(reg, perm=None):
    """Render <reg> as a registry XML document. <perm> optionally permutes
    the variable declarations; the DDT node and its instance variable keep
    their positions (parse-order requirement of the format)."""
    variables = list(reg.variables)
    if perm is not None:
        variables = [variables[i] for i in perm]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<registry name="cam_registry" version="1.0">']
    for fname, _ in reg.meta_files:
        parts.append(f'  <metadata_file>{fname}</metadata_file>')
    parts.append(f'  <file name="{_MODULE_NAME}" type="module">')
    parts.append('    <use module="ccpp_kinds" reference="kind_phys"/>')
    parts.extend(render_variable(v) for v in variables)
    if reg.ddt_name:
        members = "".join(f"<data>{v.standard_name}</data>"
                          for v in reg.variables if v.ddt_member)
        parts.append(f'    <ddt type="{reg.ddt_name}">{members}</ddt>')
        if reg.instance:
            parts.append(render_variable(reg.instance))
    parts.append('  </file>')
    parts.append('</registry>')
    return "\n".join(parts) + "\n"


class GenRun:
    """One gen_registry run on a rendered registry in a fresh workspace."""

    def __init__(self, reg, perm=None, dycore="se"):
        self.ws = Path(tempfile.mkdtemp(prefix="cam_reg_prop_"))
        srcmods = self.ws / "SourceMods"
        srcmods.mkdir()
        for fname, content in reg.meta_files:
            (srcmods / fname).write_text(content)
        regfile = self.ws / "registry.xml"
        regfile.write_text(render_registry(reg, perm=perm))
        self.outdir = self.ws / "out"
        (self.retcode, self.files, self.ic_names, self.constituents,
         self.restart, self.vars_init_value) = gen_registry(
            str(regfile), dycore, str(self.outdir), 3, str(srcmods),
            str(_ROOT), logger=_LOGGER, error_on_no_validate=True)

    def outputs(self):
        """Generated artifacts as {filename: text}."""
        return {p.name: p.read_text()
                for p in sorted(self.outdir.iterdir()) if p.is_file()}

    def cleanup(self):
        shutil.rmtree(self.ws, ignore_errors=True)


def file_facts(files):
    """Per-variable resolved facts from gen_registry's File objects,
    including DDT members (removed from the variable dictionary by DDT
    construction)."""
    facts = {}
    for freg in files:
        fvars = list(freg.variable_list())
        for ddt in freg.ddts.values():
            fvars.extend(ddt.variable_list())
        for var in fvars:
            facts[(freg.name, var.local_name)] = (
                var.standard_name, var.units, var.var_type, var.kind,
                tuple(var.dimensions), tuple(var.allocation_dimensions),
                var.protected, var.allocatable)
    return facts


def dimension_snapshot(files):
    """The mutable dimension state of every variable (DDT members included)."""
    snap = {}
    for freg in files:
        fvars = list(freg.variable_list())
        for ddt in freg.ddts.values():
            fvars.extend(ddt.variable_list())
        for var in fvars:
            snap[(freg.name, var.local_name)] = (
                tuple(var.dimensions), tuple(var.allocation_dimensions))
    return snap


def expected_meta_facts(reg):
    """Facts the generated .meta must carry, derived from the specs alone:
    {(table_name, local_name): fact tuple}. Private and constituent
    variables are contractually absent."""
    facts = {}
    specs = list(reg.variables) + ([reg.instance] if reg.instance else [])
    for spec in specs:
        if spec.constituent or spec.access == "private":
            continue
        table = reg.ddt_name if spec.ddt_member else _MODULE_NAME
        protected = (spec.access == "protected" or
                     spec.allocatable == "parameter")
        facts[(table, spec.local_name)] = (
            spec.standard_name, spec.units, spec.vtype, spec.kind,
            tuple(spec.dims), protected)
    return facts


def parse_meta_facts(meta_path, known_ddts):
    """Facts parsed back from a generated .meta with the real framework
    parser, in the same shape as expected_meta_facts."""
    run_env = CCPPFrameworkEnv(_LOGGER, host_files='', scheme_files='',
                               suites='')
    facts = {}
    for table in parse_metadata_file(str(meta_path), known_ddts, run_env):
        section = table.sections()[0]
        for var in section.variable_list(loop_vars=False, consts=False):
            dims = tuple(d[len("ccpp_constant_one:"):]
                         if d.startswith("ccpp_constant_one:") else d
                         for d in var.get_dimensions())
            vtype = var.get_prop_value("type")
            kind = var.get_prop_value("kind") or ""
            # The framework parser reports kind == type for DDT variables;
            # the production re-ingest (metadata_file_to_files) drops that
            # kind the same way.
            if kind == vtype:
                kind = ""
            facts[(table.table_name, var.get_prop_value("local_name"))] = (
                var.get_prop_value("standard_name"),
                var.get_prop_value("units"),
                vtype,
                kind,
                dims,
                bool(var.get_prop_value("protected")))
    return facts


def reingest_facts(meta_path):
    """Facts after re-ingesting a generated .meta through the production
    <metadata_file> registry path, in the same shape as
    expected_meta_facts."""
    ws = Path(tempfile.mkdtemp(prefix="cam_reg_reingest_"))
    try:
        srcmods = ws / "SourceMods"
        srcmods.mkdir()
        shutil.copy(str(meta_path), str(srcmods))
        regfile = ws / "registry.xml"
        regfile.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<registry name="cam_registry" version="1.0">\n'
            f'  <metadata_file>{Path(meta_path).name}</metadata_file>\n'
            '</registry>\n')
        _, files, *_ = gen_registry(
            str(regfile), "se", str(ws / "out"), 3, str(srcmods), str(_ROOT),
            logger=_LOGGER, error_on_no_validate=True)
        facts = {}
        for freg in files:
            fvars = list(freg.variable_list())
            for ddt in freg.ddts.values():
                fvars.extend(ddt.variable_list())
            for var in fvars:
                facts[(freg.name, var.local_name)] = (
                    var.standard_name, var.units, var.var_type,
                    var.kind or "", tuple(var.dimensions), var.protected)
        return facts
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def returned_facts(run):
    """Order-insensitive view of gen_registry's returned lists/dicts."""
    return (run.ic_names, frozenset(run.constituents), run.restart,
            frozenset(run.vars_init_value))


def add_host_dim_providers(variables):
    """Append protected integer scalars providing any host dimensions used,
    so every dimension resolves inside the table (production layout)."""
    used = {d for v in variables for dim in v.dims
            for d in dim.split(":") if d in _HOST_DIMS}
    providers = tuple(
        VarSpec(local_name=_HOST_DIMS[dim], standard_name=dim, units="count",
                vtype="integer", access="protected", initial_value="0")
        for dim in sorted(used))
    return providers + tuple(variables)


# ---------------------------------------------------------------------------
# Deterministic fixtures
# ---------------------------------------------------------------------------

# One rich fixture exercising every drawn feature plus the <metadata_file>
# path (which activates the host-dimension use imports in the generated
# allocate routine -- the hash-order-sensitive code path).
_HOST_DIMS_META = """[ccpp-table-properties]
  name = prop_host_dims
  type = module
[ccpp-arg-table]
  name = prop_host_dims
  type = module
[ ncol_ext ]
  standard_name = horizontal_dimension
  units = count
  type = integer
  dimensions = ()
  protected = True
[ pver_ext ]
  standard_name = vertical_layer_dimension
  units = count
  type = integer
  dimensions = ()
  protected = True
"""

FIX_DET = RegSpec(
    variables=(
        VarSpec("pdim0", "param_dim_0", "count", "integer",
                allocatable="parameter", initial_value="4"),
        VarSpec("fixed_arr", "fixed_array_var", "m", "real", "kind_phys",
                dims=("param_dim_0",), allocatable="target"),
        VarSpec("theta_p", "theta_prop", "K", "real", "kind_phys",
                dims=("horizontal_dimension", "vertical_layer_dimension"),
                allocatable="pointer", ic_names=("theta", "pot_temp"),
                restart=True, ddt_member=True),
        VarSpec("wind_p", "wind_prop", "m s-1", "real", "kind_phys",
                dims=("horizontal_dimension",), allocatable="allocatable",
                tstep_init=True),
        VarSpec("count_p", "count_prop", "count", "integer",
                initial_value="3", access="protected"),
        VarSpec("hidden_p", "hidden_prop", "1", "integer", access="private",
                initial_value="1"),
        VarSpec("flag_p", "flag_prop", "1", "logical",
                initial_value=".true."),
        VarSpec("const_p", "const_prop", "kg kg-1", "real", "kind_phys",
                dims=("horizontal_dimension", "vertical_layer_dimension"),
                allocatable="pointer", constituent=True,
                ic_names=("CONSTQ", "cnst_CONSTQ")),
    ),
    ddt_name=_DDT_NAME,
    instance=VarSpec("pddt_inst", "prop_ddt_instance", "1", _DDT_NAME),
    meta_files=(("prop_host_dims.meta", _HOST_DIMS_META),),
)

# The PR #520 instance: a parameter declared after its explicit-shape
# consumer. Pre-#520 code (audit base 27639b49) raises CCPPError on this
# order and succeeds on the reverse; current code must treat both alike.
FIX_PARAM_AFTER_CONSUMER = RegSpec(variables=(
    VarSpec("consumer_arr", "consumer_array", "m", "real", "kind_phys",
            dims=("param_dim_0",), allocatable="target"),
    VarSpec("pdim0", "param_dim_0", "count", "integer",
            allocatable="parameter", initial_value="4"),
))

# Alias corner: pdim_a's local name is pdim_b's standard name, so a second
# resolution pass rewrites consumer dimensions again (admission evidence
# that the idempotence check can fail).
FIX_ALIAS = RegSpec(variables=(
    VarSpec("alias_mid", "param_dim_a", "count", "integer",
            allocatable="parameter", initial_value="4"),
    VarSpec("pdim_b", "alias_mid", "count", "integer",
            allocatable="parameter", initial_value="5"),
    VarSpec("consumer_arr", "consumer_array", "m", "real", "kind_phys",
            dims=("param_dim_a",), allocatable="target"),
))


# ---------------------------------------------------------------------------
# Hypothesis strategy
# ---------------------------------------------------------------------------

if HAVE_HYPOTHESIS:

    _TYPES = [("real", "kind_phys"), ("integer", ""), ("logical", "")]
    _UNITS = ["m", "K", "Pa", "count", "kg kg-1", "1"]
    _INITS = {"real": "0.5_kind_phys", "integer": "3", "logical": ".true."}
    _DEFERRED = ["pointer", "allocatable", "target, allocatable",
                 "allocatable, target"]

    @st.composite
    def registry_specs(draw):
        """Draw a RegSpec whose local-name and standard-name namespaces are
        disjoint (the alias corner is exercised separately)."""
        params = tuple(
            VarSpec(local_name=f"pdim{i}", standard_name=f"param_dim_{i}",
                    units="count", vtype="integer", allocatable="parameter",
                    initial_value=str(draw(st.integers(1, 8))))
            for i in range(draw(st.integers(0, 2))))
        dim_pool = [p.standard_name for p in params] + sorted(_HOST_DIMS)
        variables = []
        for i in range(draw(st.integers(1, 5))):
            vtype, kind = draw(st.sampled_from(_TYPES))
            units = draw(st.sampled_from(_UNITS))
            vclass = draw(st.sampled_from(
                ["scalar", "explicit", "deferred", "constituent"]))
            access = draw(st.sampled_from(
                ["public", "public", "protected", "private"]))
            init = _INITS[vtype] if draw(st.booleans()) else ""
            ic_names = tuple(f"icnm_{i}_{j}"
                             for j in range(draw(st.integers(0, 2))))
            if vclass == "scalar":
                spec = VarSpec(f"ln{i}", f"sn_{i}", units, vtype, kind,
                               access=access, initial_value=init,
                               ic_names=ic_names)
            elif vclass == "explicit":
                dims = tuple(draw(st.lists(st.sampled_from(dim_pool),
                                           min_size=1, max_size=2)))
                spec = VarSpec(f"ln{i}", f"sn_{i}", units, vtype, kind,
                               dims=dims,
                               allocatable=draw(st.sampled_from(
                                   ["", "target"])),
                               access=access, initial_value=init,
                               ic_names=ic_names)
            elif vclass == "deferred":
                dims = tuple(draw(st.lists(st.sampled_from(dim_pool),
                                           min_size=1, max_size=2)))
                spec = VarSpec(f"ln{i}", f"sn_{i}", units, vtype, kind,
                               dims=dims,
                               allocatable=draw(st.sampled_from(_DEFERRED)),
                               access=access, initial_value=init,
                               ic_names=ic_names,
                               restart=draw(st.booleans()),
                               tstep_init=draw(st.booleans()))
            else:
                spec = VarSpec(f"ln{i}", f"sn_{i}", "kg kg-1", "real",
                               "kind_phys",
                               dims=("horizontal_dimension",
                                     "vertical_layer_dimension"),
                               allocatable="pointer", constituent=True,
                               ic_names=ic_names,
                               restart=draw(st.booleans()))
            variables.append(spec)
        ddt_name = ""
        instance = None
        eligible = [idx for idx, v in enumerate(variables)
                    if v.allocatable in _DEFERRED and
                    v.access == "public" and not v.constituent]
        if eligible and draw(st.booleans()):
            ddt_name = _DDT_NAME
            members = draw(st.lists(st.sampled_from(eligible), min_size=1,
                                    max_size=min(2, len(eligible)),
                                    unique=True))
            for idx in members:
                variables[idx] = replace(variables[idx], ddt_member=True)
            if draw(st.booleans()):
                instance = VarSpec("pddt_inst", "prop_ddt_instance", "1",
                                   _DDT_NAME)
        return RegSpec(
            variables=add_host_dim_providers(params + tuple(variables)),
            ddt_name=ddt_name, instance=instance)

    _SETTINGS = settings(max_examples=20, deadline=None, derandomize=True,
                         database=None,
                         suppress_health_check=[HealthCheck.too_slow])


# ---------------------------------------------------------------------------
# Shared check bodies (used by the deterministic and quantified tests)
# ---------------------------------------------------------------------------

class _Checks(unittest.TestCase):
    """Check bodies shared by deterministic and Hypothesis tests."""

    maxDiff = None

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def check_round_trip(self, reg):
        run = GenRun(reg)
        try:
            expected = expected_meta_facts(reg)
            meta_path = run.outdir / f"{_MODULE_NAME}.meta"
            known_ddts = [reg.ddt_name] if reg.ddt_name else []
            self.assertEqual(parse_meta_facts(meta_path, known_ddts),
                             expected, "parsed-back .meta facts differ")
            self.assertEqual(reingest_facts(meta_path), expected,
                             "re-ingested <metadata_file> facts differ")
        finally:
            run.cleanup()

    def check_order_independent(self, reg, perm):
        base = GenRun(reg)
        permuted = GenRun(reg, perm=perm)
        try:
            self.assertEqual(file_facts(base.files),
                             file_facts(permuted.files),
                             "resolved variable facts depend on order")
            base_out = base.outputs()
            perm_out = permuted.outputs()
            self.assertEqual(sorted(base_out), sorted(perm_out))
            for name in base_out:
                self.assertEqual(sorted(base_out[name].splitlines()),
                                 sorted(perm_out[name].splitlines()),
                                 f"{name}: line content depends on order")
            self.assertEqual(returned_facts(base), returned_facts(permuted),
                             "returned registry facts depend on order")
        finally:
            base.cleanup()
            permuted.cleanup()

    def check_resolution_idempotent(self, reg):
        run = GenRun(reg)
        try:
            before = dimension_snapshot(run.files)
            for freg in run.files:
                freg.resolve_dimensions()
            self.assertEqual(before, dimension_snapshot(run.files),
                             "second resolve_dimensions pass changed state")
        finally:
            run.cleanup()


class RegistryGenDeterministic(_Checks):
    """Deterministic contract instances (run without Hypothesis too)."""

    def test_round_trip_fixture(self):
        self.check_round_trip(FIX_DET)

    def test_order_independence_fixture(self):
        nvars = len(FIX_DET.variables)
        self.check_order_independent(FIX_DET,
                                     perm=list(reversed(range(nvars))))

    def test_param_after_consumer_order_insensitive(self):
        """Historical counterexample (fires on pre-#520 code, see module
        docstring): parameter after its explicit-shape consumer."""
        self.check_order_independent(FIX_PARAM_AFTER_CONSUMER, perm=[1, 0])

    def test_resolution_idempotent_fixture(self):
        self.check_resolution_idempotent(FIX_DET)

    def test_alias_corner_detector_fires(self):
        """Admission evidence: on an alias registry the second resolution
        pass changes state, so the idempotence check can fail. If this
        test ever fails (resolution became alias-safe), remove it and add
        alias draws to the quantified idempotence class."""
        run = GenRun(FIX_ALIAS)
        try:
            before = dimension_snapshot(run.files)
            for freg in run.files:
                freg.resolve_dimensions()
            self.assertNotEqual(before, dimension_snapshot(run.files),
                                "resolution unexpectedly idempotent on the "
                                "alias registry")
        finally:
            run.cleanup()

    def test_output_deterministic_across_hash_seeds(self):
        """Generation output must not depend on PYTHONHASHSEED (set/dict
        iteration order). Runs the --generate driver below in fresh
        subprocesses."""
        results = {}
        for seed in ("0", "1", "2", "3"):
            ws = Path(tempfile.mkdtemp(prefix=f"cam_reg_det_{seed}_"))
            try:
                srcmods = ws / "SourceMods"
                srcmods.mkdir()
                for fname, content in FIX_DET.meta_files:
                    (srcmods / fname).write_text(content)
                regfile = ws / "registry.xml"
                regfile.write_text(render_registry(FIX_DET))
                outdir = ws / "out"
                env = dict(os.environ, PYTHONHASHSEED=seed)
                proc = subprocess.run(
                    [sys.executable, str(_THIS_FILE), "--generate",
                     str(regfile), str(outdir), str(srcmods)],
                    env=env, capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, 0,
                                 f"--generate failed: {proc.stderr}")
                results[seed] = {p.name: p.read_bytes()
                                 for p in sorted(outdir.iterdir())
                                 if p.is_file()}
            finally:
                shutil.rmtree(ws, ignore_errors=True)
        baseline = results["0"]
        for seed, outputs in results.items():
            self.assertEqual(outputs, baseline,
                             f"outputs differ between hash seeds 0 and {seed}")


if HAVE_HYPOTHESIS:

    class RegistryGenQuantified(_Checks):
        """The same contracts quantified over drawn registries."""

        @_SETTINGS
        @given(reg=registry_specs())
        def test_round_trip(self, reg):
            """Quantified contract 1 (see module docstring)."""
            self.check_round_trip(reg)

        @_SETTINGS
        @given(reg=registry_specs(), data=st.data())
        def test_order_independence(self, reg, data):
            """Quantified contract 2 (see module docstring)."""
            perm = data.draw(st.permutations(range(len(reg.variables))))
            self.check_order_independent(reg, perm=list(perm))

        @_SETTINGS
        @given(reg=registry_specs())
        def test_resolution_idempotent(self, reg):
            """Quantified contract 3 (see module docstring)."""
            self.check_resolution_idempotent(reg)


def _generate_main(argv):
    """Subprocess driver for the hash-seed determinism test: run
    gen_registry on <registry.xml> into <outdir> and record the returned
    facts (whose order feeds downstream code generation) as JSON."""
    regfile, outdir, srcmods = argv
    retcode, _, ic_names, constituents, restart, vars_init_value = \
        gen_registry(regfile, "se", outdir, 3, srcmods, str(_ROOT),
                     logger=_LOGGER, error_on_no_validate=True)
    if retcode != 0:
        return retcode
    returns = {"ic_names": ic_names, "constituents": constituents,
               "restart": restart, "vars_init_value": vars_init_value}
    with open(os.path.join(outdir, "returns.json"), "w",
              encoding="utf-8") as jfile:
        json.dump(returns, jfile, indent=1)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--generate":
        logging.disable(logging.CRITICAL)
        sys.exit(_generate_main(sys.argv[2:]))
    unittest.main(verbosity=2)

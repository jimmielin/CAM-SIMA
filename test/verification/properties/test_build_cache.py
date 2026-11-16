#!/usr/bin/env python3
"""Build-cache property suite: incremental generation must equal clean
generation.

Guarantee statement
  Property: after any supported sequence of {edit registry, successful build,
    failed build (failure injected after the registry stage but before the
    cache write, as when a later stage or the compile fails), revert}, a
    successful build leaves generated registry artifacts byte-identical to a
    clean generation from the current inputs -- and the cache-hit/miss
    decision (do_gen_registry) is consistent with that.
  Assumptions: the harness mirrors cam_config.generate_cam_src's protocol for
    the registry stage: one BuildCacheCAM loaded from bldroot, the real
    cam_autogen.generate_registry + gen_registry on the real code paths, and
    one cache write at the very end of a successful pass. Surrogate cache
    updates stand in for the CCPP/init/restart stages' update_* calls (same
    constant values each pass) because BuildCacheCAM.write() requires them;
    those stages are not driven.
  Checked domain: deterministic regression sequences below, plus (when
    Hypothesis is installed) derandomized stateful sequences over the registry
    variants and build/noop-build operations. Registry fixtures derive from
    test/unit/python/sample_files/reg_good_simple.xml.
  Connection to production code: executes the real generate_registry,
    gen_registry and BuildCacheCAM; the only test double is the injected
    failure and the surrogate updates named above.
  Blind spots: the CCPP stage's cache behaviour (including copied utility
    sources missing from the key, F-DRIVER-4) is not driven -- it needs capgen
    and atmospheric_physics; SourceMods-vs-src/data shadowing uses only the
    SourceMods slot; the Hypothesis machine currently excludes the
    failure-injection operation so the suite is green while F-DRIVER-3 is
    open -- enable it in the machine when FG-8 lands and the expectedFailure
    below flips.

Admission evidence: test_revert_after_failed_build encodes the F-DRIVER-3
sequence (Nov 2026 audit, fix group FG-8) and fails against today's code; it
is marked expectedFailure so an unittest run is green until the fix lands,
at which point the unexpected success forces removing the marker (the test
ratchet, mirroring baseline.json's stale-entry rule).

Run: python3 test/verification/properties/test_build_cache.py
"""

import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "cime_config"))

# cam_autogen imports the ccpp_framework scripts at module import time, so
# this suite needs the ccpp_framework submodule populated (git-fleximod).
from cam_autogen import generate_registry          # noqa: E402
from cam_build_cache import BuildCacheCAM          # noqa: E402

try:
    from hypothesis import settings, HealthCheck
    from hypothesis import strategies as st
    from hypothesis.stateful import (RuleBasedStateMachine, rule, invariant,
                                     initialize)
    HAVE_HYPOTHESIS = True
except ImportError:
    HAVE_HYPOTHESIS = False

_BASE = (_ROOT / "test" / "unit" / "python" / "sample_files" /
         "reg_good_simple.xml").read_text()

_EXTRA_VAR = """    <variable local_name="extra_scalar_{n}"
              standard_name="verification_extra_scalar_{n}"
              units="K" type="real" kind="kind_phys" access="protected">
      <long_name>Extra scalar {n} for cache property tests</long_name>
      <initial_value>0.0_kind_phys</initial_value>
    </variable>
  </file>"""


def make_variant(n_extra):
    """Registry content with <n_extra> additional scalar variables."""
    content = _BASE
    for i in range(n_extra):
        content = content.replace("</file>", _EXTRA_VAR.format(n=i))
    return content


# Small, schema-valid, mutually distinct registry inputs.
VARIANTS = [make_variant(n) for n in range(3)]


class InjectedFailure(Exception):
    """Stands in for a post-registry generation stage or build failure."""


class Workspace:
    """One case directory: SourceMods registry override, bldroot, cache."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cam_cache_prop_"))
        self.srcmods = self.dir / "SourceMods"
        self.bldroot = self.dir / "bld"
        self.srcmods.mkdir()
        self.bldroot.mkdir()

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def set_registry(self, content):
        (self.srcmods / "registry.xml").write_text(content)

    def build(self, fail_before_cache_write=False):
        """One generate pass with production's protocol: load cache, run the
        registry stage, write the cache last. Returns do_gen_registry."""
        cache = BuildCacheCAM(str(self.bldroot / "cam_build_cache.xml"))
        retvals = generate_registry(
            [str(self.srcmods), str(_ROOT / "src" / "data")], cache,
            str(_ROOT), str(self.bldroot), str(self.srcmods), "fv", 2)
        if fail_before_cache_write:
            raise InjectedFailure()
        # Surrogates for the update_* calls the CCPP/init/restart stages
        # make before the single end-of-pass write (constant inputs).
        cache.update_ccpp([], [], [], {}, [], [],
                          str(_ROOT / "cime_config" / "create_readnl_files.py"),
                          "UNSET", ["kind_phys = REAL64"])
        cache.update_init_gen(str(_ROOT / "src" / "data" / "write_init_files.py"))
        cache.update_restart_gen(
            str(_ROOT / "src" / "data" / "write_restart_physics.py"))
        cache.write()
        return retvals[1]  # do_gen_registry

    def generated(self):
        """Generated registry artifacts as {relative path: bytes}."""
        gen_dir = self.bldroot / "cam_registry"
        return {str(p.relative_to(self.bldroot)): p.read_bytes()
                for p in sorted(gen_dir.rglob("*")) if p.is_file()}


_ORACLE_CACHE = {}


def clean_oracle(content):
    """Artifacts of a clean generation from <content> in a fresh workspace."""
    if content not in _ORACLE_CACHE:
        ws = Workspace()
        try:
            ws.set_registry(content)
            ws.build()
            _ORACLE_CACHE[content] = ws.generated()
        finally:
            ws.cleanup()
    return _ORACLE_CACHE[content]


class BuildCacheDeterministic(unittest.TestCase):
    """Deterministic contract and regression sequences."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.ws = Workspace()
        self.addCleanup(self.ws.cleanup)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_clean_generation_is_deterministic(self):
        """Two clean generations of the same input agree byte-for-byte."""
        self.ws.set_registry(VARIANTS[0])
        self.ws.build()
        self.assertEqual(self.ws.generated(), clean_oracle(VARIANTS[0]))

    def test_cache_hit_skips_regeneration_and_preserves_outputs(self):
        self.ws.set_registry(VARIANTS[0])
        self.assertTrue(self.ws.build())
        self.assertFalse(self.ws.build(), "unchanged inputs must be a cache hit")
        self.assertEqual(self.ws.generated(), clean_oracle(VARIANTS[0]))

    def test_edit_then_rebuild_regenerates(self):
        self.ws.set_registry(VARIANTS[0])
        self.ws.build()
        self.ws.set_registry(VARIANTS[1])
        self.assertTrue(self.ws.build(), "edited inputs must be a cache miss")
        self.assertEqual(self.ws.generated(), clean_oracle(VARIANTS[1]))

    def test_failed_build_then_rebuild_same_inputs_recovers(self):
        """A failure before the cache write must not poison a retry with the
        same inputs: the stale cache forces regeneration."""
        self.ws.set_registry(VARIANTS[0])
        self.ws.build()
        self.ws.set_registry(VARIANTS[1])
        with self.assertRaises(InjectedFailure):
            self.ws.build(fail_before_cache_write=True)
        self.assertTrue(self.ws.build())
        self.assertEqual(self.ws.generated(), clean_oracle(VARIANTS[1]))

    @unittest.expectedFailure
    def test_revert_after_failed_build(self):
        """F-DRIVER-3 (FG-8): edit, fail after regeneration, revert. The old
        cache matches the reverted inputs, so today nothing regenerates and
        the abandoned artifacts from the edited inputs are reused. Contract:
        outputs equal a clean generation from the reverted inputs.
        expectedFailure until FG-8 lands; then remove the marker and enable
        the failure operation in the stateful machine."""
        self.ws.set_registry(VARIANTS[0])
        self.ws.build()
        self.ws.set_registry(VARIANTS[1])
        with self.assertRaises(InjectedFailure):
            self.ws.build(fail_before_cache_write=True)
        self.ws.set_registry(VARIANTS[0])   # revert
        self.ws.build()
        self.assertEqual(self.ws.generated(), clean_oracle(VARIANTS[0]))


if HAVE_HYPOTHESIS:

    class CacheMachine(RuleBasedStateMachine):
        """Random edit/build sequences; after every successful build the
        artifacts must equal the clean oracle of the current inputs.
        Failure injection is deliberately absent until FG-8 (see module
        docstring)."""

        def __init__(self):
            super().__init__()
            logging.disable(logging.CRITICAL)
            self.ws = Workspace()
            self.current = None
            self.built = False

        @initialize(variant=st.integers(0, len(VARIANTS) - 1))
        def start(self, variant):
            self.current = VARIANTS[variant]
            self.ws.set_registry(self.current)

        @rule(variant=st.integers(0, len(VARIANTS) - 1))
        def edit(self, variant):
            self.current = VARIANTS[variant]
            self.ws.set_registry(self.current)
            self.built = False

        @rule()
        def build(self):
            self.ws.build()
            self.built = True

        @invariant()
        def outputs_match_clean_generation(self):
            if self.built:
                assert self.ws.generated() == clean_oracle(self.current)

        def teardown(self):
            self.ws.cleanup()
            logging.disable(logging.NOTSET)

    CacheMachine.TestCase.settings = settings(
        max_examples=25, stateful_step_count=6, deadline=None,
        derandomize=True,
        suppress_health_check=[HealthCheck.too_slow])

    class BuildCacheStateful(CacheMachine.TestCase):
        """unittest wrapper so discovery picks the state machine up."""


if __name__ == "__main__":
    unittest.main(verbosity=2)

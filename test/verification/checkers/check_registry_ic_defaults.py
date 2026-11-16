#!/usr/bin/env python3
"""Registry IC-backed variables must have a neutral fallback initial value.

Guarantee statement
  Property: every registry <variable> carrying <ic_file_input_names> (that is,
    a variable meant to be filled from an IC/snapshot file) has every
    <initial_value> neutral: numerically zero, .false., or a nan/unset
    sentinel. A non-neutral fallback is the P2 anti-pattern -- a default
    indistinguishable from data -- and is a violation unless it is justified
    in the baseline (which is today's stand-in for an explicit neutrality
    declaration in the registry schema).
  Assumptions: src/data/registry.xml is the complete registry; the generated
    code applies <initial_value> verbatim as the pre-read value.
  Checked domain: every <variable> element in registry.xml; all of its
    <initial_value> elements including dyn="..." variants.
  Connection to production code: checks the registry source of truth directly;
    it does not trace which schemes read the variable on step 0 (that is
    suite-trace read-before-write's job, from the other side).
  Blind spots: zero or .false. is scientifically wrong for some quantities --
    neutrality here means "cannot masquerade as data", not "safe"; a variable
    with ic names but no <initial_value> is not flagged (reading it before the
    IC fills it is the UNSET class, suite-trace territory); IC-name case
    consistency against the CAM snapshot vocabulary is not checked (no
    vocabulary fixture exists yet -- the tpert/CLD wrong-case defect class is
    only caught here because the same entries also carry non-neutral values).

Admission evidence: fires on F-AP_MOIST-1 (tpert 273.15 K) and F-AP_MOIST-5
(cldfrc 0.7) at CAM-SIMA 27639b49 and at 8d34b02c; self-test carries a
synthetic mutation.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlib

CHECKER = "check_registry_ic_defaults"

_KIND_SUFFIX = re.compile(r"_[a-z]\w*$", re.IGNORECASE)


def classify_initial_value(text):
    """Return 'neutral', 'non-neutral', or 'unknown' for an initial_value."""
    value = text.strip()
    low = value.lower()
    if "nan" in low or "unset" in low:
        return "neutral"
    if low in (".false.",):
        return "neutral"
    if low in (".true.",):
        return "non-neutral"
    numeric = _KIND_SUFFIX.sub("", low)
    # Fortran literals: 0, 0., 0.0, 1.e5, 10e5, 2., .5
    try:
        return "neutral" if float(numeric) == 0.0 else "non-neutral"
    except ValueError:
        return "unknown"


def check_registry(registry_path):
    findings, unknowns = [], []
    n_checked = 0
    root = ET.parse(registry_path).getroot()
    rel = registry_path.name
    for var in root.iter("variable"):
        ic = var.find("ic_file_input_names")
        if ic is None or not (ic.text or "").strip():
            continue
        name = var.get("local_name", "?")
        ivs = var.findall("initial_value")
        if not ivs:
            continue  # no declared fallback: UNSET class, out of scope here
        n_checked += 1
        for iv in ivs:
            text = (iv.text or "").strip()
            dyn = iv.get("dyn")
            tag = f"{name}" + (f"[dyn={dyn}]" if dyn else "")
            verdict = classify_initial_value(text)
            if verdict == "non-neutral":
                findings.append(vlib.Finding(
                    key=f"registry:{tag}",
                    file=rel, line=None,
                    message=(f"IC-backed variable '{tag}' has non-neutral "
                             f"fallback initial_value '{text}' "
                             f"(ic names: {ic.text.strip()})")))
            elif verdict == "unknown":
                unknowns.append((rel, None,
                                 f"'{tag}': cannot parse initial_value '{text}'"))
    return findings, unknowns, n_checked


SELF_TEST_XML = """<?xml version="1.0"?>
<registry>
  <variable local_name="bad_default" type="real" kind="kind_phys">
    <initial_value>273.15_kind_phys</initial_value>
    <ic_file_input_names>bad_default</ic_file_input_names>
  </variable>
  <variable local_name="good_zero" type="real" kind="kind_phys">
    <initial_value>0.0_kind_phys</initial_value>
    <ic_file_input_names>good_zero</ic_file_input_names>
  </variable>
  <variable local_name="good_sentinel" type="real" kind="kind_phys">
    <initial_value>unset_real</initial_value>
    <ic_file_input_names>good_sentinel</ic_file_input_names>
  </variable>
  <variable local_name="no_ic_ok" type="real" kind="kind_phys">
    <initial_value>42.0_kind_phys</initial_value>
  </variable>
  <variable local_name="dyn_bad" type="logical">
    <initial_value>.false.</initial_value>
    <initial_value dyn="SE">.true.</initial_value>
    <ic_file_input_names>dyn_bad</ic_file_input_names>
  </variable>
  <variable local_name="odd_expr" type="real" kind="kind_phys">
    <initial_value>some_parameter</initial_value>
    <ic_file_input_names>odd_expr</ic_file_input_names>
  </variable>
</registry>
"""


def self_test():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(SELF_TEST_XML)
        path = Path(f.name)
    try:
        findings, unknowns, n_checked = check_registry(path)
        keys = {f.key for f in findings}
        assert keys == {"registry:bad_default", "registry:dyn_bad[dyn=SE]"}, keys
        assert len(unknowns) == 1 and "odd_expr" in unknowns[0][2], unknowns
        assert n_checked == 5, n_checked
    finally:
        path.unlink()
    print(f"{CHECKER}: self-test ok")
    return 0


def main():
    args = vlib.make_parser(__doc__.splitlines()[0]).parse_args()
    if args.self_test:
        return self_test()
    registry = args.repo / "src" / "data" / "registry.xml"
    if not registry.is_file():
        print(f"{CHECKER}: registry not found at {registry}", file=sys.stderr)
        return 2
    findings, unknowns, n_checked = check_registry(registry)
    return vlib.report(CHECKER, args, findings, unknowns, n_checked)


if __name__ == "__main__":
    sys.exit(main())

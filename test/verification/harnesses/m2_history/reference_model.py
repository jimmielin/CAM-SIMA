"""Executable reference model for the M2 history-lifecycle harness.

This is the FG-3 (fixed) protocol of test/verification/models/m2_history/
M2HistoryLifecycle.tla made concrete: split flags recomputed from the
committed accumulate types after the 1*nsteps override, zero-sample
intervals written as _FillValue, and produced file names never reused.
Given a scenario op script it predicts the observable events the recording
stubs emit - file opens/closes by split kind, field variable definitions,
and per-frame field writes classified as data (with the expected
accumulated value) or fill.

The model deliberately does not re-implement filename interpolation: names
are treated as opaque identities whose uniqueness the comparator enforces
over the real driver's createfile events.
"""

FILLVALUE = 1.0e36

# Accumulate normalization mirrored from hist_buffer semantics: 'lst'
# tracks the last sample, the others reduce over the interval's samples.
ACCUMULATORS = {
    "lst": lambda samples: samples[-1],
    "avg": lambda samples: sum(samples) / len(samples),
    "min": min,
    "max": max,
}


def parse_ops(text):
    """Parse a scenario op script into a list of (op, args) tuples."""
    ops = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        ops.append((parts[0], parts[1:]))
    return ops


class Field(object):
    def __init__(self, name, list_kind, xyfill):
        self.name = name
        self.list_kind = list_kind  # inst | avg | min | max | var
        self.xyfill = xyfill
        # inst-list fields are 'lst' from configure (cam_hist_file.F90:900)
        self.acc = "lst" if list_kind == "inst" else list_kind
        self.samples = []

    @property
    def split(self):
        # 'lst' routes to the instantaneous file, all else accumulated
        return "i" if self.acc == "lst" else "a"


class ExpectedEvents(object):
    """Accumulates the predicted observable events for one scenario."""

    def __init__(self):
        # Each open: sorted list of split kinds created, e.g. ['a', 'i']
        self.opens = []
        # defvar expectations per open index: set of (split, field name)
        self.defvars = []
        # writes: list of (field name, split, generation, frame, kind, value)
        # where generation is the open-round index (frames restart per
        # file) and kind is 'data' (value = expected number) or 'fill'
        self.writes = []
        self.closes = []  # sorted split kinds per close


class ReferenceModel(object):
    def __init__(self):
        self.fields = []
        self.max_frames = None
        self.one_step = False
        self.committed = False
        self.num_samples = 0
        self.files_open = False
        self.expected = ExpectedEvents()

    def field(self, name):
        for fld in self.fields:
            if fld.name == name:
                return fld
        raise KeyError(name)

    @property
    def active_splits(self):
        # FG-3: derived from committed accumulate types (FixRecomputeSplit)
        return sorted({fld.split for fld in self.fields})

    def run(self, ops):
        for op, args in ops:
            if op == "volume":
                self.max_frames = int(args[1])
                freq = args[2]
                mult, _, unit = freq.partition("*")
                self.one_step = (mult == "1" and
                                 unit in ("nsteps", "nstep", "steps", "step"))
            elif op == "field":
                self.fields.append(Field(args[0], args[1], args[2] == "T"))
            elif op == "setup":
                # The override commit (cam_hist_file.F90:1066-1070)
                if self.one_step:
                    for fld in self.fields:
                        fld.acc = "lst"
                self.committed = True
            elif op == "sample":
                self.field(args[0]).samples.append(float(args[1]))
            elif op == "write":
                self.do_write()
            elif op in ("dtime", "nstep"):
                pass
            else:
                raise ValueError("unknown op " + op)
        return self.expected

    def do_write(self):
        if self.num_samples % self.max_frames == 0:
            splits = self.active_splits
            self.expected.opens.append(splits)
            self.expected.defvars.append(
                {(fld.split, fld.name) for fld in self.fields})
            self.files_open = True
        frame = (self.num_samples % self.max_frames) + 1
        generation = len(self.expected.opens) - 1
        for fld in self.fields:
            if fld.samples:
                value = ACCUMULATORS[fld.acc](fld.samples)
                self.expected.writes.append(
                    (fld.name, fld.split, generation, frame, "data", value))
            else:
                # FG-3 FixFillUnsampled: zero-sample intervals write fill
                self.expected.writes.append(
                    (fld.name, fld.split, generation, frame, "fill",
                     FILLVALUE))
            fld.samples = []
        self.num_samples += 1
        if self.num_samples % self.max_frames == 0:
            self.expected.closes.append(self.active_splits)
            self.files_open = False


def predict(text):
    return ReferenceModel().run(parse_ops(text))

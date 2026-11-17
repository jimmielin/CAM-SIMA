#!/usr/bin/env python3
"""Executable reference model (oracle) of the tracer_data time-bracketing
machine: src/utils/tracer_data.F90 (SM-INPUTS-1/2/3/4 of the Nov 2026
state-machine audit), rebuilt from the audit's line-by-line spec
(state_machine_audit_nov26/sections/INPUTS.md).

This module is the model library; run_m4_oracle.py drives the scenario
table and asserts the declared verdicts. Every modeled routine cites the
Fortran lines it transcribes (at CAM-SIMA 146ccde1; the bracketing core is
unchanged since audit base 27639b49).

Modeling conventions
  - PIO is replaced by DataFile objects holding the date/datesec arrays a
    real file would carry; "reading" record i is recorded, not performed.
  - Fortran undefined values (locals read before assignment, e.g. find_times
    `n` when the cyclical bracket is skipped) are the UNDEF sentinel:
    arithmetic propagates it, ordering comparisons on it return False (one
    arbitrary-but-fixed resolution of genuinely undefined behavior; scenario
    verdicts never depend on a choice downstream of UNDEF).
  - endrun is the Endrun exception with a stable code identifier; message
    prose is never asserted.
  - The read_next_trcdata search loop has no iteration bound in the real
    code (F-INPUTS-3a); the model raises Livelock when one find_times /
    check_files round leaves the whole search state unchanged, which is the
    exact non-termination condition of the real loop (its state space is
    finite and the loop body is deterministic in that state).

Fix flags (all default False = today's code; each names its fix group):
  - fix_calendar_mapping (FG calendar-date-mapping, F-INPUTS-1): repair
    Feb 29 for NO_LEAP or a non-leap target year (CAM semantics), not only
    for NO_LEAP.
  - fix_search_contract (FG trc-search-contract, F-INPUTS-3): find_times
    resets times_found on entry, aborts on a cycle window of fewer than two
    records, and the search loop aborts when a round makes no progress.
  - fix_file_window (FG trc-file-window, F-INPUTS-2): after a successful
    search, normalize the window so the earlier bracketing record lives in
    the current file (advance_file + re-search) before the fill path runs.
  - fix_unset_sentinel (FG trc-file-window, F-INPUTS-4): trcdata_init
    normalizes the 'UNSET' filelist sentinel to "no filelist".
"""

import datetime

# Seconds per day (physconst cday), used by the FIXED weight rounding
# (tracer_data.F90:1846).
CDAY = 86400.0

# unset_real = +huge (runtime_obj.F90:12); the sentinel stored in
# datatimem/p is -unset_real (tracer_data.F90:73-74, 210-211).
UNSET_REAL = 1.0e308


class Endrun(Exception):
    """Model endrun; <code> is the stable identifier scenarios assert."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Livelock(Exception):
    """read_next_trcdata search loop made no progress (F-INPUTS-3a)."""


class _Undef:
    """Fortran undefined value: propagates through arithmetic; ordering
    comparisons return False (arbitrary-but-fixed, see module docstring)."""

    def __repr__(self):
        return "UNDEFINED"

    def _op(self, _other):
        return self

    __add__ = __radd__ = __sub__ = __rsub__ = _op
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _op

    def _cmp(self, _other):
        return False

    __lt__ = __le__ = __gt__ = __ge__ = _cmp


UNDEF = _Undef()


def is_undef(value):
    """True if <value> carries the undefined sentinel."""
    return value is UNDEF


# ---------------------------------------------------------------------------
# Calendar: time_manager set_time_float_from_date / set_date_from_time_float
# ---------------------------------------------------------------------------

_MONTH_DAYS_NOLEAP = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_CUM_NOLEAP = [0]
for _d in _MONTH_DAYS_NOLEAP[:-1]:
    _CUM_NOLEAP.append(_CUM_NOLEAP[-1] + _d)


def _is_gregorian_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


class Calendar:
    """Date <-> time-float mapping with the time_manager Feb 29 semantics.

    set_time_float_from_date (time_manager.F90:256-293): the Feb 29 repair
    is guarded by `timemgr_is_caltype(shr_cal_noleap)` only (line 279), so
    under GREGORIAN an invalid (non-leap-year) Feb 29 reaches ESMF_TimeSet
    and endruns through chkrc (lines 282-283, 1244-1249) -- F-INPUTS-1.
    With fix_calendar_mapping the repair follows CAM
    (CAM:src/utils/time_manager.F90:263-264): noleap OR non-leap year."""

    def __init__(self, name="NO_LEAP", fix_calendar_mapping=False):
        assert name in ("NO_LEAP", "GREGORIAN")
        self.name = name
        self.fix_calendar_mapping = fix_calendar_mapping

    def time_float(self, year, month, day, sec):
        """Days since the calendar origin (set_time_float_from_date)."""
        if is_undef(year) or is_undef(month) or is_undef(day):
            return UNDEF
        useday = day
        if month == 2 and day == 29:
            if self.name == "NO_LEAP":
                useday = 28                       # time_manager.F90:279-281
            elif self.fix_calendar_mapping and not _is_gregorian_leap(year):
                useday = 28                       # CAM-style repair (fix)
        if self.name == "NO_LEAP":
            return ((year - 1) * 365.0 + _CUM_NOLEAP[month - 1]
                    + (useday - 1) + sec / 86400.0)
        try:
            date = datetime.date(year, month, useday)
        except ValueError as err:
            # ESMF_TimeSet failure -> chkrc -> endrun (time_manager.F90:283,
            # 1244-1249).
            raise Endrun("CHKRC", f"ESMF_TimeSet {year}-{month}-{useday}") \
                from err
        return float((date - datetime.date(1, 1, 1)).days) + sec / 86400.0

    def date_from_float(self, tfloat):
        """Inverse mapping (set_date_from_time_float)."""
        if is_undef(tfloat):
            return UNDEF, UNDEF, UNDEF, UNDEF
        days = int(tfloat)
        sec = int(round((tfloat - days) * 86400.0))
        if self.name == "NO_LEAP":
            year = days // 365 + 1
            doy = days % 365
            month = 1
            while month < 12 and doy >= _CUM_NOLEAP[month]:
                month += 1
            day = doy - _CUM_NOLEAP[month - 1] + 1
            return year, month, day, sec
        date = datetime.date(1, 1, 1) + datetime.timedelta(days=days)
        return date.year, date.month, date.day, sec


class Clock:
    """Model time clock (get_curr_date / get_step_size)."""

    def __init__(self, year, month, day, sec, dtime=1800):
        self.date = (year, month, day, sec)
        self.dtime = dtime

    def get_curr_date(self):
        return self.date

    def set_date(self, year, month, day, sec=0):
        self.date = (year, month, day, sec)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class DataFile:
    """One dataset file: the date/datesec coordinate a real file carries."""

    _next_fh = [100]

    def __init__(self, name, dates, datesecs=None):
        self.name = name
        self.dates = list(dates)                 # yyyymmdd integers
        self.datesecs = list(datesecs or [0] * len(dates))
        self.fh = DataFile._next_fh[0]           # file_desc_t%fh identity
        DataFile._next_fh[0] += 1

    def times(self, cal):
        """open_trc_datafile's time coordinate (tracer_data.F90:2111-2115)."""
        out = []
        for date, dsec in zip(self.dates, self.datesecs):
            year, month, day = date // 10000, date % 10000 // 100, date % 100
            out.append(cal.time_float(year, month, day, dsec))
        return out


class Filesystem:
    """Named DataFiles plus filelist files (text lists of names)."""

    def __init__(self, files=(), filelists=None):
        self.files = {f.name: f for f in files}
        self.filelists = dict(filelists or {})


class TrFile:
    """The trfile state (tracer_data.F90:61-125), bracketing subset."""

    def __init__(self):
        self.pathname = ""
        self.curr_filename = ""
        self.next_filename = ""
        self.filenames_list = ""
        self.curr_file = None                    # DataFile (curr_fileid)
        self.next_file = None                    # DataFile (next_fileid)
        self.curr_data_times = None
        self.next_data_times = None              # None == .not. allocated
        self.datatimem = -UNSET_REAL             # tracer_data.F90:210-211
        self.datatimep = -UNSET_REAL
        self.datatimes = [UNDEF] * 4             # 1-based slots 1..4 -> 0..3
        self.interp_recs = 0
        self.offset_time = 0.0
        self.cyc_ndx_beg = -1
        self.cyc_ndx_end = -1
        self.cyc_yr = 0
        self.one_yr = 0.0
        self.curr_mod_time = UNDEF
        self.next_mod_time = UNDEF
        self.fixed = False
        self.cyclical = False
        self.cyclical_list = False
        self.fill_in_months = False
        self.stepTime = False                    # never set in SIMA
        self.initialized = False


class StepResult:
    """Observables of one advance_trcdata call."""

    def __init__(self):
        self.read_performed = False
        self.reads = []                          # [(file name, recno)] read
        self.fact1 = None
        self.fact2 = None
        self.blended = False                     # interp_recs 4 -> 2 blend
        self.blend_facts = []                    # [(fact1, fact2)] per pair

    def __repr__(self):
        return (f"StepResult(read={self.read_performed}, reads={self.reads}, "
                f"fact1={self.fact1}, blended={self.blended})")


# ---------------------------------------------------------------------------
# The machine
# ---------------------------------------------------------------------------

class TracerDataModel:
    """One trfile object driven the way advance_trcdata drives it."""

    def __init__(self, fs, clock, cal, fix_search_contract=False,
                 fix_file_window=False, fix_unset_sentinel=False):
        self.fs = fs
        self.clock = clock
        self.cal = cal
        self.fix_search_contract = fix_search_contract
        self.fix_file_window = fix_file_window
        self.fix_unset_sentinel = fix_unset_sentinel
        self.file = TrFile()
        self.log = []                            # masterproc-style trace

    # -- trcdata_init (tracer_data.F90:148-470, bracketing-relevant part) --

    def trcdata_init(self, filename, filelist="", datapath="",
                     data_type="SERIAL", cycle_yr=0, fixed_ymd=0,
                     fixed_tod=0):
        file = self.file
        file.datatimep = -UNSET_REAL             # 210-211
        file.datatimem = -UNSET_REAL
        file.pathname = datapath                 # 218-219
        file.filenames_list = filelist
        if self.fix_unset_sentinel and filelist in ("UNSET", "unset"):
            file.filenames_list = ""             # F-INPUTS-4 normalization
        if data_type == "FIXED":                 # 225-242
            file.fixed = True
        elif data_type == "INTERP_MISSING_MONTHS":
            file.fill_in_months = True
        elif data_type == "CYCLICAL":
            file.cyclical = True
            file.cyc_yr = cycle_yr
        elif data_type == "SERIAL":
            pass
        else:
            raise Endrun("INVALID_DATA_TYPE", data_type)
        # initial run: 259-275
        file.curr_filename = filename
        self.get_model_time()
        if file.fixed:
            str_yr = fixed_ymd // 10000
            str_mon = (fixed_ymd - str_yr * 10000) // 100
            str_day = fixed_ymd - str_yr * 10000 - str_mon * 100
            start_time = self.cal.time_float(str_yr, str_mon, str_day,
                                             fixed_tod)
            file.offset_time = start_time - file.curr_mod_time
        else:
            file.offset_time = 0.0
        # one_yr: 277-287
        file.one_yr = (self.cal.time_float(2, 1, 1, 0)
                       - self.cal.time_float(1, 1, 1, 0))
        if file.cyclical:
            file.cyc_ndx_beg = -1
            file.cyc_ndx_end = -1
            if file.cyc_yr != 0:
                file.one_yr = (self.cal.time_float(file.cyc_yr + 1, 1, 1, 0)
                               - self.cal.time_float(file.cyc_yr, 1, 1, 0))
            # open with cycle indices: 290-292, 2111-2127, 2140-2145
            self._open_curr(filename, with_cycle_indices=True)
        else:
            # open + offset: 297-298
            self._open_curr(filename, with_cycle_indices=False)
            file.curr_data_times = [t - file.offset_time
                                    for t in file.curr_data_times]

    def _open_curr(self, fname, with_cycle_indices):
        file = self.file
        file.curr_file = self._open(fname)
        file.curr_data_times = file.curr_file.times(self.cal)
        if with_cycle_indices:
            # open_trc_datafile cyc scan (2111-2127) + guard (2140-2145)
            need_first = True
            for i, date in enumerate(file.curr_file.dates, start=1):
                if date // 10000 == file.cyc_yr:
                    if need_first:
                        file.cyc_ndx_beg = i
                        need_first = False
                    file.cyc_ndx_end = i
            if file.cyc_ndx_beg < 0:
                raise Endrun("CYC_YEAR_NOT_FOUND", str(file.cyc_yr))

    def _open(self, fname):
        """open_trc_datafile file lookup (cam_get_file + openfile)."""
        if fname not in self.fs.files:
            raise Endrun("OPEN_FAIL", fname)
        return self.fs.files[fname]

    # -- get_model_time (882-897) --

    def get_model_time(self):
        file = self.file
        year, mon, day, ncsec = self.clock.get_curr_date()
        if file.cyclical or file.cyclical_list:
            year = file.cyc_yr                   # 893
        file.curr_mod_time = self.cal.time_float(year, mon, day, ncsec)  # 894
        file.next_mod_time = (file.curr_mod_time
                              + self.clock.dtime / 86400.0)              # 895

    # -- advance_trcdata (775-842, data movement elided) --

    def advance_trcdata(self):
        file = self.file
        result = StepResult()
        if not (file.fixed and file.initialized):    # 800
            self.get_model_time()                    # 802
            data_time = file.datatimep               # 804
            if file.cyclical or file.cyclical_list:  # 806-811 wrap guard
                if (file.datatimep < file.datatimem and
                        file.curr_mod_time > file.datatimem):
                    data_time = data_time + file.one_yr
            if file.curr_mod_time >= data_time:      # 815
                self.read_next_trcdata(result)       # 817
                result.read_performed = True
            file.initialized = True                  # 822
        self._interpolate_weights(result)            # 828-838 -> 1796-1849
        return result

    # -- findplb (2741-2764) --

    @staticmethod
    def findplb(x, xval):
        """1-based 'previous lower bound' index into strictly increasing x."""
        nx = len(x)
        if xval < x[0] or xval >= x[nx - 1]:
            return nx
        for i in range(2, nx + 1):
            if xval < x[i - 1]:
                return i - 1
        return UNDEF  # unreachable for strictly increasing x

    # -- find_times (1126-1238) --

    def find_times(self, time, times_found):
        """Returns (itms, fids, datatimem, datatimep, times_found).
        times_found is intent(inout): never reset here (F-INPUTS-3) unless
        fix_search_contract. itms/fids are UNDEF when computed from the
        undefined locals of a skipped cyclical bracket."""
        file = self.file
        if self.fix_search_contract:
            times_found = False
        n = UNDEF                                   # locals, undefined
        np1 = UNDEF
        datatimem = UNDEF                           # intent(out), undefined
        datatimep = UNDEF
        curr_tsize = len(file.curr_data_times)      # 1150
        next_tsize = len(file.next_data_times) if file.next_data_times \
            else 0                                  # 1151-1152
        all_data_times = list(file.curr_data_times)  # 1160-1161
        if next_tsize > 0:
            all_data_times += list(file.next_data_times)
        all_tsize = curr_tsize + next_tsize

        if not file.cyclical:                       # 1163-1182
            if all(t > time for t in all_data_times):
                raise Endrun("ALL_TIMES_AFTER", file.curr_filename)  # 1168
            for n_try in range(1, all_tsize):       # 1172-1182
                datatimem = all_data_times[n_try - 1]
                datatimep = all_data_times[n_try]
                if datatimem <= time < datatimep:   # 1178
                    times_found = True
                    n, np1 = n_try, n_try + 1
                    break
        else:                                       # 1184-1203
            cyc_tsize = file.cyc_ndx_end - file.cyc_ndx_beg + 1  # 1186
            if cyc_tsize > 1:                       # 1188
                window = all_data_times[file.cyc_ndx_beg - 1:file.cyc_ndx_end]
                n = self.findplb(window, time)      # 1190
                np1 = 1 if n == cyc_tsize else n + 1  # 1192-1196
                datatimem = all_data_times[n + file.cyc_ndx_beg - 2]  # 1198
                datatimep = all_data_times[np1 + file.cyc_ndx_beg - 2]
                times_found = True                  # 1200
            elif self.fix_search_contract:
                raise Endrun("CYC_WINDOW_LT2", f"cyc_tsize={cyc_tsize}")

        if not times_found:                         # 1205-1213
            self.log.append("find_times: failed to bracket "
                            f"time={time} in {file.curr_filename}")
            return None, None, datatimem, datatimep, times_found

        if not file.cyclical:                       # 1221-1227
            itms = [n, np1]
        else:
            itms = [n + file.cyc_ndx_beg - 1, np1 + file.cyc_ndx_beg - 1]
        fids = [file.curr_file, file.curr_file]     # 1229
        for i in range(2):                          # 1231-1236
            if not is_undef(itms[i]) and itms[i] > curr_tsize:
                itms[i] = itms[i] - curr_tsize
                fids[i] = file.next_file
        return itms, fids, datatimem, datatimep, times_found

    # -- incr_filename (959-1100, the two live branches) --

    def incr_filename(self, filename):
        file = self.file
        have_list = len(file.filenames_list.strip()) > 0  # 996-999
        if not have_list:
            # ccm-style filename increment (1001-1016): bump the last
            # integer field (increment_string semantics on yyyy names).
            stem = filename[:-3] if filename.endswith(".nc") else filename
            digits_end = len(stem)
            digits_beg = digits_end
            while digits_beg > 0 and stem[digits_beg - 1].isdigit():
                digits_beg -= 1
            if digits_beg == digits_end:
                raise Endrun("INCREMENT_STRING_FAILURE", filename)
            number = int(stem[digits_beg:digits_end]) + 1
            new_stem = (stem[:digits_beg]
                        + str(number).zfill(digits_end - digits_beg))
            return new_stem + (".nc" if filename.endswith(".nc") else "")
        # filenames_list branch (1018-1100): open <datapath>/<list>.
        # The join guard is present(datapath), not len_trim (1026-1030), and
        # check_files always passes datapath, so an EMPTY pathname yields the
        # absolute path /<list> -- a latent root-path quirk the differential
        # harness caught in this model's first transcription (which had
        # branched on emptiness). The Filesystem's filelists are rooted at
        # the datapath, so an empty pathname never finds the list.
        filepath = f"{file.pathname}/{file.filenames_list}"
        if (not file.pathname or
                file.filenames_list not in self.fs.filelists):  # 1032-1035
            raise Endrun("OPEN_FAIL", filepath)            # F-INPUTS-4
        names = self.fs.filelists[file.filenames_list]
        if filename == "":
            return names[0]                                # 1055 else-branch
        if filename not in names or names.index(filename) + 1 >= len(names):
            raise Endrun("LIST_EXHAUSTED", filename)
        return names[names.index(filename) + 1]

    # -- check_files (899-955, cyclical_list paths out of scope) --

    def check_files(self):
        file = self.file
        if file.cyclical_list:
            raise Endrun("MODEL_SCOPE", "CYCLICAL_LIST not modeled (latent)")
        # 913: open the next file when model time passes the current list
        if file.next_mod_time > file.curr_data_times[-1]:
            if file.next_data_times is None:     # 922-932
                file.next_filename = self.incr_filename(file.curr_filename)
                file.next_file = self._open(file.next_filename)
                file.next_data_times = [t - file.offset_time
                                        for t in file.next_file.times(self.cal)]
        # 939-953: swap to the next file once model time reaches it
        if file.next_data_times is not None:
            if file.curr_mod_time >= file.next_data_times[0]:  # 950
                self.advance_file()                            # 951

    # -- advance_file (2217-2273) --

    def advance_file(self):
        """Swap the prefetched next file into the current slot."""
        file = self.file
        file.curr_filename = file.next_filename   # 2244-2245
        file.curr_file = file.next_file
        file.curr_data_times = list(file.next_data_times)  # 2250-2260
        file.next_filename = ""                   # 2265
        file.next_file = None
        file.next_data_times = None               # 2267 deallocate

    # -- set_cycle_indices (1983-2027) --

    # pylint: disable=no-self-use
    def set_cycle_indices(self, data_file, cyc_yr):
        """Returns (cyc_ndx_beg, cyc_ndx_end) relative to <data_file>'s own
        time dimension -- the caller is responsible for any concatenation
        offset (the F-INPUTS-2 gap)."""
        beg = -1
        end = UNDEF                               # intent(out), only set
        for i, date in enumerate(data_file.dates, start=1):  # 2009-2017
            if date // 10000 == cyc_yr:
                if beg < 0:
                    beg = i
                end = i
        if beg < 0:                               # 2022-2025
            raise Endrun("CYC_YEAR_NOT_FOUND", str(cyc_yr))
        return beg, end

    # -- read_next_trcdata (1240-1412, record reads recorded only) --

    def read_next_trcdata(self, result):
        """The search loop, the fill path, and the record reads."""
        file = self.file
        recnos = [UNDEF] * 4
        fids = [None] * 4
        times_found = False                       # 1262

        rounds = 0
        while not times_found:                    # 1264-1269
            state_before = self._search_state()
            itms, sfids, dtm, dtp, times_found = \
                self.find_times(file.curr_mod_time, times_found)
            file.datatimem, file.datatimep = dtm, dtp
            if times_found:
                recnos[0:2] = itms
                fids[0:2] = sfids
            else:
                self.check_files()                # 1267
                if self.fix_search_contract and \
                        self._search_state() == state_before:
                    raise Endrun("SEARCH_NO_PROGRESS", file.curr_filename)
                rounds += 1
                if self._search_state() == state_before:
                    # The real loop repeats this exact state forever.
                    raise Livelock(
                        f"state unchanged after round {rounds} "
                        f"(do while never exits), file={file.curr_filename}")

        # fix_file_window: normalize "earlier record in curr" (F-INPUTS-2
        # fix shape) by advancing the window and searching again.
        if self.fix_file_window and fids[0] is file.next_file \
                and file.next_file is not None:
            self.advance_file()
            itms, sfids, dtm, dtp, times_found = \
                self.find_times(file.curr_mod_time, times_found)
            file.datatimem, file.datatimep = dtm, dtp
            recnos[0:2] = itms
            fids[0:2] = sfids

        file.interp_recs = 1 if file.stepTime else 2   # 1274-1278

        if file.fill_in_months:                   # 1280
            if file.datatimep - file.datatimem > file.one_yr:  # 1282
                cur_yr, cur_mon, cur_day, cur_sec = \
                    self.clock.get_curr_date()    # 1284
                yr1, _, _, _ = self.cal.date_from_float(file.datatimem)  # 1286
                yr2, _, _, _ = self.cal.date_from_float(file.datatimep)
                series1_time = self.cal.time_float(yr1, cur_mon, cur_day,
                                                   cur_sec)  # 1289
                series2_time = self.cal.time_float(yr2, cur_mon, cur_day,
                                                   cur_sec)
                fid1 = fids[0]                    # 1292-1293
                fid2 = fids[1]
                file.cyclical = True              # 1294
                file.cyc_ndx_beg, file.cyc_ndx_end = \
                    self.set_cycle_indices(fid1, yr1)    # 1295
                itms, sfids, dt1, dt2, times_found = \
                    self.find_times(series1_time, times_found)  # 1296
                file.datatimes[0], file.datatimes[1] = dt1, dt2
                if not times_found:               # 1298-1300
                    raise Endrun("SERIES1_NOT_FOUND")
                if itms is not None:
                    recnos[0:2] = itms
                    fids[0:2] = sfids
                file.cyc_ndx_beg, file.cyc_ndx_end = \
                    self.set_cycle_indices(fid2, yr2)    # 1301
                if fid1.fh != fid2.fh:            # 1303-1306
                    file.cyc_ndx_beg += len(file.curr_data_times)
                    file.cyc_ndx_end += len(file.curr_data_times)
                itms, sfids, dt3, dt4, times_found = \
                    self.find_times(series2_time, times_found)  # 1307
                file.datatimes[2], file.datatimes[3] = dt3, dt4
                if not times_found:               # 1308-1310
                    raise Endrun("SERIES2_NOT_FOUND")
                if itms is not None:
                    recnos[2:4] = itms
                    fids[2:4] = sfids
                file.cyclical = False             # 1311
                file.interp_recs = 4              # 1312

                # Remap datatimem/p into the current year (1314-1328).
                yr1, mon, date, sec = self.cal.date_from_float(
                    file.datatimes[0])            # 1314
                file.datatimem = self.cal.time_float(cur_yr, mon, date, sec)
                if file.datatimes[0] > file.datatimes[1]:  # wrap 1316-1320
                    if cur_mon == 1:
                        file.datatimem = self.cal.time_float(
                            cur_yr - 1, mon, date, sec)
                yr1, mon, date, sec = self.cal.date_from_float(
                    file.datatimes[1])            # 1322
                file.datatimep = self.cal.time_float(cur_yr, mon, date, sec)
                if file.datatimes[0] > file.datatimes[1]:  # wrap 1324-1328
                    if cur_mon == 12:
                        file.datatimep = self.cal.time_float(
                            cur_yr + 1, mon, date, sec)

        # Record the hyperslab reads (1337-1410).
        for i in range(file.interp_recs):
            fname = fids[i].name if fids[i] is not None else UNDEF
            result.reads.append((fname, recnos[i]))

    def _search_state(self):
        """The state the find_times/check_files round depends on."""
        file = self.file
        return (file.curr_filename, file.next_filename,
                file.next_data_times is None, file.cyc_ndx_beg,
                file.cyc_ndx_end, len(file.curr_data_times))

    # -- interpolate_trcdata, weight computation only (1764-1849) --

    def _interpolate_weights(self, result):
        file = self.file
        if file.interp_recs == 4:                 # 1796-1819 one-shot blend
            result.blended = True
            # Record the blend weights (data movement elided). A weight
            # outside [0,1] is the F-INPUTS-2 extrapolation observable.
            deltat = file.datatimes[2] - file.datatimes[0]    # 1797-1799
            bfact1 = (file.datatimes[2] - file.datatimem) / deltat
            result.blend_facts.append((bfact1, 1.0 - bfact1))
            deltat = file.datatimes[3] - file.datatimes[1]    # 1808-1810
            bfact1 = (file.datatimes[3] - file.datatimep) / deltat
            result.blend_facts.append((bfact1, 1.0 - bfact1))
        if file.interp_recs == 1:                 # 1825-1827
            fact1 = 1.0
            fact2 = 0.0
        else:
            file.interp_recs = 2                  # 1829
            deltat = file.datatimep - file.datatimem  # 1831
            if file.cyclical and deltat < 0.0:    # 1833-1839 wrap
                deltat = deltat + file.one_yr
                if file.datatimep >= file.curr_mod_time:
                    fact1 = (file.datatimep - file.curr_mod_time) / deltat
                else:
                    fact1 = (file.datatimep + file.one_yr
                             - file.curr_mod_time) / deltat
            else:                                 # 1841
                fact1 = (file.datatimep - file.curr_mod_time) / deltat
            if file.fixed:                        # 1845-1847
                fact1 = float(int(fact1 * CDAY + 0.5)) / CDAY
            fact2 = 1.0 - fact1
        result.fact1 = fact1
        result.fact2 = fact2

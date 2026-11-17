! Harness stub: a driver-set calendar date plus the date<->float mapping
! transcribed from src/utils/time_manager.F90. The two behaviors under test
! inherit the real module's semantics with line citations:
!   - set_time_float_from_date repairs Feb 29 ONLY when the calendar is
!     NO_LEAP (time_manager.F90:279-281); under GREGORIAN an invalid date
!     reaches ESMF_TimeSet and aborts through chkrc
!     (time_manager.F90:282-283, 1244-1249) -- the F-INPUTS-1 surface.
!   - the float origin is days since 0001-01-01, matching the oracle's
!     Calendar (trc_oracle.py), so time floats agree bit-for-bit.
! Because this module is a stub, the F-INPUTS-1 harness evidence is
! stub-mediated (see README.md blind spots); every other finding fires
! through the real tracer_data.F90.
module time_manager
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private

   public :: get_curr_date, get_step_size
   public :: set_time_float_from_date, set_date_from_time_float
   public :: tm_set_date, tm_set_step, tm_set_calendar

   integer :: cur_yr = 1
   integer :: cur_mon = 1
   integer :: cur_day = 1
   integer :: cur_sec = 0
   integer :: cur_dtime = 1800
   logical :: cal_noleap = .true.

   integer, parameter :: days_per_month(12) = &
        [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
   integer, parameter :: cum_days(12) = &
        [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

contains

   subroutine tm_set_date(yr, mon, day, sec)
      integer, intent(in) :: yr, mon, day, sec
      cur_yr = yr
      cur_mon = mon
      cur_day = day
      cur_sec = sec
   end subroutine tm_set_date

   subroutine tm_set_step(dtime)
      integer, intent(in) :: dtime
      cur_dtime = dtime
   end subroutine tm_set_step

   subroutine tm_set_calendar(name)
      use cam_abortutils, only: endrun
      character(len=*), intent(in) :: name
      select case (trim(name))
      case ('NO_LEAP')
         cal_noleap = .true.
      case ('GREGORIAN')
         cal_noleap = .false.
      case default
         call endrun('tm_set_calendar: unknown calendar '//trim(name))
      end select
   end subroutine tm_set_calendar

   integer function get_step_size()
      get_step_size = cur_dtime
   end function get_step_size

   subroutine get_curr_date(yr, mon, day, tod)
      integer, intent(out) :: yr, mon, day, tod
      yr = cur_yr
      mon = cur_mon
      day = cur_day
      tod = cur_sec
   end subroutine get_curr_date

   logical function greg_is_leap(yr)
      integer, intent(in) :: yr
      greg_is_leap = (mod(yr, 4) == 0 .and. &
           (mod(yr, 100) /= 0 .or. mod(yr, 400) == 0))
   end function greg_is_leap

   integer function greg_month_len(yr, mon)
      integer, intent(in) :: yr, mon
      greg_month_len = days_per_month(mon)
      if (mon == 2 .and. greg_is_leap(yr)) greg_month_len = 29
   end function greg_month_len

   integer function greg_days_from_civil(yr, mon, day)
      ! Proleptic-Gregorian day count with 0001-01-01 = day 0
      ! (Hinnant's days_from_civil rebased from the 1970 epoch).
      integer, intent(in) :: yr, mon, day
      integer :: yy, era, yoe, doy, doe
      yy = yr
      if (mon <= 2) yy = yy - 1
      era = yy/400
      if (yy < 0 .and. mod(yy, 400) /= 0) era = era - 1
      yoe = yy - era*400
      if (mon > 2) then
         doy = (153*(mon - 3) + 2)/5 + day - 1
      else
         doy = (153*(mon + 9) + 2)/5 + day - 1
      end if
      doe = yoe*365 + yoe/4 - yoe/100 + doy
      greg_days_from_civil = era*146097 + doe - 306
   end function greg_days_from_civil

   subroutine greg_civil_from_days(days, yr, mon, day)
      integer, intent(in)  :: days
      integer, intent(out) :: yr, mon, day
      integer :: z, era, doe, yoe, doy, mp
      z = days + 306
      era = z/146097
      if (z < 0 .and. mod(z, 146097) /= 0) era = era - 1
      doe = z - era*146097
      yoe = (doe - doe/1460 + doe/36524 - doe/146096)/365
      yr = yoe + era*400
      doy = doe - (365*yoe + yoe/4 - yoe/100)
      mp = (5*doy + 2)/153
      day = doy - (153*mp + 2)/5 + 1
      if (mp < 10) then
         mon = mp + 3
      else
         mon = mp - 9
      end if
      if (mon <= 2) yr = yr + 1
   end subroutine greg_civil_from_days

   subroutine chkrc_abort(yr, mon, day)
      ! ESMF_TimeSet rejected the date: chkrc endrun
      ! (time_manager.F90:1244-1249). The event tag is the stable
      ! identifier; the comparator never matches the log prose.
      use harness_events, only: ev_emit
      use cam_abortutils, only: endrun
      use cam_logfile,    only: iulog
      integer, intent(in) :: yr, mon, day
      call ev_emit('chkrc')
      write(iulog, '(a,3i6)') 'chkrc: invalid date ', yr, mon, day
      call endrun('chkrc: ESMF_TimeSet failed')
   end subroutine chkrc_abort

   subroutine set_time_float_from_date(time, yr, mon, day, sec)
      real(r8), intent(out) :: time
      integer,  intent(in)  :: yr, mon, day, sec
      integer :: useday
      useday = day
      ! Transcribed repair guard (time_manager.F90:279-281): Feb 29 is
      ! repaired to Feb 28 only under NO_LEAP; GREGORIAN passes the raw
      ! date through to ESMF, which rejects it for a non-leap year.
      if (mon == 2 .and. day == 29 .and. cal_noleap) useday = 28
      if (mon < 1 .or. mon > 12 .or. useday < 1) call chkrc_abort(yr, mon, useday)
      if (cal_noleap) then
         if (useday > days_per_month(mon) .and. &
              .not. (mon == 2 .and. useday == 29)) then
            call chkrc_abort(yr, mon, useday)
         end if
         time = real(yr - 1, r8)*365.0_r8 + real(cum_days(mon), r8) &
              + real(useday - 1, r8) + real(sec, r8)/86400.0_r8
      else
         if (useday > greg_month_len(yr, mon)) call chkrc_abort(yr, mon, useday)
         time = real(greg_days_from_civil(yr, mon, useday), r8) &
              + real(sec, r8)/86400.0_r8
      end if
   end subroutine set_time_float_from_date

   subroutine set_date_from_time_float(time, yr, mon, day, sec)
      real(r8), intent(in)  :: time
      integer,  intent(out) :: yr, mon, day, sec
      integer :: days, doy
      ! Garbage guard: defect scenarios legitimately pass undefined floats
      ! down this path (downstream-of-UNDEF, never compared); return a
      ! harmless fixed date instead of overflowing int().
      if (.not. (time == time) .or. abs(time) > 1.0e15_r8) then
         yr = -9999
         mon = 1
         day = 1
         sec = 0
         return
      end if
      days = int(time)
      sec = nint((time - real(days, r8))*86400.0_r8)
      if (cal_noleap) then
         yr = days/365 + 1
         doy = mod(days, 365)
         mon = 1
         do while (mon < 12 .and. doy >= cum_days(mon + 1))
            mon = mon + 1
         end do
         day = doy - cum_days(mon) + 1
      else
         call greg_civil_from_days(days, yr, mon, day)
      end if
   end subroutine set_date_from_time_float

end module time_manager

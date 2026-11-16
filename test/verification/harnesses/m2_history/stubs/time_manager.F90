! Harness stub: model time is state the driver sets explicitly, so scenarios
! control nstep and the calendar date deterministically.  Only the members
! the history code references are provided.  Dates use a 365-day NO_LEAP
! calendar starting at the reference date.
module time_manager
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private

   public :: get_step_size, get_nstep, get_curr_date, get_prev_date
   public :: get_curr_time, get_ref_date, timemgr_get_calendar_cf
   public :: set_date_from_time_float
   public :: tm_harness_set

   integer :: cur_dtime = 1800
   integer :: cur_nstep = 0
   integer :: ref_ymd = 10101  ! 0001-01-01
   integer :: ref_tod = 0

   integer, parameter :: days_per_month(12) = &
        [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

contains

   subroutine tm_harness_set(dtime, nstep)
      integer, intent(in) :: dtime
      integer, intent(in) :: nstep
      cur_dtime = dtime
      cur_nstep = nstep
   end subroutine tm_harness_set

   integer function get_step_size()
      get_step_size = cur_dtime
   end function get_step_size

   integer function get_nstep()
      get_nstep = cur_nstep
   end function get_nstep

   subroutine days_to_date(days, yr, mon, day)
      ! NO_LEAP days since 0001-01-01 (day 0) to calendar date
      integer, intent(in)  :: days
      integer, intent(out) :: yr, mon, day
      integer :: rem
      yr = 1 + days / 365
      rem = mod(days, 365)
      mon = 1
      do while (rem >= days_per_month(mon))
         rem = rem - days_per_month(mon)
         mon = mon + 1
      end do
      day = rem + 1
   end subroutine days_to_date

   subroutine get_curr_date(yr, mon, day, tod, offset)
      integer, intent(out) :: yr, mon, day, tod
      integer, optional, intent(in) :: offset
      integer :: totsec, days
      totsec = cur_nstep * cur_dtime
      if (present(offset)) totsec = totsec + offset
      days = totsec / 86400
      tod = mod(totsec, 86400)
      call days_to_date(days, yr, mon, day)
   end subroutine get_curr_date

   subroutine get_prev_date(yr, mon, day, tod)
      integer, intent(out) :: yr, mon, day, tod
      integer :: totsec, days
      totsec = max(cur_nstep - 1, 0) * cur_dtime
      days = totsec / 86400
      tod = mod(totsec, 86400)
      call days_to_date(days, yr, mon, day)
   end subroutine get_prev_date

   subroutine get_curr_time(days, seconds)
      integer, intent(out) :: days, seconds
      integer :: totsec
      totsec = cur_nstep * cur_dtime
      days = totsec / 86400
      seconds = mod(totsec, 86400)
   end subroutine get_curr_time

   subroutine get_ref_date(yr, mon, day, tod)
      integer, intent(out) :: yr, mon, day, tod
      yr = ref_ymd / 10000
      mon = mod(ref_ymd / 100, 100)
      day = mod(ref_ymd, 100)
      tod = ref_tod
   end subroutine get_ref_date

   function timemgr_get_calendar_cf() result(cal)
      character(len=32) :: cal
      cal = 'noleap'
   end function timemgr_get_calendar_cf

   subroutine set_date_from_time_float(time, year, month, day, sec)
      ! time is fractional days since the reference date
      real(r8), intent(in)  :: time
      integer,  intent(out) :: year, month, day, sec
      integer :: days
      days = int(time)
      sec = nint((time - real(days, r8)) * 86400.0_r8)
      call days_to_date(days, year, month, day)
   end subroutine set_date_from_time_float

end module time_manager

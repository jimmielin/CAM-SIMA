! Harness stub: endrun emits an abort event, then stops with a distinct code
! so the comparator sees aborts as structured outcomes, never as prose.
module cam_abortutils
   implicit none
   private
   public :: endrun, safe_endrun, check_allocate

contains

   subroutine endrun(message, file, line)
      use harness_events, only: ev_abort
      use cam_logfile, only: iulog
      character(len=*),           intent(in) :: message
      character(len=*), optional, intent(in) :: file
      integer,          optional, intent(in) :: line
      write(iulog, '(2a)') 'ENDRUN: ', trim(message)
      call ev_abort('endrun')
      stop 17
   end subroutine endrun

   subroutine safe_endrun(message, file, line)
      character(len=*),           intent(in) :: message
      character(len=*), optional, intent(in) :: file
      integer,          optional, intent(in) :: line
      call endrun(message, file=file, line=line)
   end subroutine safe_endrun

   subroutine check_allocate(errcode, subname, fieldname, file, line, errmsg)
      integer,                    intent(in) :: errcode
      character(len=*),           intent(in) :: subname
      character(len=*),           intent(in) :: fieldname
      character(len=*), optional, intent(in) :: file
      integer,          optional, intent(in) :: line
      character(len=*), optional, intent(in) :: errmsg
      if (errcode /= 0) then
         call endrun(trim(subname)//': allocate of '//trim(fieldname)//' failed')
      end if
   end subroutine check_allocate

end module cam_abortutils

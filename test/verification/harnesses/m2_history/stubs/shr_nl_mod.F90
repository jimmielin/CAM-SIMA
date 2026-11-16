! Harness stub: namelist-group search, only linked (never called) here
module shr_nl_mod
   implicit none
   private
   public :: shr_nl_find_group_name
contains
   subroutine shr_nl_find_group_name(unit, group, status)
      integer,          intent(in)  :: unit
      character(len=*), intent(in)  :: group
      integer, optional, intent(out) :: status
      if (present(status)) status = 1
   end subroutine shr_nl_find_group_name
end module shr_nl_mod

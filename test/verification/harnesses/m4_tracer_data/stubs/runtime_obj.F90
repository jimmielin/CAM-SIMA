! Harness stub: the unset sentinels from src/control/runtime_obj.F90
module runtime_obj
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   public
   integer,          parameter :: unset_int  = huge(1)
   character(len=*), parameter :: unset_str  = 'UNSET'
   real(r8),         parameter :: unset_real = huge(1.0_r8)
end module runtime_obj

! Harness stub: only cday is referenced by the history code
module physconst
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   public
   real(r8), parameter :: cday = 86400.0_r8
end module physconst

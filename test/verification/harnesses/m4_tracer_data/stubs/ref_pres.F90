! Harness stub: reference top pressure (only used by vert_interp_ub,
! which the surface-field scenarios never reach)
module ref_pres
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   public
   real(r8), parameter :: ptop_ref = 100.0_r8
end module ref_pres

! Harness stub, compile-only: rebin is only reached for altitude-coordinate
! data, which the scenarios never use.
module ccpp_tuvx_utils
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private
   public :: rebin

contains

   subroutine rebin(nsrc, ntrg, src_x, trg_x, src, trg)
      integer,  intent(in)  :: nsrc
      integer,  intent(in)  :: ntrg
      real(r8), intent(in)  :: src_x(:)
      real(r8), intent(in)  :: trg_x(:)
      real(r8), intent(in)  :: src(:)
      real(r8), intent(out) :: trg(:)
      trg = 0.0_r8
   end subroutine rebin

end module ccpp_tuvx_utils

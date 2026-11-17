! Harness stub, compile-only: the unstructured surface-field scenarios
! never take the lat/lon interpolation paths (read_2d_trc/read_3d_trc/
! read_za_trc), so these bodies are no-ops that zero their outputs.
module interpolate_data
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private

   public :: interp_type, lininterp_init, lininterp, lininterp_finish

   type :: interp_type
      integer :: n = 0
   end type interp_type

   interface lininterp
      module procedure lininterp_1d
      module procedure lininterp_2d
      module procedure lininterp_3d
   end interface lininterp

contains

   subroutine lininterp_init(yin, nin, yout, nout, extrap_method, wgts, &
        cyclicmin, cyclicmax)
      real(r8),           intent(in)  :: yin(:)
      integer,            intent(in)  :: nin
      real(r8),           intent(in)  :: yout(:)
      integer,            intent(in)  :: nout
      integer,            intent(in)  :: extrap_method
      type(interp_type),  intent(out) :: wgts
      real(r8), optional, intent(in)  :: cyclicmin
      real(r8), optional, intent(in)  :: cyclicmax
      wgts%n = nout
   end subroutine lininterp_init

   subroutine lininterp_1d(arrin, nin, arrout, nout, wgts)
      real(r8),          intent(in)  :: arrin(:)
      integer,           intent(in)  :: nin
      real(r8),          intent(out) :: arrout(:)
      integer,           intent(in)  :: nout
      type(interp_type), intent(in)  :: wgts
      arrout = 0.0_r8
   end subroutine lininterp_1d

   subroutine lininterp_2d(arrin, nlon, nlat, arrout, nout, wgts1, wgts2)
      real(r8),          intent(in)  :: arrin(:, :)
      integer,           intent(in)  :: nlon
      integer,           intent(in)  :: nlat
      real(r8),          intent(out) :: arrout(:)
      integer,           intent(in)  :: nout
      type(interp_type), intent(in)  :: wgts1
      type(interp_type), intent(in)  :: wgts2
      arrout = 0.0_r8
   end subroutine lininterp_2d

   subroutine lininterp_3d(arrin, nlon, nlat, nlev, arrout, ncols, nout, &
        wgts1, wgts2)
      real(r8),          intent(in)  :: arrin(:, :, :)
      integer,           intent(in)  :: nlon
      integer,           intent(in)  :: nlat
      integer,           intent(in)  :: nlev
      real(r8),          intent(out) :: arrout(:, :)
      integer,           intent(in)  :: ncols
      integer,           intent(in)  :: nout
      type(interp_type), intent(in)  :: wgts1
      type(interp_type), intent(in)  :: wgts2
      arrout = 0.0_r8
   end subroutine lininterp_3d

   subroutine lininterp_finish(wgts)
      type(interp_type), intent(inout) :: wgts
      wgts%n = 0
   end subroutine lininterp_finish

end module interpolate_data

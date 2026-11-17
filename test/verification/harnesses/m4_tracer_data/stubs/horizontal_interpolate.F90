! Harness stub, compile-only: weight_by_lat is never set by the scenarios.
module horizontal_interpolate
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private

   public :: xy_interp

   interface xy_interp
      module procedure xy_interp_2d
      module procedure xy_interp_3d
   end interface xy_interp

contains

   subroutine xy_interp_2d(nlon, nlat, nlev, plon, plat, pcols, ncols, &
        wx, wy, din, dout, lons, lats, cx, cy, ix, iy)
      integer,  intent(in)  :: nlon, nlat, nlev, plon, plat, pcols, ncols
      real(r8), intent(in)  :: wx(:, :), wy(:, :)
      real(r8), intent(in)  :: din(:, :)
      real(r8), intent(out) :: dout(:)
      integer,  intent(in)  :: lons(:), lats(:)
      integer,  intent(in)  :: cx(:), cy(:)
      integer,  intent(in)  :: ix(:, :), iy(:, :)
      dout = 0.0_r8
   end subroutine xy_interp_2d

   subroutine xy_interp_3d(nlon, nlat, nlev, plon, plat, pcols, ncols, &
        wx, wy, din, dout, lons, lats, cx, cy, ix, iy)
      integer,  intent(in)  :: nlon, nlat, nlev, plon, plat, pcols, ncols
      real(r8), intent(in)  :: wx(:, :), wy(:, :)
      real(r8), intent(in)  :: din(:, :, :)
      real(r8), intent(out) :: dout(:, :)
      integer,  intent(in)  :: lons(:), lats(:)
      integer,  intent(in)  :: cx(:), cy(:)
      integer,  intent(in)  :: ix(:, :), iy(:, :)
      dout = 0.0_r8
   end subroutine xy_interp_3d

end module horizontal_interpolate

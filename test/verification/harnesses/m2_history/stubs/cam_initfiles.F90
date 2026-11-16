! Harness stub: fixed input file names for the history header
module cam_initfiles
   use shr_kind_mod, only: cl => shr_kind_cl
   implicit none
   public
   character(len=cl) :: ncdata = 'fixture_ncdata.nc'
   character(len=cl) :: bnd_topo = 'fixture_topo.nc'
end module cam_initfiles

! Harness stub: fixed case metadata for filename interpolation
module cam_control_mod
   use shr_kind_mod, only: cl => shr_kind_cl
   implicit none
   public
   character(len=cl) :: caseid = 'm2case'
   character(len=cl) :: ctitle = 'M2 harness'
end module cam_control_mod

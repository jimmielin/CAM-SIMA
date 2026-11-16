! Harness stub: route the model log to stderr so stdout carries only events
module cam_logfile
   use, intrinsic :: iso_fortran_env, only: error_unit
   implicit none
   public
   integer :: iulog = error_unit
   integer, parameter :: debug_output_none = 0
   integer :: debug_output = 0
end module cam_logfile

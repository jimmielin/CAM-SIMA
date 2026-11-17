! Harness stub: serial run, rank 0 is master
module spmd_utils
   implicit none
   public
   logical, parameter :: masterproc = .true.
   integer, parameter :: masterprocid = 0
   integer, parameter :: iam = 0
   integer, parameter :: npes = 1
   integer, parameter :: mpicom = 0
end module spmd_utils

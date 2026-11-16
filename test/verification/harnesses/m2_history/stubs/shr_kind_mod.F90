! Harness stub: kind constants matching share/util/shr_kind_mod.F90
module shr_kind_mod
   use, intrinsic :: iso_fortran_env, only: real64, real32, int64
   implicit none
   public
   integer, parameter :: shr_kind_r8 = real64
   integer, parameter :: shr_kind_r4 = real32
   integer, parameter :: shr_kind_i8 = int64
   integer, parameter :: shr_kind_in = kind(1)
   integer, parameter :: shr_kind_cs = 80
   integer, parameter :: shr_kind_cm = 160
   integer, parameter :: shr_kind_cl = 256
   integer, parameter :: shr_kind_cx = 512
   integer, parameter :: shr_kind_cxx = 4096
end module shr_kind_mod

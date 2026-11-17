! Harness stub: only pi, cday and rga are referenced by tracer_data
module physconst
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   public
   real(r8), parameter :: pi = 3.14159265358979323846_r8
   real(r8), parameter :: cday = 86400.0_r8
   real(r8), parameter :: gravit = 9.80616_r8
   real(r8), parameter :: rga = 1.0_r8/gravit
end module physconst

! Harness stub: a tiny vertical grid. The scenarios drive surface fields
! only, so pver is never used for interpolation, just for array shapes.
module vert_coord
   implicit none
   public
   integer, parameter :: pver = 2
   integer, parameter :: pverp = 3
end module vert_coord

! Harness stub: no acquisition step; the path passes through and existence
! is checked at open time against the dataset registry.
module ioFileMod
   implicit none
   private
   public :: cam_get_file

contains

   subroutine cam_get_file(iofile, localfile, allow_fail)
      character(len=*),  intent(in)  :: iofile
      character(len=*),  intent(out) :: localfile
      logical, optional, intent(in)  :: allow_fail
      localfile = trim(iofile)
   end subroutine cam_get_file

end module ioFileMod

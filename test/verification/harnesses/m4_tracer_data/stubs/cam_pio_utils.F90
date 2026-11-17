! Harness stub: opening a dataset binds the descriptor to the registry
! entry whose name matches the path's basename; a missing dataset aborts,
! as a missing file would through PIO.
module cam_pio_utils
   implicit none
   private
   public :: cam_pio_openfile

contains

   subroutine cam_pio_openfile(file, fname, mode)
      use pio,            only: file_desc_t, harness_open_dataset
      use harness_events, only: ev_emit
      use cam_abortutils, only: endrun
      type(file_desc_t), intent(inout) :: file
      character(len=*),  intent(in)    :: fname
      integer,           intent(in)    :: mode
      character(len=256) :: base
      integer :: pos
      pos = index(fname, '/', back=.true.)
      base = fname(pos + 1:)
      file%fh = harness_open_dataset(trim(base))
      if (file%fh < 0) then
         call ev_emit('openfail|'//trim(base))
         call endrun('cam_pio_openfile: no such dataset '//trim(fname))
      end if
      call ev_emit('openfile|'//trim(base))
   end subroutine cam_pio_openfile

end module cam_pio_utils

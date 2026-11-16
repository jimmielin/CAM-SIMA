! The recorder shared by every stub: emits one `EV|...` line per observable
! action on stdout and keeps the file/variable registries the PIO stub needs.
! The comparator parses only these lines, so stdout must stay otherwise clean
! (the model log goes to stderr via the cam_logfile stub).
module harness_events
   use, intrinsic :: iso_fortran_env, only: output_unit
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private

   public :: ev_emit, ev_createfile, ev_closefile, ev_defvar, ev_writevalues
   public :: ev_abort, ev_find_var, ev_file_name
   public :: ev_next_file_handle, ev_next_var_id

   integer, parameter, public :: ev_name_len = 256

   integer, parameter :: max_files = 64
   integer, parameter :: max_vars = 512

   integer :: num_files = 0
   character(len=ev_name_len) :: file_names(max_files) = ''

   integer :: num_vars = 0
   integer :: var_file(max_vars) = -1
   character(len=ev_name_len) :: var_names(max_vars) = ''

contains

   subroutine ev_emit(line)
      character(len=*), intent(in) :: line
      write(output_unit, '(a)') 'EV|'//trim(line)
      flush(output_unit)
   end subroutine ev_emit

   function ev_next_file_handle(fname) result(fh)
      character(len=*), intent(in) :: fname
      integer :: fh
      num_files = num_files + 1
      fh = num_files
      file_names(fh) = trim(fname)
   end function ev_next_file_handle

   function ev_file_name(fh) result(fname)
      integer, intent(in) :: fh
      character(len=ev_name_len) :: fname
      if (fh >= 1 .and. fh <= num_files) then
         fname = file_names(fh)
      else
         fname = '<unknown-file>'
      end if
   end function ev_file_name

   function ev_next_var_id(fh, vname) result(vid)
      integer, intent(in) :: fh
      character(len=*), intent(in) :: vname
      integer :: vid
      num_vars = num_vars + 1
      vid = num_vars
      var_file(vid) = fh
      var_names(vid) = trim(vname)
   end function ev_next_var_id

   function ev_find_var(fh, vname) result(vid)
      integer, intent(in) :: fh
      character(len=*), intent(in) :: vname
      integer :: vid
      integer :: idx
      vid = -1
      do idx = 1, num_vars
         if (var_file(idx) == fh .and. trim(var_names(idx)) == trim(vname)) then
            vid = idx
            return
         end if
      end do
   end function ev_find_var

   subroutine ev_createfile(fh)
      integer, intent(in) :: fh
      call ev_emit('createfile|'//trim(itoa(fh))//'|'//trim(ev_file_name(fh)))
   end subroutine ev_createfile

   subroutine ev_closefile(fh)
      integer, intent(in) :: fh
      call ev_emit('closefile|'//trim(itoa(fh))//'|'//trim(ev_file_name(fh)))
   end subroutine ev_closefile

   subroutine ev_defvar(fh, vname)
      integer, intent(in) :: fh
      character(len=*), intent(in) :: vname
      call ev_emit('defvar|'//trim(itoa(fh))//'|'//trim(vname))
   end subroutine ev_defvar

   subroutine ev_writevalues(fh, vname, frame, values)
      integer, intent(in) :: fh
      character(len=*), intent(in) :: vname
      integer, intent(in) :: frame
      real(r8), intent(in) :: values(:)
      character(len=2048) :: line
      character(len=32) :: valstr
      integer :: idx, nvals
      ! Emit every value (fields in this harness are small)
      nvals = size(values)
      write(line, '(5a,i0)') 'writefield|', trim(itoa(fh)), '|', trim(vname), &
           '|', frame
      do idx = 1, nvals
         write(valstr, '(es24.16)') values(idx)
         line = trim(line)//'|'//trim(adjustl(valstr))
      end do
      call ev_emit(line)
   end subroutine ev_writevalues

   subroutine ev_abort(tag)
      character(len=*), intent(in) :: tag
      call ev_emit('abort|'//trim(tag))
   end subroutine ev_abort

   function itoa(ival) result(str)
      integer, intent(in) :: ival
      character(len=16) :: str
      write(str, '(i0)') ival
   end function itoa

end module harness_events

! Harness stub: the PIO surface the history code touches, backed by the
! harness recorder.  def_var registers variables; put_var on numeric data
! emits events; attributes are accepted and dropped.  A var_desc_t carries
! its name, file handle and current frame so copies stored in hist_file_t
! arrays keep working (value semantics, as with real PIO descriptors).
module pio
   use shr_kind_mod,   only: r8 => shr_kind_r8, r4 => shr_kind_r4
   use harness_events, only: ev_name_len
   implicit none
   private

   public :: file_desc_t, var_desc_t
   public :: pio_def_var, pio_enddef, pio_file_is_open, pio_inq_varid
   public :: pio_put_att, pio_put_var, pio_setframe
   public :: PIO_NOERR, PIO_CLOBBER, PIO_GLOBAL, PIO_OFFSET_KIND
   public :: pio_double, pio_real, pio_int, pio_char, pio_unlimited
   public :: pio_bcast_error, pio_internal_error, pio_seterrorhandling

   integer, parameter :: pio_bcast_error = 21
   integer, parameter :: pio_internal_error = 22
   integer, parameter :: PIO_NOERR = 0
   integer, parameter :: PIO_CLOBBER = 2
   integer, parameter :: PIO_GLOBAL = -1
   integer, parameter :: PIO_OFFSET_KIND = selected_int_kind(13)
   integer, parameter :: pio_double = 6
   integer, parameter :: pio_real = 5
   integer, parameter :: pio_int = 4
   integer, parameter :: pio_char = 2
   integer, parameter :: pio_unlimited = 0

   type :: file_desc_t
      integer :: fh = -1
      logical :: is_open = .false.
   end type file_desc_t

   type :: var_desc_t
      integer :: varid = -1
      integer :: fh = -1
      character(len=ev_name_len) :: name = ''
      integer :: frame = -1
   end type var_desc_t

   interface pio_def_var
      module procedure def_var_dims, def_var_scalar
   end interface pio_def_var

   interface pio_put_att
      module procedure att_var_char, att_var_int, att_var_r8, att_var_r4
      module procedure att_var_ints
      module procedure att_glob_char, att_glob_int, att_glob_r8
   end interface pio_put_att

   interface pio_put_var
      module procedure put_int, put_r8, put_char
      module procedure put_int1, put_r8_1, put_r8_2, put_char1
      module procedure put_start_int1, put_start_r8_1
      module procedure put_sc_int1, put_sc_r8_1, put_sc_char1
   end interface pio_put_var

contains

   integer function def_var_dims(file, name, dtype, dimids, vardesc) result(ierr)
      use harness_events, only: ev_next_var_id, ev_defvar
      type(file_desc_t), intent(in)    :: file
      character(len=*),  intent(in)    :: name
      integer,           intent(in)    :: dtype
      integer,           intent(in)    :: dimids(:)
      type(var_desc_t),  intent(inout) :: vardesc
      vardesc%varid = ev_next_var_id(file%fh, name)
      vardesc%fh = file%fh
      vardesc%name = trim(name)
      vardesc%frame = -1
      call ev_defvar(file%fh, name)
      ierr = PIO_NOERR
   end function def_var_dims

   integer function def_var_scalar(file, name, dtype, vardesc) result(ierr)
      use harness_events, only: ev_next_var_id, ev_defvar
      type(file_desc_t), intent(in)    :: file
      character(len=*),  intent(in)    :: name
      integer,           intent(in)    :: dtype
      type(var_desc_t),  intent(inout) :: vardesc
      vardesc%varid = ev_next_var_id(file%fh, name)
      vardesc%fh = file%fh
      vardesc%name = trim(name)
      vardesc%frame = -1
      call ev_defvar(file%fh, name)
      ierr = PIO_NOERR
   end function def_var_scalar

   integer function pio_enddef(file) result(ierr)
      type(file_desc_t), intent(in) :: file
      ierr = PIO_NOERR
   end function pio_enddef

   logical function pio_file_is_open(file)
      type(file_desc_t), intent(in) :: file
      pio_file_is_open = file%is_open
   end function pio_file_is_open

   integer function pio_inq_varid(file, name, vardesc) result(ierr)
      use harness_events, only: ev_find_var
      type(file_desc_t), intent(in)    :: file
      character(len=*),  intent(in)    :: name
      type(var_desc_t),  intent(inout) :: vardesc
      integer :: vid
      vid = ev_find_var(file%fh, name)
      if (vid > 0) then
         vardesc%varid = vid
         vardesc%fh = file%fh
         vardesc%name = trim(name)
         ierr = PIO_NOERR
      else
         ierr = -49
      end if
   end function pio_inq_varid

   subroutine pio_seterrorhandling(file, method, oldmethod)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: method
      integer, optional, intent(out)   :: oldmethod
      if (present(oldmethod)) oldmethod = pio_internal_error
   end subroutine pio_seterrorhandling

   subroutine pio_setframe(file, vardesc, frame)
      type(file_desc_t), intent(in)    :: file
      type(var_desc_t),  intent(inout) :: vardesc
      integer(PIO_OFFSET_KIND), intent(in) :: frame
      vardesc%frame = int(frame)
   end subroutine pio_setframe

   ! ---- attributes: accepted, not recorded --------------------------------

   integer function att_var_char(file, vardesc, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: name, val
      ierr = PIO_NOERR
   end function att_var_char

   integer function att_var_int(file, vardesc, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: name
      integer,           intent(in) :: val
      ierr = PIO_NOERR
   end function att_var_int

   integer function att_var_r8(file, vardesc, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: name
      real(r8),          intent(in) :: val
      ierr = PIO_NOERR
   end function att_var_r8

   integer function att_var_r4(file, vardesc, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: name
      real(r4),          intent(in) :: val
      ierr = PIO_NOERR
   end function att_var_r4

   integer function att_var_ints(file, vardesc, name, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: name
      integer,           intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function att_var_ints

   integer function att_glob_char(file, varid, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      integer,           intent(in) :: varid
      character(len=*),  intent(in) :: name, val
      ierr = PIO_NOERR
   end function att_glob_char

   integer function att_glob_int(file, varid, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      integer,           intent(in) :: varid
      character(len=*),  intent(in) :: name
      integer,           intent(in) :: val
      ierr = PIO_NOERR
   end function att_glob_int

   integer function att_glob_r8(file, varid, name, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      integer,           intent(in) :: varid
      character(len=*),  intent(in) :: name
      real(r8),          intent(in) :: val
      ierr = PIO_NOERR
   end function att_glob_r8

   ! ---- put_var: scalar and framed writes ---------------------------------

   integer function put_int(file, vardesc, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: val
      ierr = PIO_NOERR
   end function put_int

   integer function put_r8(file, vardesc, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      real(r8),          intent(in) :: val
      ierr = PIO_NOERR
   end function put_r8

   integer function put_char(file, vardesc, val) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: val
      ierr = PIO_NOERR
   end function put_char

   integer function put_int1(file, vardesc, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_int1

   integer function put_r8_1(file, vardesc, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      real(r8),          intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_r8_1

   integer function put_r8_2(file, vardesc, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      real(r8),          intent(in) :: vals(:,:)
      ierr = PIO_NOERR
   end function put_r8_2

   integer function put_char1(file, vardesc, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      character(len=*),  intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_char1

   integer function put_start_int1(file, vardesc, start, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: start(:)
      integer,           intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_start_int1

   integer function put_start_r8_1(file, vardesc, start, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: start(:)
      real(r8),          intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_start_r8_1

   integer function put_sc_int1(file, vardesc, start, count, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: start(:), count(:)
      integer,           intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_sc_int1

   integer function put_sc_r8_1(file, vardesc, start, count, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: start(:), count(:)
      real(r8),          intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_sc_r8_1

   integer function put_sc_char1(file, vardesc, start, count, vals) result(ierr)
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: vardesc
      integer,           intent(in) :: start(:), count(:)
      character(len=*),  intent(in) :: vals(:)
      ierr = PIO_NOERR
   end function put_sc_char1

end module pio

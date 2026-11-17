! Harness stub: an in-memory PIO. Datasets are registered by the driver
! (name + date/datesec coordinate arrays, the information a real tracer
! file carries); opening binds a file_desc_t handle to a dataset, and
! pio_get_var serves the 'date'/'datesec' arrays. Every file carries one
! surface field named TESTFLD, read through the cam_field_read stub.
! Hyperslab reads, attributes and the restart define/put surface are
! compile-only: the unstructured surface-field scenarios never reach them.
module pio
   use shr_kind_mod, only: r8 => shr_kind_r8
   implicit none
   private

   type, public :: file_desc_t
      integer :: fh = -1
   end type file_desc_t

   type, public :: var_desc_t
      integer :: fh = -1
      integer :: code = -1
   end type var_desc_t

   integer, parameter, public :: PIO_NOERR = 0
   integer, parameter, public :: PIO_BCAST_ERROR = 1
   integer, parameter, public :: PIO_INTERNAL_ERROR = 2
   integer, parameter, public :: PIO_NOWRITE = 0
   integer, parameter, public :: pio_char = 1

   integer, parameter :: PIO_ERR = -33
   ! Variable codes (var_desc_t%code / integer varids)
   integer, parameter :: VAR_DATE = 1
   integer, parameter :: VAR_DATESEC = 2
   integer, parameter :: VAR_FIELD = 3
   ! Dimension ids
   integer, parameter :: DIM_NCOL = 1
   integer, parameter :: DIM_TIME = 2

   character(len=*), parameter, public :: harness_field_name = 'TESTFLD'

   integer, parameter :: max_ds = 16
   integer, parameter :: max_times = 64
   integer, parameter :: max_handles = 64

   integer :: num_ds = 0
   character(len=256) :: ds_name(max_ds) = ''
   integer :: ds_nt(max_ds) = 0
   integer :: ds_dates(max_times, max_ds) = 0
   integer :: ds_secs(max_times, max_ds) = 0

   integer :: num_handles = 0
   integer :: handle_ds(max_handles) = -1
   logical :: handle_open(max_handles) = .false.

   public :: pio_inq_varid, pio_inq_dimid, pio_inq_dimlen
   public :: pio_inquire_variable, pio_inq_vardimid
   public :: pio_get_var, pio_get_att, pio_put_att
   public :: pio_def_dim, pio_def_var, pio_put_var
   public :: pio_seterrorhandling, pio_closefile
   public :: harness_register_datafile, harness_open_dataset
   public :: harness_dataset_name, harness_dataset_index
   public :: harness_dataset_ntimes, harness_handle_open

   interface pio_inq_varid
      module procedure inq_varid_desc
      module procedure inq_varid_int
   end interface pio_inq_varid

   interface pio_get_var
      module procedure gv_int1d_desc
      module procedure gv_int1d_int
      module procedure gv_real0d_desc
      module procedure gv_real1d_desc
      module procedure gv_real1d_int
      module procedure gv_real2d_slab_desc
      module procedure gv_real3d_slab_desc
      module procedure gv_char_desc
   end interface pio_get_var

   interface pio_get_att
      module procedure ga_char_desc
      module procedure ga_real_desc
      module procedure ga_int_desc
   end interface pio_get_att

   interface pio_put_att
      module procedure pa_real_desc
      module procedure pa_int_desc
   end interface pio_put_att

contains

   ! ------------------------------------------------------------------
   ! Harness hooks (driver and sibling stubs)
   ! ------------------------------------------------------------------

   subroutine harness_register_datafile(fname, dates, datesecs)
      use cam_abortutils, only: endrun
      character(len=*), intent(in) :: fname
      integer,          intent(in) :: dates(:)
      integer,          intent(in) :: datesecs(:)
      if (num_ds >= max_ds) call endrun('pio stub: too many datasets')
      if (size(dates) > max_times) call endrun('pio stub: too many times')
      num_ds = num_ds + 1
      ds_name(num_ds) = trim(fname)
      ds_nt(num_ds) = size(dates)
      ds_dates(1:size(dates), num_ds) = dates
      ds_secs(1:size(dates), num_ds) = datesecs
   end subroutine harness_register_datafile

   function harness_open_dataset(fname) result(fh)
      character(len=*), intent(in) :: fname
      integer :: fh
      integer :: ids
      fh = -1
      do ids = 1, num_ds
         if (trim(ds_name(ids)) == trim(fname)) then
            num_handles = num_handles + 1
            fh = num_handles
            handle_ds(fh) = ids
            handle_open(fh) = .true.
            return
         end if
      end do
   end function harness_open_dataset

   function harness_dataset_name(fh) result(fname)
      integer, intent(in) :: fh
      character(len=256) :: fname
      if (fh >= 1 .and. fh <= num_handles) then
         fname = ds_name(handle_ds(fh))
      else
         fname = '<unknown-file>'
      end if
   end function harness_dataset_name

   function harness_dataset_index(fh) result(ids)
      integer, intent(in) :: fh
      integer :: ids
      ids = -1
      if (fh >= 1 .and. fh <= num_handles) ids = handle_ds(fh)
   end function harness_dataset_index

   function harness_dataset_ntimes(fh) result(ntimes)
      integer, intent(in) :: fh
      integer :: ntimes
      ntimes = 0
      if (fh >= 1 .and. fh <= num_handles) ntimes = ds_nt(handle_ds(fh))
   end function harness_dataset_ntimes

   function harness_handle_open(fh) result(is_open)
      integer, intent(in) :: fh
      logical :: is_open
      is_open = .false.
      if (fh >= 1 .and. fh <= num_handles) is_open = handle_open(fh)
   end function harness_handle_open

   ! ------------------------------------------------------------------
   ! Inquiry
   ! ------------------------------------------------------------------

   integer function name_code(vname) result(code)
      character(len=*), intent(in) :: vname
      select case (trim(vname))
      case ('date')
         code = VAR_DATE
      case ('datesec')
         code = VAR_DATESEC
      case (harness_field_name)
         code = VAR_FIELD
      case default
         code = -1
      end select
   end function name_code

   integer function inq_varid_desc(fid, vname, vdesc) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      character(len=*),  intent(in)  :: vname
      type(var_desc_t),  intent(out) :: vdesc
      vdesc%fh = fid%fh
      vdesc%code = name_code(vname)
      ierr = merge(PIO_NOERR, PIO_ERR, vdesc%code > 0)
   end function inq_varid_desc

   integer function inq_varid_int(fid, vname, vid) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      character(len=*),  intent(in)  :: vname
      integer,           intent(out) :: vid
      vid = name_code(vname)
      ierr = merge(PIO_NOERR, PIO_ERR, vid > 0)
   end function inq_varid_int

   integer function pio_inq_dimid(fid, dname, dimid) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      character(len=*),  intent(in)  :: dname
      integer,           intent(out) :: dimid
      select case (trim(dname))
      case ('ncol')
         dimid = DIM_NCOL
         ierr = PIO_NOERR
      case ('time')
         dimid = DIM_TIME
         ierr = PIO_NOERR
      case default
         dimid = -1
         ierr = PIO_ERR
      end select
   end function pio_inq_dimid

   integer function pio_inq_dimlen(fid, dimid, dlen) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      integer,           intent(in)  :: dimid
      integer,           intent(out) :: dlen
      ierr = PIO_NOERR
      select case (dimid)
      case (DIM_NCOL)
         dlen = 4
      case (DIM_TIME)
         dlen = harness_dataset_ntimes(fid%fh)
      case default
         dlen = 0
         ierr = PIO_ERR
      end select
   end function pio_inq_dimlen

   integer function pio_inquire_variable(fid, vdesc, ndims, dimids) result(ierr)
      type(file_desc_t), intent(in)            :: fid
      type(var_desc_t),  intent(in)            :: vdesc
      integer,           intent(out), optional :: ndims
      integer,           intent(out), optional :: dimids(:)
      if (present(ndims)) ndims = 1
      if (present(dimids)) dimids = -1
      ierr = PIO_NOERR
   end function pio_inquire_variable

   integer function pio_inq_vardimid(fid, vdesc, dimids) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      integer,           intent(out) :: dimids(:)
      dimids = -1
      ierr = PIO_NOERR
   end function pio_inq_vardimid

   ! ------------------------------------------------------------------
   ! Reads
   ! ------------------------------------------------------------------

   integer function serve_int1d(fh, code, ival) result(ierr)
      integer, intent(in)  :: fh
      integer, intent(in)  :: code
      integer, intent(out) :: ival(:)
      integer :: ids, nt
      ival = 0
      ierr = PIO_ERR
      ids = harness_dataset_index(fh)
      if (ids < 0) return
      nt = min(size(ival), ds_nt(ids))
      select case (code)
      case (VAR_DATE)
         ival(1:nt) = ds_dates(1:nt, ids)
         ierr = PIO_NOERR
      case (VAR_DATESEC)
         ival(1:nt) = ds_secs(1:nt, ids)
         ierr = PIO_NOERR
      end select
   end function serve_int1d

   integer function gv_int1d_desc(fid, vdesc, ival) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      integer,           intent(out) :: ival(:)
      ierr = serve_int1d(fid%fh, vdesc%code, ival)
   end function gv_int1d_desc

   integer function gv_int1d_int(fid, vid, ival) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      integer,           intent(in)  :: vid
      integer,           intent(out) :: ival(:)
      ierr = serve_int1d(fid%fh, vid, ival)
   end function gv_int1d_int

   integer function gv_real0d_desc(fid, vdesc, rval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      real(r8),          intent(out) :: rval
      rval = 0.0_r8
      ierr = PIO_ERR
   end function gv_real0d_desc

   integer function gv_real1d_desc(fid, vdesc, rval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      real(r8),          intent(out) :: rval(:)
      rval = 0.0_r8
      ierr = PIO_ERR
   end function gv_real1d_desc

   integer function gv_real1d_int(fid, vid, rval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      integer,           intent(in)  :: vid
      real(r8),          intent(out) :: rval(:)
      rval = 0.0_r8
      ierr = PIO_ERR
   end function gv_real1d_int

   integer function gv_real2d_slab_desc(fid, vdesc, strt, cnt, rval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      integer,           intent(in)  :: strt(:)
      integer,           intent(in)  :: cnt(:)
      real(r8),          intent(out) :: rval(:, :)
      rval = 0.0_r8
      ierr = PIO_ERR
   end function gv_real2d_slab_desc

   integer function gv_real3d_slab_desc(fid, vdesc, strt, cnt, rval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      integer,           intent(in)  :: strt(:)
      integer,           intent(in)  :: cnt(:)
      real(r8),          intent(out) :: rval(:, :, :)
      rval = 0.0_r8
      ierr = PIO_ERR
   end function gv_real3d_slab_desc

   ! ------------------------------------------------------------------
   ! Attributes and restart define/put (compile-only)
   ! ------------------------------------------------------------------

   integer function ga_char_desc(fid, vdesc, aname, aval) result(ierr)
      type(file_desc_t), intent(in)    :: fid
      type(var_desc_t),  intent(in)    :: vdesc
      character(len=*),  intent(in)    :: aname
      character(len=*),  intent(inout) :: aval
      ierr = PIO_ERR
   end function ga_char_desc

   integer function ga_real_desc(fid, vdesc, aname, aval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      character(len=*),  intent(in)  :: aname
      real(r8),          intent(out) :: aval
      aval = 0.0_r8
      ierr = PIO_ERR
   end function ga_real_desc

   integer function ga_int_desc(fid, vdesc, aname, aval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      character(len=*),  intent(in)  :: aname
      integer,           intent(out) :: aval
      aval = 0
      ierr = PIO_ERR
   end function ga_int_desc

   integer function gv_char_desc(fid, vdesc, cval) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      type(var_desc_t),  intent(in)  :: vdesc
      character(len=*),  intent(out) :: cval
      cval = ''
      ierr = PIO_ERR
   end function gv_char_desc

   integer function pa_real_desc(fid, vdesc, aname, aval) result(ierr)
      type(file_desc_t), intent(in) :: fid
      type(var_desc_t),  intent(in) :: vdesc
      character(len=*),  intent(in) :: aname
      real(r8),          intent(in) :: aval
      ierr = PIO_NOERR
   end function pa_real_desc

   integer function pa_int_desc(fid, vdesc, aname, aval) result(ierr)
      type(file_desc_t), intent(in) :: fid
      type(var_desc_t),  intent(in) :: vdesc
      character(len=*),  intent(in) :: aname
      integer,           intent(in) :: aval
      ierr = PIO_NOERR
   end function pa_int_desc

   integer function pio_def_dim(fid, dname, dlen, dimid) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      character(len=*),  intent(in)  :: dname
      integer,           intent(in)  :: dlen
      integer,           intent(out) :: dimid
      dimid = -1
      ierr = PIO_NOERR
   end function pio_def_dim

   integer function pio_def_var(fid, vname, vtype, dimids, vdesc) result(ierr)
      type(file_desc_t), intent(in)  :: fid
      character(len=*),  intent(in)  :: vname
      integer,           intent(in)  :: vtype
      integer,           intent(in)  :: dimids(:)
      type(var_desc_t),  intent(out) :: vdesc
      vdesc = var_desc_t()
      ierr = PIO_NOERR
   end function pio_def_var

   integer function pio_put_var(fid, vdesc, cval) result(ierr)
      type(file_desc_t), intent(in) :: fid
      type(var_desc_t),  intent(in) :: vdesc
      character(len=*),  intent(in) :: cval
      ierr = PIO_NOERR
   end function pio_put_var

   ! ------------------------------------------------------------------
   ! Control
   ! ------------------------------------------------------------------

   subroutine pio_seterrorhandling(fid, method, oldmethod)
      type(file_desc_t), intent(in)            :: fid
      integer,           intent(in)            :: method
      integer,           intent(out), optional :: oldmethod
      if (present(oldmethod)) oldmethod = PIO_INTERNAL_ERROR
   end subroutine pio_seterrorhandling

   subroutine pio_closefile(fid)
      use harness_events, only: ev_emit
      type(file_desc_t), intent(inout) :: fid
      if (fid%fh >= 1 .and. fid%fh <= num_handles) then
         handle_open(fid%fh) = .false.
         call ev_emit('closefile|'//trim(harness_dataset_name(fid%fh)))
      else
         call ev_emit('closefile|<unknown-file>')
      end if
   end subroutine pio_closefile

end module pio

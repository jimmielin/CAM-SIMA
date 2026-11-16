! Harness stub: one unstructured grid ("ncol" columns), serial decomposition.
! cam_grid_write_dist_array is the field-data sink, so it emits the
! writefield events the comparator checks values against.
module cam_grid_support
   use shr_kind_mod, only: r8 => shr_kind_r8, r4 => shr_kind_r4
   use pio,          only: file_desc_t, var_desc_t
   implicit none
   private

   public :: cam_grid_header_info_t
   public :: cam_grid_num_grids, cam_grid_write_attr, cam_grid_write_var
   public :: cam_grid_write_dist_array
   public :: cam_grid_get_array_bounds, cam_grid_dimensions
   public :: max_hcoordname_len, max_split_files
   public :: harness_ncol

   integer, parameter :: max_hcoordname_len = 16
   integer, parameter :: max_split_files = 2
   integer, parameter :: harness_ncol = 4

   type :: cam_grid_header_info_t
      integer :: grid_id = -1
      integer :: hdimids(1) = -1
   contains
      procedure :: num_hdims => hi_num_hdims
      procedure :: get_hdimid => hi_get_hdimid
      procedure :: get_gridid => hi_get_gridid
      procedure :: deallocate => hi_deallocate
   end type cam_grid_header_info_t

   interface cam_grid_write_dist_array
      module procedure write_dist_1d_r8, write_dist_2d_r8, write_dist_3d_r8
      module procedure write_dist_1d_r4, write_dist_2d_r4, write_dist_3d_r4
      module procedure write_dist_1d_int, write_dist_2d_int
   end interface cam_grid_write_dist_array

contains

   integer function cam_grid_num_grids()
      cam_grid_num_grids = 1
   end function cam_grid_num_grids

   integer function hi_num_hdims(this)
      class(cam_grid_header_info_t), intent(in) :: this
      hi_num_hdims = 1
   end function hi_num_hdims

   integer function hi_get_hdimid(this, index)
      class(cam_grid_header_info_t), intent(in) :: this
      integer,                       intent(in) :: index
      hi_get_hdimid = this%hdimids(1)
   end function hi_get_hdimid

   integer function hi_get_gridid(this)
      class(cam_grid_header_info_t), intent(in) :: this
      hi_get_gridid = this%grid_id
   end function hi_get_gridid

   subroutine hi_deallocate(this)
      class(cam_grid_header_info_t), intent(inout) :: this
      this%grid_id = -1
      this%hdimids = -1
   end subroutine hi_deallocate

   subroutine cam_grid_write_attr(file, grid_id, header_info, file_index)
      use cam_pio_utils, only: cam_pio_def_dim
      type(file_desc_t),             intent(inout) :: file
      integer,                       intent(in)    :: grid_id
      type(cam_grid_header_info_t),  intent(inout) :: header_info
      integer, optional,             intent(in)    :: file_index
      integer :: dimid
      call cam_pio_def_dim(file, 'ncol', harness_ncol, dimid)
      header_info%grid_id = grid_id
      header_info%hdimids(1) = dimid
   end subroutine cam_grid_write_attr

   subroutine cam_grid_write_var(file, grid_id, file_index)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: grid_id
      integer, optional, intent(in)    :: file_index
      ! Coordinate variable values are not part of the checked protocol
   end subroutine cam_grid_write_var

   subroutine cam_grid_get_array_bounds(grid_id, bounds)
      integer, intent(in)  :: grid_id
      integer, intent(out) :: bounds(2, 2)
      bounds(1, 1) = 1
      bounds(1, 2) = harness_ncol
      bounds(2, 1) = 1
      bounds(2, 2) = 1
   end subroutine cam_grid_get_array_bounds

   subroutine cam_grid_dimensions(grid_id, dims, rank)
      integer,           intent(in)  :: grid_id
      integer,           intent(out) :: dims(2)
      integer, optional, intent(out) :: rank
      dims(1) = harness_ncol
      dims(2) = 1
      if (present(rank)) rank = 1
   end subroutine cam_grid_dimensions

   subroutine emit_field(file, varid, values)
      use harness_events, only: ev_writevalues
      type(file_desc_t), intent(in) :: file
      type(var_desc_t),  intent(in) :: varid
      real(r8),          intent(in) :: values(:)
      call ev_writevalues(file%fh, trim(varid%name), varid%frame, values)
   end subroutine emit_field

   subroutine write_dist_1d_r8(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      real(r8),          intent(in)    :: buf(:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, buf)
   end subroutine write_dist_1d_r8

   subroutine write_dist_2d_r8(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      real(r8),          intent(in)    :: buf(:,:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, reshape(buf, [size(buf)]))
   end subroutine write_dist_2d_r8

   subroutine write_dist_3d_r8(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      real(r8),          intent(in)    :: buf(:,:,:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, reshape(buf, [size(buf)]))
   end subroutine write_dist_3d_r8

   subroutine write_dist_1d_r4(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      real(r4),          intent(in)    :: buf(:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, real(buf, r8))
   end subroutine write_dist_1d_r4

   subroutine write_dist_2d_r4(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      real(r4),          intent(in)    :: buf(:,:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, real(reshape(buf, [size(buf)]), r8))
   end subroutine write_dist_2d_r4

   subroutine write_dist_3d_r4(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      real(r4),          intent(in)    :: buf(:,:,:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, real(reshape(buf, [size(buf)]), r8))
   end subroutine write_dist_3d_r4

   subroutine write_dist_1d_int(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      integer,           intent(in)    :: buf(:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, real(buf, r8))
   end subroutine write_dist_1d_int

   subroutine write_dist_2d_int(file, decomp, adims, fdims, buf, varid)
      type(file_desc_t), intent(inout) :: file
      integer,           intent(in)    :: decomp
      integer,           intent(in)    :: adims(:), fdims(:)
      integer,           intent(in)    :: buf(:,:)
      type(var_desc_t),  intent(in)    :: varid
      call emit_field(file, varid, real(reshape(buf, [size(buf)]), r8))
   end subroutine write_dist_2d_int

end module cam_grid_support

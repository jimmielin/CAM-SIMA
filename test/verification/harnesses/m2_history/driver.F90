! M2 differential-harness driver: reads a scenario op script on stdin and
! drives a real hist_file_t volume through it, with recording stubs standing
! in for PIO, the grid layer and the time manager.  Observable actions come
! out as EV| lines on stdout for the Python comparator.
!
! The write op replays the per-volume slice of history_write_files
! (cam_history.F90:209-241) and the wrap-up close (cam_history.F90:865-879):
! on a frame boundary allocate filenames and define the files, then write
! the time sample, then close when the file set is full.  The volume's own
! protocol (routing, buffers, filenames) is entirely the real code's.
!
! Op script grammar (one op per line, '#' comments):
!   dtime <seconds>
!   nstep <n>
!   volume <name> <max_frames> <freq> <write_nstep0 T|F> <filename_spec>
!   field <name> <inst|avg|min|max|var> <xyfill T|F>
!   setup
!   sample <field> <value>
!   write
program m2_driver
   use, intrinsic :: iso_fortran_env, only: input_unit, error_unit, real64
   use shr_kind_mod,        only: r8 => shr_kind_r8, cl => shr_kind_cl
   use cam_hist_file,       only: hist_file_t
   use cam_history_support, only: fillvalue, max_fldlen => max_fieldname_len
   use cam_grid_support,    only: harness_ncol
   use hist_api,            only: hist_new_field, hist_field_accumulate
   use hist_field,          only: hist_field_info_t
   use hist_hash_table,     only: hist_hash_table_t
   use hist_msg_handler,    only: hist_log_messages
   use time_manager,        only: tm_harness_set, get_curr_time
   use cam_abortutils,      only: endrun
   use harness_events,      only: ev_emit
   implicit none

   integer, parameter :: max_fields = 16

   type(hist_file_t)       :: vol
   type(hist_hash_table_t) :: possible_field_list

   character(len=cl) :: line, tok
   character(len=cl) :: vol_name, vol_freq, vol_spec
   integer           :: vol_max_frames
   logical           :: vol_nstep0

   character(len=max_fldlen) :: fld_names(max_fields)
   character(len=8)          :: fld_lists(max_fields)
   logical                   :: fld_xyfill(max_fields)
   integer                   :: num_fields = 0

   integer :: dtime = 1800
   integer :: nstep = 0
   integer :: pos, ios, idx
   real(r8) :: rval

   do
      read(input_unit, '(a)', iostat=ios) line
      if (ios /= 0) exit
      if (len_trim(line) == 0) cycle
      if (line(1:1) == '#') cycle
      call ev_emit('op|'//trim(line))
      pos = 1
      call next_token(line, pos, tok)
      select case (trim(tok))
      case ('dtime')
         call next_token(line, pos, tok)
         read(tok, *) dtime
         call tm_harness_set(dtime, nstep)
      case ('nstep')
         call next_token(line, pos, tok)
         read(tok, *) nstep
         call tm_harness_set(dtime, nstep)
      case ('volume')
         call next_token(line, pos, vol_name)
         call next_token(line, pos, tok)
         read(tok, *) vol_max_frames
         call next_token(line, pos, vol_freq)
         call next_token(line, pos, tok)
         vol_nstep0 = (trim(tok) == 'T')
         call next_token(line, pos, vol_spec)
      case ('field')
         num_fields = num_fields + 1
         call next_token(line, pos, fld_names(num_fields))
         call next_token(line, pos, fld_lists(num_fields))
         call next_token(line, pos, tok)
         fld_xyfill(num_fields) = (trim(tok) == 'T')
      case ('setup')
         call do_setup()
      case ('sample')
         call next_token(line, pos, tok)
         idx = field_index(tok)
         call next_token(line, pos, tok)
         read(tok, *) rval
         call do_sample(fld_names(idx), rval)
      case ('write')
         call do_write()
      case default
         call endrun('m2_driver: unknown op '//trim(tok))
      end select
   end do

contains

   subroutine next_token(str, cursor, token)
      character(len=*), intent(in)    :: str
      integer,          intent(inout) :: cursor
      character(len=*), intent(out)   :: token
      integer :: istart
      do while (cursor <= len_trim(str))
         if (str(cursor:cursor) /= ' ') exit
         cursor = cursor + 1
      end do
      istart = cursor
      do while (cursor <= len_trim(str))
         if (str(cursor:cursor) == ' ') exit
         cursor = cursor + 1
      end do
      token = str(istart:cursor-1)
   end subroutine next_token

   integer function field_index(fname)
      character(len=*), intent(in) :: fname
      integer :: fidx
      field_index = -1
      do fidx = 1, num_fields
         if (trim(fld_names(fidx)) == trim(fname)) then
            field_index = fidx
            return
         end if
      end do
      call endrun('m2_driver: unregistered field '//trim(fname))
   end function field_index

   subroutine collect_list(list_name, members, count)
      character(len=*), intent(in)  :: list_name
      character(len=max_fldlen), intent(out) :: members(max_fields)
      integer,          intent(out) :: count
      integer :: fidx
      count = 0
      do fidx = 1, num_fields
         if (trim(fld_lists(fidx)) == trim(list_name)) then
            count = count + 1
            members(count) = fld_names(fidx)
         end if
      end do
   end subroutine collect_list

   subroutine do_setup()
      ! Mirrors the init sequence: register the possible fields
      ! (cam_history.F90 history_add_field_nd), configure the volume from
      ! its namelist-equivalent settings, then commit with set_up_fields.
      class(hist_field_info_t), pointer :: fptr
      character(len=max_fldlen) :: inst_f(max_fields), avg_f(max_fields)
      character(len=max_fldlen) :: min_f(max_fields), max_f(max_fields)
      character(len=max_fldlen) :: var_f(max_fields)
      integer :: n_inst, n_avg, n_min, n_max, n_var
      integer :: fidx, day, sec
      integer :: no_mdims(0)
      integer :: dimbounds(2, 2)

      dimbounds(1, 1) = 1
      dimbounds(1, 2) = harness_ncol
      dimbounds(2, 1) = 1
      dimbounds(2, 2) = 1

      call possible_field_list%initialize(max(num_fields, 2))
      do fidx = 1, num_fields
         fptr => hist_new_field(trim(fld_names(fidx)),                        &
              'std_'//trim(fld_names(fidx)), 'std_'//trim(fld_names(fidx)),   &
              'kg kg-1', 'real', 1, no_mdims, 'avg', 1, [harness_ncol],       &
              fillvalue, mixing_ratio='', dim_bounds=dimbounds,               &
              mdim_sizes=no_mdims, cell_methods='',                           &
              flag_xyfill=fld_xyfill(fidx), sampled_on_subcycle=.false.)
         call possible_field_list%add_hash_key(fptr)
      end do

      call collect_list('inst', inst_f, n_inst)
      call collect_list('avg', avg_f, n_avg)
      call collect_list('min', min_f, n_min)
      call collect_list('max', max_f, n_max)
      call collect_list('var', var_f, n_var)

      call vol%configure(trim(vol_name), real64, vol_max_frames,              &
           trim(vol_freq), 1, trim(vol_spec), .false.,                        &
           inst_f(1:n_inst), avg_f(1:n_avg), min_f(1:n_min),                  &
           max_f(1:n_max), var_f(1:n_var), vol_nstep0)

      call get_curr_time(day, sec)
      call vol%set_beg_time(day, sec)
      call vol%set_up_fields(possible_field_list)
   end subroutine do_setup

   subroutine do_sample(fname, val)
      ! Mirrors history_out_field_1d: look the field up on the volume and
      ! accumulate one sample across all columns.
      character(len=*), intent(in) :: fname
      real(r8),         intent(in) :: val
      class(hist_field_info_t), pointer :: field_info
      type(hist_log_messages) :: logger
      character(len=cl) :: errmsg
      real(r8) :: vals(harness_ncol)
      errmsg = ''
      call vol%find_in_field_list(trim(fname), field_info, errmsg)
      if (len_trim(errmsg) /= 0) then
         call endrun('m2_driver sample: '//trim(errmsg))
      end if
      if (.not. associated(field_info)) then
         ! Field not active on this volume: production silently skips
         return
      end if
      vals = val
      call hist_field_accumulate(field_info, vals, 1, logger=logger)
      call logger%output(error_unit)
      if (logger%num_errors() > 0) then
         call endrun('m2_driver sample: accumulate error for '//trim(fname))
      end if
   end subroutine do_sample

   subroutine do_write()
      integer :: ns
      ns = vol%get_num_samples()
      if (mod(ns, vol%max_frame()) == 0) then
         call vol%set_filenames()
         call vol%define_file('harness', 'localhost', '')
      end if
      call vol%write_time_dependent_variables()
      ns = vol%get_num_samples()
      if (mod(ns, vol%max_frame()) == 0 .and. ns > 0 .and.                    &
           vol%are_files_open()) then
         call vol%close_files()
      end if
   end subroutine do_write

end program m2_driver

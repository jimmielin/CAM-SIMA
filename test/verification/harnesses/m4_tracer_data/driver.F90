! M4 differential-harness driver: reads a scenario op script on stdin and
! drives the real tracer_data machine through it, with recording stubs
! standing in for PIO, the file readers and the time manager. Observable
! actions come out as EV| lines on stdout for the Python comparator.
!
! The scenarios register fake datasets (name + date coordinates), set the
! calendar and clock, run trcdata_init once, and call advance_trcdata the
! way a host-model run loop would -- the bracketing machine (find_times,
! check_files, incr_filename, advance_file, set_cycle_indices, the fill
! path, the weight computation) is entirely the real code's.
!
! Op script grammar (one op per line, '#' comments):
!   dtime <seconds>
!   calendar <NO_LEAP|GREGORIAN>
!   datafile <name> <yyyymmdd> [<yyyymmdd> ...]
!   date <yr> <mon> <day> <sec>
!   init <filename> <filelist|-> <datapath|-> <data_type> <cyc_yr> <fixed_ymd> <fixed_tod>
!   advance
program m4_driver
   use, intrinsic :: iso_fortran_env, only: input_unit
   use shr_kind_mod,   only: r8 => shr_kind_r8, cl => shr_kind_cl
   use ccpp_kinds,     only: kind_phys
   use vert_coord,     only: pver, pverp
   use physics_grid,   only: pcols => columns_on_task
   use pio,            only: harness_register_datafile
   use time_manager,   only: tm_set_date, tm_set_step, tm_set_calendar
   use tracer_data,    only: trfld, trfile, trcdata_init, advance_trcdata
   use cam_abortutils, only: endrun
   use harness_events, only: ev_emit, ev_fmt_r8
   implicit none

   integer, parameter :: max_dates = 64

   type(trfile)         :: tr_file
   type(trfld), pointer :: flds(:) => null()
   character(len=32)    :: specifier(1)

   character(len=2048) :: line
   character(len=cl)   :: tok
   character(len=cl)   :: fname, filelist, datapath, data_type
   integer :: dates(max_dates), datesecs(max_dates)
   integer :: cyc_yr, fixed_ymd, fixed_tod
   integer :: yr, mon, day, sec, dtime
   integer :: pos, ios, ndates
   logical :: initialized

   real(kind_phys) :: pmid(pcols, pver), pint(pcols, pverp)
   real(kind_phys) :: phis(pcols), zi(pcols, pverp)

   specifier(1) = 'TESTFLD'
   initialized = .false.
   ! Benign state inputs: surface fields never consult them
   pmid(:, 1) = 500.0e2_kind_phys
   pmid(:, 2) = 900.0e2_kind_phys
   pint(:, 1) = 100.0e2_kind_phys
   pint(:, 2) = 700.0e2_kind_phys
   pint(:, 3) = 1000.0e2_kind_phys
   phis(:) = 0.0_kind_phys
   zi(:, 1) = 100.0_kind_phys
   zi(:, 2) = 50.0_kind_phys
   zi(:, 3) = 0.0_kind_phys

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
         call tm_set_step(dtime)
      case ('calendar')
         call next_token(line, pos, tok)
         call tm_set_calendar(trim(tok))
      case ('datafile')
         call next_token(line, pos, fname)
         ndates = 0
         do
            call next_token(line, pos, tok)
            if (len_trim(tok) == 0) exit
            if (ndates >= max_dates) call endrun('m4_driver: too many dates')
            ndates = ndates + 1
            read(tok, *) dates(ndates)
         end do
         if (ndates == 0) call endrun('m4_driver: datafile without dates')
         datesecs(1:ndates) = 0
         call harness_register_datafile(trim(fname), dates(1:ndates), &
              datesecs(1:ndates))
      case ('date')
         call next_token(line, pos, tok)
         read(tok, *) yr
         call next_token(line, pos, tok)
         read(tok, *) mon
         call next_token(line, pos, tok)
         read(tok, *) day
         call next_token(line, pos, tok)
         read(tok, *) sec
         call tm_set_date(yr, mon, day, sec)
      case ('init')
         call next_token(line, pos, fname)
         call next_token(line, pos, filelist)
         if (trim(filelist) == '-') filelist = ''
         call next_token(line, pos, datapath)
         if (trim(datapath) == '-') datapath = ''
         call next_token(line, pos, data_type)
         call next_token(line, pos, tok)
         read(tok, *) cyc_yr
         call next_token(line, pos, tok)
         read(tok, *) fixed_ymd
         call next_token(line, pos, tok)
         read(tok, *) fixed_tod
         call trcdata_init(specifier, trim(fname), trim(filelist), &
              trim(datapath), flds, tr_file, cyc_yr, fixed_ymd, fixed_tod, &
              trim(data_type))
         initialized = .true.
         call ev_emit('init_done')
      case ('advance')
         if (.not. initialized) call endrun('m4_driver: advance before init')
         call advance_trcdata(flds, tr_file, pmid, pint, phis, zi)
         call emit_advance_state()
      case default
         call endrun('m4_driver: unknown op '//trim(tok))
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

   function name_or_dash(name) result(out)
      character(len=*), intent(in) :: name
      character(len=cl) :: out
      if (len_trim(name) == 0) then
         out = '-'
      else
         out = trim(name)
      end if
   end function name_or_dash

   subroutine emit_advance_state()
      character(len=2048) :: evline
      character(len=16)   :: irecs
      integer :: i
      write(irecs, '(i0)') tr_file%interp_recs
      evline = 'state|'//trim(ev_fmt_r8(tr_file%curr_mod_time))// &
           '|'//trim(ev_fmt_r8(tr_file%datatimem))// &
           '|'//trim(ev_fmt_r8(tr_file%datatimep))// &
           '|'//trim(irecs)// &
           '|'//trim(name_or_dash(tr_file%curr_filename))// &
           '|'//trim(name_or_dash(tr_file%next_filename))
      call ev_emit(evline)
      evline = 'datatimes'
      do i = 1, 4
         evline = trim(evline)//'|'//trim(ev_fmt_r8(tr_file%datatimes(i)))
      end do
      call ev_emit(evline)
      call ev_emit('data|'//trim(ev_fmt_r8(flds(1)%data(1, 1))))
      call ev_emit('advance_done')
   end subroutine emit_advance_state

end program m4_driver

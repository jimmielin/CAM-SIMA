module ledger_host_prog_v0
  ! Assumption-ledger driver against the capgen-v0 host-cap API
  ! (<host>_ccpp_physics_* entry points, positional error arguments).
  ! Mirrors CAM-SIMA's physics driver choreography: register phase,
  ! constituent registration/initialization, init, then per step
  ! timestep_init -> run(part...) -> timestep_final, and final; any
  ! nonzero errflg aborts the remainder, as cam_comp does.
  !
  ! Command line: [nsteps] [fail_b_at_step]

  use ccpp_kinds, only: kind_phys
  use ccpp_constituent_prop_mod, only: ccpp_constituent_properties_t
  use ccpp_constituent_prop_mod, only: ccpp_constituent_prop_ptr_t
  use ledger_host_mod, only: ncols, pver, num_tracked, tracked_stdnames
  use ledger_host_mod, only: ledger_host_init_fields, ledger_host_set_step
  use ledger_events, only: ev_host, ev_text, ev_idx, ev_constmeta, ev_val
  use ldg_order_b, only: ldg_order_b_fail_at
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_physics_register
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_register_constituents
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_number_constituents
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_initialize_constituents
  use ledger_host_ccpp_cap, only: ledger_host_constituents_array
  use ledger_host_ccpp_cap, only: ledger_host_const_get_index
  use ledger_host_ccpp_cap, only: ledger_host_model_const_properties
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_physics_initialize
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_physics_timestep_initial
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_physics_run
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_physics_timestep_final
  use ledger_host_ccpp_cap, only: ledger_host_ccpp_physics_finalize
  use ledger_host_ccpp_cap, only: ccpp_physics_suite_part_list

  implicit none
  private
  public :: ledger_host

contains

  !> \section arg_table_ledger_host  Argument Table
  !! \htmlinclude arg_table_ledger_host.html
  subroutine ledger_host()

  character(len=*), parameter :: suite_name = 'ledger'
  type(ccpp_constituent_properties_t), allocatable, target :: host_consts(:)
  type(ccpp_constituent_prop_ptr_t), pointer :: const_props(:)
  real(kind=kind_phys), pointer :: const_ptr(:, :, :)
  character(len=128), allocatable :: part_names(:)
  character(len=512) :: errmsg
  character(len=64)  :: const_str
  character(len=256) :: argbuf
  integer :: errflg
  integer :: nsteps
  integer :: step
  integer :: ip
  integer :: j
  integer :: idx
  integer :: nconst
  logical :: aborted
  character(len=32) :: mode
  integer :: col_start
  integer :: col_end

  col_start = 1
  col_end = ncols
  nsteps = 3
  aborted = .false.
  call get_command_argument(1, argbuf)
  if (len_trim(argbuf) > 0) then
    read(argbuf, *) nsteps
  end if
  call get_command_argument(2, argbuf)
  if (len_trim(argbuf) > 0) then
    read(argbuf, *) ldg_order_b_fail_at
  end if
  mode = ''
  call get_command_argument(3, mode)

  errmsg = ''
  errflg = 0
  call ledger_host_init_fields()
  call ev_text('begin', 'api=v0')

  ! Register phase.
  call ledger_host_ccpp_physics_register(suite_name, errmsg, errflg)
  call ev_host('register', errflg, errmsg)
  if (errflg /= 0) stop 1

  ! Host-registered constituents (wet first, then dry).
  allocate(host_consts(2))
  call host_consts(1)%instantiate(std_name='ldg_host_wet_mixing_ratio', &
       long_name='Ledger host wet constituent', diag_name='LDGWET', &
       units='kg kg-1', vertical_dim='vertical_layer_dimension', &
       advected=.true., errcode=errflg, errmsg=errmsg)
  if (errflg == 0) then
    call host_consts(2)%instantiate(std_name='ldg_host_dry_mixing_ratio', &
         long_name='Ledger host dry constituent', diag_name='LDGDRY', &
         units='kg kg-1', vertical_dim='vertical_layer_dimension', &
         advected=.true., errcode=errflg, errmsg=errmsg)
  end if
  call ev_host('instantiate', errflg, errmsg)
  if (errflg /= 0) stop 1
  call ledger_host_ccpp_register_constituents(host_consts, &
       errmsg=errmsg, errflg=errflg)
  call ev_host('register_constituents', errflg, errmsg)
  if (errflg /= 0) stop 1

  call ledger_host_ccpp_number_constituents(nconst, errmsg=errmsg, &
       errflg=errflg)
  call ev_host('number_constituents', errflg, errmsg)
  write(argbuf, '(i0)') nconst
  call ev_text('nconst', argbuf)

  call ledger_host_ccpp_initialize_constituents(ncols, pver, errflg, errmsg)
  call ev_host('initialize_constituents', errflg, errmsg)
  if (errflg /= 0) stop 1

  const_ptr => ledger_host_constituents_array()

  ! Host-side index lookups for the tracked constituents.
  do j = 1, num_tracked
    call ledger_host_const_get_index(trim(tracked_stdnames(j)), idx, &
         errflg, errmsg)
    call ev_idx('host', tracked_stdnames(j), idx)
    if (errflg /= 0) then
      call ev_host('const_get_index', errflg, errmsg)
      stop 1
    end if
  end do

  ! Host-side constituent order: standard name at every index.
  const_props => ledger_host_model_const_properties()
  do idx = 1, nconst
    call const_props(idx)%standard_name(const_str, errflg, errmsg)
    if (errflg /= 0) then
      call ev_host('const_properties', errflg, errmsg)
      stop 1
    end if
    call ev_constmeta(idx, const_str)
  end do

  ! Init phase.
  call ledger_host_ccpp_physics_initialize(suite_name, errmsg, errflg)
  call ev_host('init', errflg, errmsg)
  if (errflg /= 0) stop 1

  ! Phase-protocol probe: a run call before any timestep_init must be
  ! rejected by the generated cap's suite-state guard.
  if (trim(mode) == 'violate') then
    call ledger_host_ccpp_physics_run(suite_name, 'alpha', &
           col_start, col_end, errmsg, errflg)
    call ev_host('run_before_timestep_init', errflg, errmsg)
    call ev_text('end', 'violate')
    stop
  end if

  ! Run-phase group names, in suite order.
  call ccpp_physics_suite_part_list(suite_name, part_names, errmsg, errflg)
  argbuf = ''
  do ip = 1, size(part_names)
    if (ip > 1) argbuf = trim(argbuf) // ','
    argbuf = trim(argbuf) // trim(part_names(ip))
  end do
  call ev_text('parts', argbuf)

  ! Time loop.
  step_loop: do step = 1, nsteps
    call ledger_host_set_step(step)
    call ledger_host_ccpp_physics_timestep_initial(suite_name, errmsg, &
         errflg)
    call ev_host('timestep_init', errflg, errmsg)
    if (errflg /= 0) then
      aborted = .true.
      exit step_loop
    end if
    do ip = 1, size(part_names)
      call ledger_host_ccpp_physics_run(suite_name, &
           trim(part_names(ip)), col_start, col_end, errmsg, errflg)
      call ev_host('run:' // trim(part_names(ip)), errflg, errmsg)
      if (errflg /= 0) then
        aborted = .true.
        exit step_loop
      end if
    end do
    call ledger_host_ccpp_physics_timestep_final(suite_name, errmsg, errflg)
    call ev_host('timestep_final', errflg, errmsg)
    if (errflg /= 0) then
      aborted = .true.
      exit step_loop
    end if
  end do step_loop

  ! Read back the constituent markers through the host-side indices.
  if (.not. aborted) then
    do j = 1, num_tracked
      call ledger_host_const_get_index(trim(tracked_stdnames(j)), idx, &
           errflg, errmsg)
      if (errflg == 0 .and. idx > 0) then
        call ev_val('constval', tracked_stdnames(j), const_ptr(1, 1, idx))
      end if
    end do
    call ledger_host_ccpp_physics_finalize(suite_name, errmsg, errflg)
    call ev_host('final', errflg, errmsg)
  end if

  if (aborted) then
    call ev_text('end', 'aborted')
  else
    call ev_text('end', 'clean')
  end if

  end subroutine ledger_host

end module ledger_host_prog_v0

program ledger_main
  use ledger_host_prog_v0, only: ledger_host
  implicit none
  call ledger_host()
end program ledger_main

module ldg_const
  ! Ledger scheme for the constituent contract: registers a dynamic
  ! constituent, declares an auto-promoted (advected) one in metadata, and
  ! at run time writes a distinct marker value into each tracked
  ! constituent through the scheme-side index lookup.  The driver
  ! cross-checks the markers through the host-side index lookup.

  use ccpp_kinds, only: kind_phys

  implicit none
  private

  public :: ldg_const_register
  public :: ldg_const_init
  public :: ldg_const_run

contains

  !> \section arg_table_ldg_const_register  Argument Table
  !! \htmlinclude arg_table_ldg_const_register.html
  subroutine ldg_const_register(dyn_const, errmsg, errflg)
    use ccpp_constituent_prop_mod, only: ccpp_constituent_properties_t
    use ledger_events, only: ev_call

    type(ccpp_constituent_properties_t), allocatable, intent(out) :: &
         dyn_const(:)
    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_const', 'register', 0)
    allocate(dyn_const(1), stat=errflg)
    if (errflg /= 0) then
      errmsg = 'ldg_const_register: allocate failed'
      return
    end if
    call dyn_const(1)%instantiate(std_name='ldg_dyn_mixing_ratio', &
         long_name='Ledger dynamic constituent', diag_name='LDGDYN', &
         units='kg kg-1', vertical_dim='vertical_layer_dimension', &
         advected=.true., errcode=errflg, errmsg=errmsg)
  end subroutine ldg_const_register

  !> \section arg_table_ldg_const_init  Argument Table
  !! \htmlinclude arg_table_ldg_const_init.html
  subroutine ldg_const_init(errmsg, errflg)
    use ledger_events, only: ev_call

    character(len=512),   intent(out) :: errmsg
    integer,              intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_const', 'init', 0)
  end subroutine ldg_const_init

  !> \section arg_table_ldg_const_run  Argument Table
  !! \htmlinclude arg_table_ldg_const_run.html
  subroutine ldg_const_run(ncol, nstep, num_tracked, tracked_stdnames, &
       const_array, cloud, errmsg, errflg)
    use ccpp_scheme_utils, only: ccpp_constituent_index
    use ledger_events, only: ev_call, ev_idx

    integer,              intent(in)    :: ncol
    integer,              intent(in)    :: nstep
    integer,              intent(in)    :: num_tracked
    character(len=*),     intent(in)    :: tracked_stdnames(:)
    real(kind=kind_phys), intent(inout) :: const_array(:, :, :)
    real(kind=kind_phys), intent(inout) :: cloud(:, :)
    character(len=512),   intent(out)   :: errmsg
    integer,              intent(out)   :: errflg

    integer :: j
    integer :: idx

    errmsg = ''
    errflg = 0
    call ev_call('ldg_const', 'run', nstep)
    ! Write 1000*j + nstep through the full constituent array at the
    ! scheme-queried index for each tracked constituent.
    do j = 1, num_tracked
      call ccpp_constituent_index(trim(tracked_stdnames(j)), idx, &
           errflg, errmsg)
      call ev_idx('scheme', tracked_stdnames(j), idx)
      if (errflg /= 0) then
        return
      end if
      if (idx > 0) then
        const_array(:, :, idx) = real(1000 * j + nstep, kind_phys)
      end if
    end do
    ! Then add 0.5 through the promoted slice argument: the host sees
    ! 1000*3 + nstep + 0.5 at its own index for ldg_cloud_dry_mixing_ratio
    ! only if the slice and the array share storage.
    cloud(:, :) = cloud(:, :) + 0.5_kind_phys
  end subroutine ldg_const_run

end module ldg_const

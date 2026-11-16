module ldg_order_b
  ! Ledger scheme B: first scheme of group beta.  Consumes the marker
  ! field produced by ldg_order_a in group alpha, and carries the fault
  ! injection for the error-propagation assumption: when the driver arms
  ! fail_at, the run phase at that step reports errflg = 42.

  use ccpp_kinds, only: kind_phys

  implicit none
  private

  ! Fault injection control; fixture-internal, set by the driver, not
  ! part of any metadata.
  integer, public :: ldg_order_b_fail_at = -1

  public :: ldg_order_b_init
  public :: ldg_order_b_run
  public :: ldg_order_b_final

contains

  !> \section arg_table_ldg_order_b_init  Argument Table
  !! \htmlinclude arg_table_ldg_order_b_init.html
  subroutine ldg_order_b_init(errmsg, errflg)
    use ledger_events, only: ev_call

    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_b', 'init', 0)
  end subroutine ldg_order_b_init

  !> \section arg_table_ldg_order_b_run  Argument Table
  !! \htmlinclude arg_table_ldg_order_b_run.html
  subroutine ldg_order_b_run(ncol, nstep, marker, errmsg, errflg)
    use ledger_events, only: ev_call, ev_val

    integer,              intent(in)  :: ncol
    integer,              intent(in)  :: nstep
    real(kind=kind_phys), intent(in)  :: marker(:, :)
    character(len=512),   intent(out) :: errmsg
    integer,              intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_b', 'run', nstep)
    ! Prove the cross-group suite variable arrived with this step's value.
    call ev_val('b_run', 'marker11', marker(1, 1))
    if (nstep == ldg_order_b_fail_at) then
      errflg = 42
      write(errmsg, '(a,i0)') &
           'ldg_order_b deliberate failure at nstep=', nstep
    end if
  end subroutine ldg_order_b_run

  !> \section arg_table_ldg_order_b_final  Argument Table
  !! \htmlinclude arg_table_ldg_order_b_final.html
  subroutine ldg_order_b_final(errmsg, errflg)
    use ledger_events, only: ev_call

    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_b', 'final', -1)
  end subroutine ldg_order_b_final

end module ldg_order_b

module ldg_order_c
  ! Ledger scheme C: last scheme of group beta.  The canary for the
  ! error-propagation assumption: whether its run executes after
  ! ldg_order_b fails is the observable the ledger records.

  implicit none
  private

  public :: ldg_order_c_run

contains

  !> \section arg_table_ldg_order_c_run  Argument Table
  !! \htmlinclude arg_table_ldg_order_c_run.html
  subroutine ldg_order_c_run(nstep, errmsg, errflg)
    use ledger_events, only: ev_call

    integer,            intent(in)  :: nstep
    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_c', 'run', nstep)
  end subroutine ldg_order_c_run

end module ldg_order_c

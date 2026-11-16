module ldg_order_a
  ! Ledger scheme A: first scheme of group alpha.  Exercises every CCPP
  ! phase, reads a host-module field, and produces the suite-internal
  ! marker field consumed by ldg_order_b in group beta.

  use ccpp_kinds, only: kind_phys

  implicit none
  private

  public :: ldg_order_a_init
  public :: ldg_order_a_timestep_init
  public :: ldg_order_a_run
  public :: ldg_order_a_timestep_final
  public :: ldg_order_a_final

contains

  !> \section arg_table_ldg_order_a_init  Argument Table
  !! \htmlinclude arg_table_ldg_order_a_init.html
  subroutine ldg_order_a_init(errmsg, errflg)
    use ledger_events, only: ev_call

    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_a', 'init', 0)
  end subroutine ldg_order_a_init

  !> \section arg_table_ldg_order_a_timestep_init  Argument Table
  !! \htmlinclude arg_table_ldg_order_a_timestep_init.html
  subroutine ldg_order_a_timestep_init(nstep, errmsg, errflg)
    use ledger_events, only: ev_call

    integer,            intent(in)  :: nstep
    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_a', 'timestep_init', nstep)
  end subroutine ldg_order_a_timestep_init

  !> \section arg_table_ldg_order_a_run  Argument Table
  !! \htmlinclude arg_table_ldg_order_a_run.html
  subroutine ldg_order_a_run(ncol, nstep, temp, marker, errmsg, errflg)
    use ledger_events, only: ev_call, ev_val

    integer,              intent(in)  :: ncol
    integer,              intent(in)  :: nstep
    real(kind=kind_phys), intent(in)  :: temp(:, :)
    real(kind=kind_phys), intent(out) :: marker(:, :)
    character(len=512),   intent(out) :: errmsg
    integer,              intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_a', 'run', nstep)
    ! Prove the scheme sees the host-module value for this step.
    call ev_val('a_run', 'temp11', temp(1, 1))
    marker(:, :) = real(10 * nstep + 1, kind_phys)
  end subroutine ldg_order_a_run

  !> \section arg_table_ldg_order_a_timestep_final  Argument Table
  !! \htmlinclude arg_table_ldg_order_a_timestep_final.html
  subroutine ldg_order_a_timestep_final(nstep, errmsg, errflg)
    use ledger_events, only: ev_call

    integer,            intent(in)  :: nstep
    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_a', 'timestep_final', nstep)
  end subroutine ldg_order_a_timestep_final

  !> \section arg_table_ldg_order_a_final  Argument Table
  !! \htmlinclude arg_table_ldg_order_a_final.html
  subroutine ldg_order_a_final(errmsg, errflg)
    use ledger_events, only: ev_call

    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    call ev_call('ldg_order_a', 'final', -1)
  end subroutine ldg_order_a_final

end module ldg_order_a

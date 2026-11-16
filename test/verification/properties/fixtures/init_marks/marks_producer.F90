! Init-mark fixture scheme: sets mark_setout (intent out) before any
! scheme reads it, so the suite needs no initial condition for it.
module marks_producer

  use ccpp_kinds, only: kind_phys

  implicit none
  private

  public :: marks_producer_run

contains

!> \section arg_table_marks_producer_run  Argument Table
!! \htmlinclude arg_table_marks_producer_run.html
!!
  subroutine marks_producer_run(nbox, setout, errmsg, errflg)

    integer,            intent(in)  :: nbox
    real(kind_phys),    intent(out) :: setout(:)
    character(len=512), intent(out) :: errmsg
    integer,            intent(out) :: errflg

    errmsg = ''
    errflg = 0
    setout(1:nbox) = 0._kind_phys

  end subroutine marks_producer_run

end module marks_producer

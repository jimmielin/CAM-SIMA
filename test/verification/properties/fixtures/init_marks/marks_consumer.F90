! Init-mark fixture scheme: reads one variable from each initialization
! class so every class appears in the suite's required-input list.
module marks_consumer

  use ccpp_kinds, only: kind_phys

  implicit none
  private

  public :: marks_consumer_run

contains

!> \section arg_table_marks_consumer_run  Argument Table
!! \htmlinclude arg_table_marks_consumer_run.html
!!
  subroutine marks_consumer_run(nbox, pver, theta, slp, prot, init_only, &
       setout, badpath_init, badpath_noinit, errmsg, errflg)

    integer,            intent(in)    :: nbox
    integer,            intent(in)    :: pver
    real(kind_phys),    intent(inout) :: theta(:, :)
    real(kind_phys),    intent(in)    :: slp(:)
    real(kind_phys),    intent(in)    :: prot(:)
    real(kind_phys),    intent(in)    :: init_only(:)
    real(kind_phys),    intent(in)    :: setout(:)
    real(kind_phys),    intent(in)    :: badpath_init(:)
    real(kind_phys),    intent(in)    :: badpath_noinit(:)
    character(len=512), intent(out)   :: errmsg
    integer,            intent(out)   :: errflg

    errmsg = ''
    errflg = 0
    theta(1:nbox, 1:pver) = theta(1:nbox, 1:pver) &
         + 0._kind_phys * (slp(1) + prot(1) + init_only(1) + setout(1) &
         + badpath_init(1) + badpath_noinit(1))

  end subroutine marks_consumer_run

end module marks_consumer

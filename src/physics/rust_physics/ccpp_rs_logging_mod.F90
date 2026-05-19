!>
!! @brief bind(C) helper that lets a Rust CCPP scheme write a single
!!        diagnostic line to a Fortran log unit (typically CAM-SIMA's
!!        atm.log via `iulog`).
!!
!! Design note (RUST_DESIGN.md §9, Phase 2; CP-I): the framework stays
!! host-agnostic, so the symbols `iulog` (CAM-SIMA's `cam_logfile`) and
!! `masterproc` (`spmd_utils`) are not directly referenced here. Capgen
!! routes them in via standard names (`log_output_unit`,
!! `flag_for_mpi_root`) that already exist in the host registry. The
!! Rust side passes them through as bind(C) value args together with a
!! NUL-terminated message buffer.
!!
!! Output is suppressed on non-master MPI ranks; on the master rank
!! the message is written with `write(log_unit, '(A)')` and the unit
!! is flushed afterwards so log lines appear promptly during a run.
!<
module ccpp_rs_logging_mod

   use iso_c_binding, only: c_bool, c_char, c_int, c_null_char

   implicit none
   private

   public :: ccpp_rs_write_log

contains

   subroutine ccpp_rs_write_log(master_flag, log_unit, buf, buf_len) &
        bind(C, name="ccpp_rs_write_log")
      logical(c_bool),              value         :: master_flag
      integer(c_int),               value         :: log_unit
      character(kind=c_char,len=1), intent(in)    :: buf(*)
      integer(c_int),               value         :: buf_len
      character(len=:), allocatable :: msg
      integer :: i, n

      if (.not. logical(master_flag)) return
      if (buf_len <= 0) return

      ! Copy up to the first NUL byte or buf_len, whichever comes first.
      n = 0
      do i = 1, buf_len
         if (buf(i) == c_null_char) exit
         n = i
      end do

      allocate(character(len=n) :: msg)
      do i = 1, n
         msg(i:i) = buf(i)
      end do

      write(log_unit, '(A)') msg
      flush(log_unit)
   end subroutine ccpp_rs_write_log

end module ccpp_rs_logging_mod

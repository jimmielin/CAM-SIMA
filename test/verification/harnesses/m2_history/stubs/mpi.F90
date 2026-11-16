! Harness stub: MPI datatype constants.  The history code imports only
! these from the mpi module and calls MPI_Bcast through the F77 implicit
! interface, so the bcast itself is the external no-op below (single rank:
! broadcast is identity).  Files calling it need -fallow-argument-mismatch,
! as with real F77-interface MPI.
module mpi
   implicit none
   public
   integer, parameter :: MPI_CHARACTER = 1
   integer, parameter :: MPI_INTEGER   = 2
   integer, parameter :: MPI_LOGICAL   = 3
   integer, parameter :: MPI_REAL8     = 4
end module mpi

subroutine mpi_bcast(buf, count, datatype, root, comm, ierr)
   implicit none
   integer :: buf(*)
   integer :: count, datatype, root, comm
   integer :: ierr
   ierr = 0
end subroutine mpi_bcast

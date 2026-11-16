module ledger_host_mod
  ! Host-model data for the assumption-ledger fixture: the variables the
  ! generated caps read by use-association, plus driver-side setup helpers.

  use ccpp_kinds, only: kind_phys

  implicit none
  public

  !> \section arg_table_ledger_host_mod  Argument Table
  !! \htmlinclude arg_table_ledger_host_mod.html
  integer, parameter :: ncols = 4
  integer, parameter :: pver = 3
  integer, protected :: nstep = 0
  real(kind=kind_phys), allocatable :: temp(:, :)
  integer, parameter :: num_tracked = 4
  character(len=40), parameter :: tracked_stdnames(num_tracked) = (/ &
       'ldg_host_wet_mixing_ratio               ', &
       'ldg_host_dry_mixing_ratio               ', &
       'ldg_cloud_dry_mixing_ratio              ', &
       'ldg_dyn_mixing_ratio                    ' /)

  public :: ledger_host_init_fields
  public :: ledger_host_set_step

contains

  subroutine ledger_host_init_fields()
    if (.not. allocated(temp)) then
      allocate(temp(ncols, pver))
    end if
    temp(:, :) = 300.0_kind_phys
  end subroutine ledger_host_init_fields

  subroutine ledger_host_set_step(step)
    ! Advance the host clock; temp changes so schemes can prove they see
    ! the host value for the current step, not a stale copy.
    integer, intent(in) :: step

    nstep = step
    temp(:, :) = 300.0_kind_phys + real(step, kind_phys)
  end subroutine ledger_host_set_step

end module ledger_host_mod

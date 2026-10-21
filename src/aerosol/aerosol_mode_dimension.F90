! The number of aerosol modes that sizes the per-mode modal aerosol state
! of the registry (CCPP number_of_aerosol_modes). It is set from the parsed
! mode_defs namelist, before the registry allocates, so MAM4 and MAM5 both
! fit; it stays 4 when no modes are defined. A leaf module with no imports:
! the registry's physics_types must not depend on the aerosol parsers,
! which reach the time manager and physics_types again.
module aerosol_mode_dimension

  implicit none
  private

  public :: aerosol_mode_dimension_set

  integer, public, protected :: nmodes_aero = 4

contains

  subroutine aerosol_mode_dimension_set(nmodes)
    integer, intent(in) :: nmodes

    if (nmodes > 0) nmodes_aero = nmodes

  end subroutine aerosol_mode_dimension_set

end module aerosol_mode_dimension

!-----------------------------------------------------------------------
! Host-side proof-of-concept demonstrating dynamic constituent property
! registration and value-setting via the cam_constituents API.
!
! Mirrors the physics-side pattern (dynamic_props_poc in
! atmospheric_physics) but with proper phase separation:
!   _register: declares properties (called before const_props_lock)
!   _init:     populates values  (called after const_props_lock)
!
! Registers:
!   is_water_tracer (logical, default .false.)
!     Set to .true. for constituents flagged as water species.
!-----------------------------------------------------------------------
module host_dynamic_props_example

  implicit none
  private

  public :: host_dynamic_props_example_register
  public :: host_dynamic_props_example_init

contains

  subroutine host_dynamic_props_example_register()
    use cam_abortutils,   only: endrun
    use cam_constituents, only: const_props_register, CCPP_PROP_TYPE_LOGICAL

    integer :: errflg
    character(len=512) :: errmsg
    character(len=*), parameter :: subname = 'host_dynamic_props_example_register: '

    errflg = 0
    errmsg = ''

    call const_props_register('is_water_tracer', CCPP_PROP_TYPE_LOGICAL, &
        errflg, errmsg, default_logical=.false.)
    if (errflg /= 0) then
      call endrun(subname//trim(errmsg), file=__FILE__, line=__LINE__)
    end if

  end subroutine host_dynamic_props_example_register

  !-----------------------------------------------------------------------

  subroutine host_dynamic_props_example_init()
    use cam_abortutils,   only: endrun
    use cam_constituents, only: num_constituents, const_is_water_species
    use cam_constituents, only: const_set_property

    integer :: m, errflg
    character(len=512) :: errmsg
    character(len=*), parameter :: subname = 'host_dynamic_props_example_init: '

    errflg = 0
    errmsg = ''

    do m = 1, num_constituents
      if (const_is_water_species(m)) then
        call const_set_property(m, 'is_water_tracer', .true., errflg, errmsg)
        if (errflg /= 0) then
          call endrun(subname//trim(errmsg), file=__FILE__, line=__LINE__)
        end if
      end if
    end do

  end subroutine host_dynamic_props_example_init

end module host_dynamic_props_example

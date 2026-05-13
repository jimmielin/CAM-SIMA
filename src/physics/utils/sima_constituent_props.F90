!-----------------------------------------------------------------------
! Lightweight *per-constituent* view into the shared property registry.
! Each instance holds a pointer to the shared sima_property_registry_t
! and the constituent index, delegating all operations to the registry.
!-----------------------------------------------------------------------
module sima_constituent_props
  use ccpp_constituent_prop_mod, only: ccpp_host_constituent_props_t
  use sima_property_registry,    only: sima_property_registry_t

  implicit none
  private

  type, public, extends(ccpp_host_constituent_props_t) :: &
      sima_constituent_props_t
    type(sima_property_registry_t), pointer :: registry => null()
    integer :: const_idx = 0
  contains
    procedure :: has_property           => sima_has_property
    procedure :: get_property_logical   => sima_get_logical
    procedure :: get_property_integer   => sima_get_integer
    procedure :: get_property_real      => sima_get_real
    procedure :: get_property_character => sima_get_character
    procedure :: set_property_logical   => sima_set_logical
    procedure :: set_property_integer   => sima_set_integer
    procedure :: set_property_real      => sima_set_real
    procedure :: set_property_character => sima_set_character
    procedure :: register_property      => sima_register_property
  end type sima_constituent_props_t

contains

  !-----------------------------------------------------------------------
  logical function sima_has_property(this, name)
    class(sima_constituent_props_t), intent(in) :: this
    character(len=*), intent(in) :: name

    if (associated(this%registry)) then
      sima_has_property = this%registry%has_registered(name)
    else
      sima_has_property = .false.
    end if
  end function sima_has_property

  !-----------------------------------------------------------------------
  subroutine sima_get_logical(this, name, val, errflg, errmsg)
    class(sima_constituent_props_t), intent(in) :: this
    character(len=*), intent(in) :: name
    logical, intent(out) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      val = .false.; errflg = 1
      errmsg = 'sima_get_logical: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) then
      val = .false.
      return
    end if
    call this%registry%get_logical_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_get_logical

  !-----------------------------------------------------------------------
  subroutine sima_get_integer(this, name, val, errflg, errmsg)
    class(sima_constituent_props_t), intent(in) :: this
    character(len=*), intent(in) :: name
    integer, intent(out) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      val = 0; errflg = 1
      errmsg = 'sima_get_integer: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) then
      val = 0
      return
    end if
    call this%registry%get_integer_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_get_integer

  !-----------------------------------------------------------------------
  subroutine sima_get_real(this, name, val, errflg, errmsg)
    use ccpp_kinds, only: kind_phys
    class(sima_constituent_props_t), intent(in) :: this
    character(len=*), intent(in) :: name
    real(kind_phys), intent(out) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      val = 0.0_kind_phys
      errflg = 1
      errmsg = 'sima_get_real: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) then
      val = 0.0_kind_phys
      return
    end if
    call this%registry%get_real_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_get_real

  !-----------------------------------------------------------------------
  subroutine sima_get_character(this, name, val, errflg, errmsg)
    class(sima_constituent_props_t), intent(in) :: this
    character(len=*), intent(in) :: name
    character(len=*), intent(out) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      val = ''
      errflg = 1
      errmsg = 'sima_get_character: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) then
      val = ''
      return
    end if
    call this%registry%get_character_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_get_character

  !-----------------------------------------------------------------------
  subroutine sima_set_logical(this, name, val, errflg, errmsg)
    class(sima_constituent_props_t), intent(inout) :: this
    character(len=*), intent(in) :: name
    logical, intent(in) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      errflg = 1
      errmsg = 'sima_set_logical: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) return
    call this%registry%set_logical_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_set_logical

  !-----------------------------------------------------------------------
  subroutine sima_set_integer(this, name, val, errflg, errmsg)
    class(sima_constituent_props_t), intent(inout) :: this
    character(len=*), intent(in) :: name
    integer, intent(in) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      errflg = 1
      errmsg = 'sima_set_integer: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) return
    call this%registry%set_integer_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_set_integer

  !-----------------------------------------------------------------------
  subroutine sima_set_real(this, name, val, errflg, errmsg)
    use ccpp_kinds, only: kind_phys
    class(sima_constituent_props_t), intent(inout) :: this
    character(len=*), intent(in) :: name
    real(kind_phys), intent(in) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      errflg = 1
      errmsg = 'sima_set_real: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) return
    call this%registry%set_real_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_set_real

  !-----------------------------------------------------------------------
  subroutine sima_set_character(this, name, val, errflg, errmsg)
    class(sima_constituent_props_t), intent(inout) :: this
    character(len=*), intent(in) :: name
    character(len=*), intent(in) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: pidx

    if (.not. associated(this%registry)) then
      errflg = 1
      errmsg = 'sima_set_character: registry not associated'; return
    end if
    call this%registry%prop_index(name, pidx, errflg, errmsg)
    if (errflg /= 0) return
    call this%registry%set_character_val(pidx, this%const_idx, val, &
        errflg, errmsg)
  end subroutine sima_set_character

  !-----------------------------------------------------------------------
  ! Register a property on the shared registry. This is a global
  ! operation: it does not matter which constituent's view is used.
  ! It is what makes the const_props(?any?)%register_prop api a bit strange.
  !-----------------------------------------------------------------------
  subroutine sima_register_property(this, name, prop_type, errflg, &
      errmsg, default_logical, default_integer, default_real, &
      default_character)
    use ccpp_kinds, only: kind_phys
    class(sima_constituent_props_t), intent(inout) :: this
    character(len=*), intent(in) :: name
    integer, intent(in) :: prop_type
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    logical, optional, intent(in) :: default_logical
    integer, optional, intent(in) :: default_integer
    real(kind_phys), optional, intent(in) :: default_real
    character(len=*), optional, intent(in) :: default_character

    if (.not. associated(this%registry)) then
      errflg = 1
      errmsg = 'sima_constituent_props: registry not associated'
      return
    end if
    call this%registry%register(name, prop_type, errflg, errmsg, &
        default_logical, default_integer, default_real, &
        default_character)
  end subroutine sima_register_property

end module sima_constituent_props

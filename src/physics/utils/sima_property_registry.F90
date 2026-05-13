!-----------------------------------------------------------------------
! Property registry for CAM-SIMA.
! Provides typed columnar storage for dynamic constituent properties,
! supporting logical, integer, real(kind_phys), and character types.
! Properties are registered by name at runtime and stored in typed
! arrays indexed by (constituent_index, property_column).
!
! Lifecycle
! ---------
! 1. initialize()
!    Allocates metadata arrays (property names, types, defaults, hash
!    table) with an initial capacity. No value storage yet.
!
! 2. register(name, prop_type, ..., default_*)    [repeatable]
!    Declares a named property with its type and optional default value.
!    Metadata arrays auto-grow if capacity is exceeded. Can be called
!    before or after allocate_storage (step 3), but the typical path
!    is to register all known properties before allocating storage.
!
! 3. allocate_storage(num_constituents)
!    Allocates the typed value stores (logical/integer/real/character)
!    and the is_set tracking array, sized (num_constituents x num_props).
!    Called once the constituent count is finalized (post lock_table).
!
! At runtime, set_*_val and get_*_val will work per-constituent.
!
! Please see sima_constituent_props.F90 for an example for usage of the
! sima_property_registry_t object to provide the proposed extension to
! the CCPP constituents properties object to add dynamic
! properties to each dynamic constituent: it holds a pointer
! to this registry and a constituent index, and resolves property names
! to slot indices via the hash table before calling get/set.
!
! The host attaches one sima_constituent_props_t view per constituent
! to the CCPP const_props(:) array, so schemes use the standard
! const_props(m)%get_property(name, val, errflg, errmsg) interface.
!-----------------------------------------------------------------------
module sima_property_registry
  use ccpp_kinds,                only: kind_phys
  use ccpp_constituent_prop_mod, only: CCPP_PROP_CHAR_LEN
  use ccpp_hashable,             only: ccpp_hashable_t
  use ccpp_hash_table,           only: ccpp_hash_table_t

  implicit none
  private

  integer, parameter :: MAX_PROP_NAME_LEN = 64
  integer, parameter :: INITIAL_CAPACITY  = 16
  ! Hash table size parameter: 2^HASH_TABLE_SIZE_BITS buckets
  integer, parameter :: HASH_TABLE_SIZE_BITS = 6  ! 2**6=64 buckets

  !-----------------------------------------------------------------------
  ! Hashable entry type for O(1) property name lookup.
  ! Each entry stores the property name (as the hash key) and its
  ! integer slot index in the registry's metadata arrays.
  !-----------------------------------------------------------------------
  type, extends(ccpp_hashable_t) :: prop_hash_entry_t
    character(len=MAX_PROP_NAME_LEN) :: prop_name = ''
    integer   :: slot_index = 0
  contains
    procedure :: key => prop_hash_entry_key
  end type prop_hash_entry_t

  ! We store an array of pointers to ccpp_hashable_t (prop_hash_entry_t) objects
  ! by using a derived type (since Fortran cannot store arrays of pointers directly)
  ! the purpose of this (instead of storing an array of prop_hash_entry_t directly)
  ! is so we do not lose the pointers stored by ccpp_hash_table_t when
  ! move_alloc-ing the array when we run out of space for properties.
  type :: prop_hash_entry_ptr_t
    type(prop_hash_entry_t), pointer :: entry => null()
  end type prop_hash_entry_ptr_t

  ! Main property registry data container
  type, public :: sima_property_registry_t
    private

    ! Number of registered properties and constituents
    ! capacity is the currently allocated capacity for dynamic properties.
    ! The arrays sized (capacity) can grow as needed starting from INITIAL_CAPACITY.
    integer :: num_props = 0
    integer :: num_constituents = 0
    integer :: capacity = 0
    logical :: storage_allocated = .false.

    ! Property metadata arrays, sized (capacity):
    character(len=MAX_PROP_NAME_LEN), allocatable :: prop_names(:)
    integer,                          allocatable :: prop_types(:)
    ! Maps each property slot to its column index in the typed store
    integer,                          allocatable :: type_col_index(:)

    ! Number of properties of each type (for column indexing)
    integer :: num_logical_props = 0
    integer :: num_integer_props = 0
    integer :: num_real_props    = 0
    integer :: num_char_props    = 0

    ! Typed value storage: (num_constituents, num_type_props)
    logical,                           allocatable :: logical_store(:,:)
    integer,                           allocatable :: integer_store(:,:)
    real(kind_phys),                   allocatable :: real_store(:,:)
    character(len=CCPP_PROP_CHAR_LEN), allocatable :: character_store(:,:)

    ! Some properties may have "default" values
    ! (i.e., even if they did not have a value set, they will return the default)
    ! Not all properties have default - this array flags if they do:
    logical,                           allocatable :: has_default(:)
    ! If they do, then the default (per-property, not per-constituent) values
    ! are stored in typed arrays below:
    ! so they are allocated during initialize() and grow with
    ! the other metadata arrays.
    logical,                           allocatable :: default_logical(:)
    integer,                           allocatable :: default_integer(:)
    real(kind_phys),                   allocatable :: default_real(:)
    character(len=CCPP_PROP_CHAR_LEN), allocatable :: default_character(:)

    ! Track which (constituent, property) pairs have been explicitly set
    ! Sized (num_constituents, capacity)
    logical, allocatable :: is_set(:,:)

    ! Hash table for O(1) property name -> slot index lookup.
    type(ccpp_hash_table_t) :: name_hash

    ! Heap-allocated hash entries (pointers survive array growth).
    ! Sized (capacity).
    type(prop_hash_entry_ptr_t),       allocatable :: hash_entries(:)

  contains
    procedure :: initialize       => registry_initialize
    procedure :: register         => registry_register
    procedure :: allocate_storage => registry_allocate_storage
    procedure :: prop_index       => registry_prop_index
    procedure :: has_registered   => registry_has_registered
    procedure :: num_properties   => registry_num_properties
    procedure :: is_value_set     => registry_is_value_set

    ! Per-element typed access (by property index and constituent index)
    procedure :: set_logical_val   => registry_set_logical
    procedure :: set_integer_val   => registry_set_integer
    procedure :: set_real_val      => registry_set_real
    procedure :: set_character_val => registry_set_character
    procedure :: get_logical_val   => registry_get_logical
    procedure :: get_integer_val   => registry_get_integer
    procedure :: get_real_val      => registry_get_real
    procedure :: get_character_val => registry_get_character
  end type sima_property_registry_t

contains

  !-----------------------------------------------------------------------
  ! Initialize the registry for collecting property declarations.
  ! Call before any register() calls.
  !-----------------------------------------------------------------------
  subroutine registry_initialize(this)
    class(sima_property_registry_t), intent(inout) :: this

    this%num_props = 0
    this%num_constituents = 0
    this%capacity = INITIAL_CAPACITY
    this%storage_allocated = .false.
    this%num_logical_props = 0
    this%num_integer_props = 0
    this%num_real_props = 0
    this%num_char_props = 0

    if (allocated(this%prop_names)) deallocate(this%prop_names)
    if (allocated(this%prop_types)) deallocate(this%prop_types)
    if (allocated(this%type_col_index)) deallocate(this%type_col_index)
    if (allocated(this%is_set)) deallocate(this%is_set)

    allocate(this%prop_names(INITIAL_CAPACITY))
    allocate(this%prop_types(INITIAL_CAPACITY))
    allocate(this%type_col_index(INITIAL_CAPACITY))

    ! Default value storage (indexed by property slot, same as other metadata)
    if (allocated(this%default_logical))   deallocate(this%default_logical)
    if (allocated(this%default_integer))   deallocate(this%default_integer)
    if (allocated(this%default_real))      deallocate(this%default_real)
    if (allocated(this%default_character)) deallocate(this%default_character)
    if (allocated(this%has_default))       deallocate(this%has_default)
    allocate(this%default_logical(INITIAL_CAPACITY))
    allocate(this%default_integer(INITIAL_CAPACITY))
    allocate(this%default_real(INITIAL_CAPACITY))
    allocate(this%default_character(INITIAL_CAPACITY))
    allocate(this%has_default(INITIAL_CAPACITY), source=.false.)

    ! Type stores start empty; allocated in allocate_storage
    if (allocated(this%logical_store))     deallocate(this%logical_store)
    if (allocated(this%integer_store))     deallocate(this%integer_store)
    if (allocated(this%real_store))        deallocate(this%real_store)
    if (allocated(this%character_store))   deallocate(this%character_store)

    ! Initialize hash table for O(1) name lookup
    call this%name_hash%initialize(HASH_TABLE_SIZE_BITS)

    ! Allocate hash entry pointer array (entries are heap-allocated
    ! individually so that pointers stored in the hash table survive
    ! when this array is grown via move_alloc).
    if (allocated(this%hash_entries)) then
      call deallocate_hash_entries(this)
    end if
    allocate(this%hash_entries(INITIAL_CAPACITY))

  end subroutine registry_initialize

  !-----------------------------------------------------------------------
  ! Register a property declaration (name + type + optional default).
  ! Can be called before or after allocate_storage. If called after,
  ! the storage arrays are grown to accommodate the new property.
  !-----------------------------------------------------------------------
  subroutine registry_register(this, name, prop_type, errflg, errmsg, &
      default_logical, default_integer, default_real, default_character)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_LOGICAL,   &
                                         CCPP_PROP_TYPE_INTEGER,   &
                                         CCPP_PROP_TYPE_REAL,      &
                                         CCPP_PROP_TYPE_CHARACTER
    class(sima_property_registry_t), intent(inout) :: this

    character(len=*),                intent(in)    :: name
    integer,                         intent(in)    :: prop_type
    integer,                         intent(out)   :: errflg
    character(len=*),                intent(out)   :: errmsg

    ! Optional: if this property should have "default" values
    ! i.e., querying for this property on a constituent that does not have
    ! this property explicit set will be non-fatal and return this default:
    logical,               optional, intent(in)    :: default_logical
    integer,               optional, intent(in)    :: default_integer
    real(kind_phys),       optional, intent(in)    :: default_real
    character(len=*),      optional, intent(in)    :: default_character

    character(len=*), parameter :: subname = 'sima_property_registry::registry_register'
    integer :: idx, col

    errflg = 0
    errmsg = ''

    ! Check for duplicate
    if (this%has_registered(name)) then
      errflg = 1
      errmsg = subname//': property already registered: '// &
          trim(name)
      return
    end if

    ! Validate prop_type
    if (prop_type < CCPP_PROP_TYPE_LOGICAL .or. &
        prop_type > CCPP_PROP_TYPE_CHARACTER) then
      errflg = 1
      errmsg = subname//': invalid property type for: '// &
          trim(name)
      return
    end if

    ! Grow metadata arrays if needed
    if (this%num_props >= this%capacity) then
      call grow_metadata_arrays(this)
    end if

    ! Add the property
    this%num_props = this%num_props + 1
    idx = this%num_props
    this%prop_names(idx) = trim(name)
    this%prop_types(idx) = prop_type

    ! Assign column index in the appropriate typed store
    select case (prop_type)
      case (CCPP_PROP_TYPE_LOGICAL)
        this%num_logical_props = this%num_logical_props + 1
        col = this%num_logical_props
      case (CCPP_PROP_TYPE_INTEGER)
        this%num_integer_props = this%num_integer_props + 1
        col = this%num_integer_props
      case (CCPP_PROP_TYPE_REAL)
        this%num_real_props = this%num_real_props + 1
        col = this%num_real_props
      case (CCPP_PROP_TYPE_CHARACTER)
        this%num_char_props = this%num_char_props + 1
        col = this%num_char_props
    end select
    this%type_col_index(idx) = col

    ! If storage is already allocated, grow the typed stores
    if (this%storage_allocated) then
      call grow_typed_stores(this, prop_type)
    end if

    ! Add to hash table for O(1) name lookup
    allocate(this%hash_entries(idx)%entry)
    this%hash_entries(idx)%entry%prop_name = trim(name)
    this%hash_entries(idx)%entry%slot_index = idx
    call this%name_hash%add_hash_key(this%hash_entries(idx)%entry)

    ! Store default value if provided
    call store_default(this, idx, prop_type, default_logical, &
        default_integer, default_real, default_character)

  end subroutine registry_register

  !-----------------------------------------------------------------------
  ! Allocate the columnar value storage arrays after the number of
  ! constituents is known (post lock_table).
  !-----------------------------------------------------------------------
  subroutine registry_allocate_storage(this, num_constituents, errflg, errmsg)
    class(sima_property_registry_t), intent(inout) :: this
    integer,                         intent(in)    :: num_constituents
    integer,                         intent(out)   :: errflg
    character(len=*),                intent(out)   :: errmsg

    errflg = 0
    errmsg = ''
    this%num_constituents = num_constituents

    ! Allocate typed value stores (may be zero-sized if no props of that type)
    allocate(this%logical_store(num_constituents, &
        max(this%num_logical_props, 0)), source=.false.)
    allocate(this%integer_store(num_constituents, &
        max(this%num_integer_props, 0)), source=0)
    allocate(this%real_store(num_constituents, &
        max(this%num_real_props, 0)), source=0.0_kind_phys)
    allocate(this%character_store(num_constituents, &
        max(this%num_char_props, 0)), source=repeat(' ', CCPP_PROP_CHAR_LEN))

    ! Allocate is_set tracking
    allocate(this%is_set(num_constituents, this%capacity), source=.false.)

    this%storage_allocated = .true.

  end subroutine registry_allocate_storage

  !-----------------------------------------------------------------------
  ! Resolve a property name to its integer slot index.
  !-----------------------------------------------------------------------
  subroutine registry_prop_index(this, name, idx, errflg, errmsg)
    class(sima_property_registry_t), intent(in)  :: this
    character(len=*),                intent(in)  :: name
    integer,                         intent(out) :: idx
    integer,                         intent(out) :: errflg
    character(len=*),                intent(out) :: errmsg

    class(ccpp_hashable_t),  pointer :: hval
    type(prop_hash_entry_t), pointer :: pentry
    character(len=*),      parameter :: subname = 'sima_property_registry::registry_prop_index'

    errflg = 0
    errmsg = ''

    ! note hplin: should we return in each clause here?

    hval => this%name_hash%table_value(trim(name))
    if (associated(hval)) then
      select type (hval)
      type is (prop_hash_entry_t)
        pentry => hval
        idx = pentry%slot_index
      class default
        idx = -1
        errflg = 1
        errmsg = subname//': unexpected hash entry type'
      end select
    else
      idx = -1
      errflg = 1
      errmsg = subname//': property not found: '//trim(name)
    end if

  end subroutine registry_prop_index

  !-----------------------------------------------------------------------
  ! Is this property registered?
  !-----------------------------------------------------------------------
  logical function registry_has_registered(this, name)
    class(sima_property_registry_t), intent(in) :: this
    character(len=*),                intent(in) :: name

    class(ccpp_hashable_t), pointer :: hval

    hval => this%name_hash%table_value(trim(name))
    registry_has_registered = associated(hval)
  end function registry_has_registered

  !-----------------------------------------------------------------------
  integer function registry_num_properties(this)
    class(sima_property_registry_t), intent(in) :: this
    registry_num_properties = this%num_props
  end function registry_num_properties

  !-----------------------------------------------------------------------
  ! Has a value been explicitly set for this (constituent, property) pair?
  !-----------------------------------------------------------------------
  logical function registry_is_value_set(this, const_idx, prop_idx)
    class(sima_property_registry_t), intent(in) :: this
    integer, intent(in) :: const_idx
    integer, intent(in) :: prop_idx
    registry_is_value_set = this%is_set(const_idx, prop_idx)
  end function registry_is_value_set

  !-----------------------------------------------------------------------
  ! Typed setters
  !-----------------------------------------------------------------------
  subroutine registry_set_logical(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_LOGICAL
    class(sima_property_registry_t), intent(inout) :: this
    integer,                         intent(in)    :: prop_idx, const_idx
    logical,                         intent(in)    :: val
    integer,                         intent(out)   :: errflg
    character(len=*),                intent(out)   :: errmsg

    integer :: col
    character(len=*), parameter :: subname = 'sima_property_registry::registry_set_logical'

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_LOGICAL) then
      errflg = 1
      errmsg = subname//': type mismatch (expected logical)'
      return
    end if
    col = this%type_col_index(prop_idx)
    this%logical_store(const_idx, col) = val
    this%is_set(const_idx, prop_idx) = .true.
  end subroutine registry_set_logical

  subroutine registry_set_integer(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_INTEGER
    class(sima_property_registry_t), intent(inout) :: this
    integer,                         intent(in)    :: prop_idx, const_idx
    integer,                         intent(in)    :: val
    integer,                         intent(out)   :: errflg
    character(len=*),                intent(out)   :: errmsg

    integer :: col
    character(len=*), parameter :: subname = 'sima_property_registry::registry_set_integer'

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_INTEGER) then
      errflg = 1
      errmsg = subname//': type mismatch (expected integer)'
      return
    end if
    col = this%type_col_index(prop_idx)
    this%integer_store(const_idx, col) = val
    this%is_set(const_idx, prop_idx) = .true.
  end subroutine registry_set_integer

  subroutine registry_set_real(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_REAL
    class(sima_property_registry_t), intent(inout) :: this
    integer,                         intent(in)    :: prop_idx, const_idx
    real(kind_phys),                 intent(in)    :: val
    integer,                         intent(out)   :: errflg
    character(len=*),                intent(out)   :: errmsg

    integer :: col
    character(len=*), parameter :: subname = 'sima_property_registry::registry_set_real'

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_REAL) then
      errflg = 1
      errmsg = subname//': type mismatch (expected real)'
      return
    end if
    col = this%type_col_index(prop_idx)
    this%real_store(const_idx, col) = val
    this%is_set(const_idx, prop_idx) = .true.
  end subroutine registry_set_real

  subroutine registry_set_character(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_CHARACTER
    class(sima_property_registry_t), intent(inout) :: this
    integer,                         intent(in)    :: prop_idx, const_idx
    character(len=*),                intent(in)    :: val
    integer,                         intent(out)   :: errflg
    character(len=*),                intent(out)   :: errmsg

    integer :: col
    character(len=*), parameter :: subname = 'sima_property_registry::registry_set_character'

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_CHARACTER) then
      errflg = 1
      errmsg = subname//': type mismatch (expected character)'
      return
    end if
    col = this%type_col_index(prop_idx)
    this%character_store(const_idx, col) = trim(val)
    this%is_set(const_idx, prop_idx) = .true.
  end subroutine registry_set_character

  !-----------------------------------------------------------------------
  ! Typed getters
  ! - return set value,
  ! - unset? default if with default, error if no default
  !-----------------------------------------------------------------------
  subroutine registry_get_logical(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_LOGICAL
    class(sima_property_registry_t), intent(in)  :: this
    integer,                         intent(in)  :: prop_idx, const_idx
    logical,                         intent(out) :: val
    integer,                         intent(out) :: errflg
    character(len=*),                intent(out) :: errmsg
    integer :: col

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_LOGICAL) then
      val = .false.
      errflg = 1
      errmsg = 'sima_property_registry: type mismatch (expected logical)'
      return
    end if
    col = this%type_col_index(prop_idx)
    if (this%is_set(const_idx, prop_idx)) then
      val = this%logical_store(const_idx, col)
    else if (this%has_default(prop_idx)) then
      val = this%default_logical(prop_idx)
    else
      val = .false.
      errflg = 1
      errmsg = 'sima_property_registry: property not set and no default: '// &
          trim(this%prop_names(prop_idx))
      return
    end if
  end subroutine registry_get_logical

  subroutine registry_get_integer(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_INTEGER
    class(sima_property_registry_t), intent(in)  :: this
    integer,                         intent(in)  :: prop_idx, const_idx
    integer,                         intent(out) :: val
    integer,                         intent(out) :: errflg
    character(len=*),                intent(out) :: errmsg
    integer :: col

    errflg = 0; errmsg = ''
    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_INTEGER) then
      errflg = 1; val = 0
      errmsg = 'sima_property_registry: type mismatch (expected integer)'
      return
    end if
    col = this%type_col_index(prop_idx)
    if (this%is_set(const_idx, prop_idx)) then
      val = this%integer_store(const_idx, col)
    else if (this%has_default(prop_idx)) then
      val = this%default_integer(prop_idx)
    else
      val = 0
      errflg = 1
      errmsg = 'sima_property_registry: property not set and no default: '// &
          trim(this%prop_names(prop_idx))
    end if
  end subroutine registry_get_integer

  subroutine registry_get_real(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_REAL
    class(sima_property_registry_t), intent(in) :: this
    integer, intent(in) :: prop_idx, const_idx
    real(kind_phys), intent(out) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: col

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_REAL) then
      val = 0.0_kind_phys
      errflg = 1
      errmsg = 'sima_property_registry: type mismatch (expected real)'
      return
    end if
    col = this%type_col_index(prop_idx)
    if (this%is_set(const_idx, prop_idx)) then
      val = this%real_store(const_idx, col)
    else if (this%has_default(prop_idx)) then
      val = this%default_real(prop_idx)
    else
      val = -huge(0.0_kind_phys)
      errflg = 1
      errmsg = 'sima_property_registry: property not set and no default: '// &
          trim(this%prop_names(prop_idx))
      return
    end if
  end subroutine registry_get_real

  subroutine registry_get_character(this, prop_idx, const_idx, val, &
      errflg, errmsg)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_CHARACTER
    class(sima_property_registry_t), intent(in) :: this
    integer, intent(in) :: prop_idx, const_idx
    character(len=*), intent(out) :: val
    integer, intent(out) :: errflg
    character(len=*), intent(out) :: errmsg
    integer :: col

    errflg = 0
    errmsg = ''

    if (this%prop_types(prop_idx) /= CCPP_PROP_TYPE_CHARACTER) then
      val = ''
      errflg = 1
      errmsg = 'sima_property_registry: type mismatch (expected character)'
      return
    end if
    col = this%type_col_index(prop_idx)
    if (this%is_set(const_idx, prop_idx)) then
      val = this%character_store(const_idx, col)
    else if (this%has_default(prop_idx)) then
      val = this%default_character(prop_idx)
    else
      val = ''
      errflg = 1
      errmsg = 'sima_property_registry: property not set and no default: '// &
          trim(this%prop_names(prop_idx))
      return
    end if
  end subroutine registry_get_character

  !-----------------------------------------------------------------------
  ! Key function for the hashable property entry type.
  !-----------------------------------------------------------------------
  function prop_hash_entry_key(hashable) result(k)
    class(prop_hash_entry_t), intent(in) :: hashable
    character(len=:), allocatable :: k
    k = trim(hashable%prop_name)
  end function prop_hash_entry_key

  !-----------------------------------------------------------------------
  ! Private helper: deallocate all heap-allocated hash entries.
  !-----------------------------------------------------------------------
  subroutine deallocate_hash_entries(this)
    type(sima_property_registry_t), intent(inout) :: this
    integer :: i
    if (allocated(this%hash_entries)) then
      do i = 1, size(this%hash_entries)
        if (associated(this%hash_entries(i)%entry)) then
          deallocate(this%hash_entries(i)%entry)
        end if
      end do
      deallocate(this%hash_entries)
    end if
  end subroutine deallocate_hash_entries

  !-----------------------------------------------------------------------
  ! Private helper: grow metadata arrays when capacity is exceeded
  !-----------------------------------------------------------------------
  subroutine grow_metadata_arrays(this)
    type(sima_property_registry_t), intent(inout) :: this
    integer :: new_cap, np
    character(len=MAX_PROP_NAME_LEN), allocatable :: tmp_names(:)
    character(len=CCPP_PROP_CHAR_LEN), allocatable :: tmp_chars(:)
    integer, allocatable :: tmp_ints(:)
    logical, allocatable :: tmp_logs(:)
    logical, allocatable :: tmp_is_set(:,:)
    real(kind_phys), allocatable :: tmp_reals(:)
    type(prop_hash_entry_ptr_t), allocatable :: tmp_hash_table_entries(:)

    new_cap = this%capacity * 2
    np = this%num_props

    ! Grow prop_names
    allocate(tmp_names(new_cap))
    tmp_names(1:np) = this%prop_names(1:np)
    call move_alloc(tmp_names, this%prop_names)

    ! Grow prop_types
    allocate(tmp_ints(new_cap))
    tmp_ints(1:np) = this%prop_types(1:np)
    call move_alloc(tmp_ints, this%prop_types)

    ! Grow type_col_index
    allocate(tmp_ints(new_cap))
    tmp_ints(1:np) = this%type_col_index(1:np)
    call move_alloc(tmp_ints, this%type_col_index)

    ! Grow default value storage (slot-indexed, same as other metadata)
    allocate(tmp_logs(new_cap))
    tmp_logs(1:np) = this%default_logical(1:np)
    call move_alloc(tmp_logs, this%default_logical)

    allocate(tmp_ints(new_cap))
    tmp_ints(1:np) = this%default_integer(1:np)
    call move_alloc(tmp_ints, this%default_integer)

    allocate(tmp_reals(new_cap))
    tmp_reals(1:np) = this%default_real(1:np)
    call move_alloc(tmp_reals, this%default_real)

    allocate(tmp_chars(new_cap))
    tmp_chars(1:np) = this%default_character(1:np)
    call move_alloc(tmp_chars, this%default_character)

    allocate(tmp_logs(new_cap), source=.false.)
    tmp_logs(1:np) = this%has_default(1:np)
    call move_alloc(tmp_logs, this%has_default)

    ! Grow is_set if storage is allocated
    if (this%storage_allocated .and. allocated(this%is_set)) then
      allocate(tmp_is_set(this%num_constituents, new_cap), source=.false.)
      tmp_is_set(:, 1:this%capacity) = this%is_set(:, 1:this%capacity)
      call move_alloc(tmp_is_set, this%is_set)
    end if

    ! Grow hash entry pointer array. The pointed-to objects are
    ! individually heap-allocated, so the hash table's internal
    ! pointers remain valid after this move_alloc.
    allocate(tmp_hash_table_entries(new_cap))
    tmp_hash_table_entries(1:np) = this%hash_entries(1:np)
    call move_alloc(tmp_hash_table_entries, this%hash_entries)

    this%capacity = new_cap
  end subroutine grow_metadata_arrays

  !-----------------------------------------------------------------------
  ! Private helper: grow a specific typed store when a property is
  ! registered after allocate_storage has been called.
  !-----------------------------------------------------------------------
  subroutine grow_typed_stores(this, prop_type)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_LOGICAL,   &
                                         CCPP_PROP_TYPE_INTEGER,   &
                                         CCPP_PROP_TYPE_REAL,      &
                                         CCPP_PROP_TYPE_CHARACTER
    type(sima_property_registry_t), intent(inout) :: this
    integer, intent(in) :: prop_type
    integer :: nc

    nc = this%num_constituents

    select case (prop_type)
    case (CCPP_PROP_TYPE_LOGICAL)
      call grow_logical_store(this, nc, this%num_logical_props)
    case (CCPP_PROP_TYPE_INTEGER)
      call grow_integer_store(this, nc, this%num_integer_props)
    case (CCPP_PROP_TYPE_REAL)
      call grow_real_store(this, nc, this%num_real_props)
    case (CCPP_PROP_TYPE_CHARACTER)
      call grow_character_store(this, nc, this%num_char_props)
    end select

  end subroutine grow_typed_stores

  subroutine grow_logical_store(this, nc, new_cols)
    type(sima_property_registry_t), intent(inout) :: this
    integer, intent(in) :: nc, new_cols
    logical, allocatable :: tmp(:,:)
    integer :: old_cols

    old_cols = new_cols - 1
    allocate(tmp(nc, new_cols), source=.false.)
    if (old_cols > 0) tmp(:, 1:old_cols) = this%logical_store(:, 1:old_cols)
    call move_alloc(tmp, this%logical_store)
  end subroutine grow_logical_store

  subroutine grow_integer_store(this, nc, new_cols)
    type(sima_property_registry_t), intent(inout) :: this
    integer, intent(in) :: nc, new_cols
    integer, allocatable :: tmp(:,:)
    integer :: old_cols

    old_cols = new_cols - 1
    allocate(tmp(nc, new_cols), source=0)
    if (old_cols > 0) tmp(:, 1:old_cols) = this%integer_store(:, 1:old_cols)
    call move_alloc(tmp, this%integer_store)
  end subroutine grow_integer_store

  subroutine grow_real_store(this, nc, new_cols)
    type(sima_property_registry_t), intent(inout) :: this
    integer, intent(in) :: nc, new_cols
    real(kind_phys), allocatable :: tmp(:,:)
    integer :: old_cols

    old_cols = new_cols - 1
    allocate(tmp(nc, new_cols), source=0.0_kind_phys)
    if (old_cols > 0) tmp(:, 1:old_cols) = this%real_store(:, 1:old_cols)
    call move_alloc(tmp, this%real_store)
  end subroutine grow_real_store

  subroutine grow_character_store(this, nc, new_cols)
    type(sima_property_registry_t), intent(inout) :: this
    integer, intent(in) :: nc, new_cols
    character(len=CCPP_PROP_CHAR_LEN), allocatable :: tmp(:,:)
    integer :: old_cols

    old_cols = new_cols - 1
    allocate(tmp(nc, new_cols), source=repeat(' ', CCPP_PROP_CHAR_LEN))
    if (old_cols > 0) tmp(:, 1:old_cols) = this%character_store(:, 1:old_cols)
    call move_alloc(tmp, this%character_store)
  end subroutine grow_character_store

  !-----------------------------------------------------------------------
  ! Private helper for storing a default value during registration.
  ! Defaults are stored in slot-indexed arrays (same as other metadata),
  ! so they work identically before and after allocate_storage.
  !-----------------------------------------------------------------------
  subroutine store_default(this, prop_idx, prop_type, default_logical, &
      default_integer, default_real, default_character)
    use ccpp_constituent_prop_mod, only: CCPP_PROP_TYPE_LOGICAL,   &
                                         CCPP_PROP_TYPE_INTEGER,   &
                                         CCPP_PROP_TYPE_REAL,      &
                                         CCPP_PROP_TYPE_CHARACTER
    type(sima_property_registry_t), intent(inout) :: this
    integer, intent(in) :: prop_idx, prop_type
    logical, optional, intent(in) :: default_logical
    integer, optional, intent(in) :: default_integer
    real(kind_phys), optional, intent(in) :: default_real
    character(len=*), optional, intent(in) :: default_character

    select case (prop_type)
    case (CCPP_PROP_TYPE_LOGICAL)
      if (present(default_logical)) then
        this%default_logical(prop_idx) = default_logical
        this%has_default(prop_idx) = .true.
      end if
    case (CCPP_PROP_TYPE_INTEGER)
      if (present(default_integer)) then
        this%default_integer(prop_idx) = default_integer
        this%has_default(prop_idx) = .true.
      end if
    case (CCPP_PROP_TYPE_REAL)
      if (present(default_real)) then
        this%default_real(prop_idx) = default_real
        this%has_default(prop_idx) = .true.
      end if
    case (CCPP_PROP_TYPE_CHARACTER)
      if (present(default_character)) then
        this%default_character(prop_idx) = default_character
        this%has_default(prop_idx) = .true.
      end if
    end select

  end subroutine store_default

end module sima_property_registry

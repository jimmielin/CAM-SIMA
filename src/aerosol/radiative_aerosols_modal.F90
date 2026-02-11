! Modal support types and subroutines for radiative_aerosols.
!
! The contents of this file were split off from the original CAM rad_constituents
! for types and subroutines pertaining to specifically modal aerosol.
module radiative_aerosols_modal

  implicit none
  private

  public :: parse_mode_defs               ! Parse namelist mode definition specifiers
  public :: init_mode_comps               ! Initialize mode definitions (index initialization)

  !----------------------------------------------------------------------
  ! Public module types for use by radiative_aerosols module:
  !----------------------------------------------------------------------

  ! Maximum length of mode definition string in namelist
  integer, parameter, public    :: n_mode_str = 120

  ! Type to provide access to the components of a mode
  type, public :: mode_component_t
    integer                     :: nspec            ! # of species per mode (dimension for below arrays:)

    character(len=  1)          :: source_num_a     ! source of interstitial number conc field
    character(len= 32)          :: camname_num_a    ! constituent standard name for number mixing ratio of interstitial species
    character(len=  1)          :: source_num_c     ! source of cloud borne number conc field
    character(len= 32)          :: camname_num_c    ! constituent standard name for number mixing ratio of cloud borne species
    character(len=  1), pointer :: source_mmr_a(:)  ! source of interstitial specie mmr fields
    character(len= 32), pointer :: camname_mmr_a(:) ! constituent standard name for mmr of interstitial components
    character(len=  1), pointer :: source_mmr_c(:)  ! source of cloud borne specie mmr fields
    character(len= 32), pointer :: camname_mmr_c(:) ! constituent standard name for mmr of cloud borne components
    character(len= 32), pointer :: type(:)          ! specie type (as used in MAM code)
    character(len=256), pointer :: props(:)         ! file containing specie properties
    integer                     :: idx_num_a        ! constituent index for number mixing ratio of interstitial species
    integer                     :: idx_num_c        ! constituent index for number mixing ratio of cloud borne species
    integer,            pointer :: idx_mmr_a(:)     ! constituent index for mmr of interstitial species
    integer,            pointer :: idx_mmr_c(:)     ! constituent index for mmr of cloud borne species
    integer,            pointer :: idx_props(:)     ! ID used to access physical properties of mode species from phys_prop
  end type mode_component_t

  ! Type to provide access to all modes
  type, public :: modes_t
    integer :: nmodes
    character(len= 32),     pointer :: names(:) ! names used to identify a mode in the climate/diag lists
    character(len= 32),     pointer :: types(:) ! type of mode (as used in MAM code)
    type(mode_component_t), pointer :: comps(:) ! components which define the mode
  end type modes_t

  ! mode definition object
  type(modes_t), target, public :: modes

  !----------------------------------------------------------------------
  ! Internal to this module
  !----------------------------------------------------------------------
  integer, parameter :: num_spec_types = 8
  character(len=9), parameter :: spec_type_names(num_spec_types) = (/ &
                                 'sulfate  ', 'ammonium ', 'nitrate  ', 'p-organic', &
                                 's-organic', 'black-c  ', 'seasalt  ', 'dust     '/)

  integer, parameter :: num_mode_types = 9
  character(len=14), parameter :: mode_type_names(num_mode_types) = (/ &
                                  'accum         ', 'aitken        ', 'primary_carbon', 'fine_seasalt  ', &
                                  'fine_dust     ', 'coarse        ', 'coarse_seasalt', 'coarse_dust   ', &
                                  'coarse_strat  '/)

contains

  ! Parse the mode definition specifiers.  The specifiers are of the form:
  !
  ! 'mode_name:mode_type:=',
  !  'source_num_a:camname_num_a:source_num_c:camname_num_c:num_mr:+',
  !  'source_mmr_a:camname_mmr_a:source_mmr_c:camname_mmr_c:spec_type:prop_file[:+]'[,]
  !  ['source_mmr_a:camname_mmr_a:source_mmr_c:camname_mmr_c:spec_type:prop_file][:+][']
  !
  ! where the ':' separated fields are:
  ! mode_name     -- name of the mode.
  ! mode_type     -- type of mode.  Valid values are from the MAM code.
  ! =             -- this line terminator identifies the initial string in a
  !                  mode definition
  ! +             -- this line terminator indicates that the mode definition is
  !                  continued in the next string
  ! source_num_a  -- Source of interstitial number mixing ratio,  'A', 'N', or 'Z'
  ! camname_num_a -- the name of the interstitial number component.
  !                  Always registered in the constituent arrays (A or N)
  ! source_num_c  -- Source of cloud borne number mixing ratio,  'A', 'N', or 'Z'
  ! camname_num_c -- the name of the cloud borne number component.
  !                  Always registered in the constituent arrays (A or N)
  ! source_mmr_a  -- Source of interstitial specie mass mixing ratio,  'A', 'N' or 'Z'
  ! camname_mmr_a -- the name of the interstitial specie.
  !                  Always registered in the constituent arrays (A or N)
  ! source_mmr_c  -- Source of cloud borne specie mass mixing ratio,  'A', 'N' or 'Z'
  ! camname_mmr_c -- the name of the cloud borne specie.
  !                  Always registered in the constituent arrays (A or N)
  ! spec_type     -- species type.  Valid values far from the MAM code, except that
  !                  the value 'num_mr' designates a number mixing ratio and has no
  !                  associated field for the prop_file.  There can only be one entry
  !                  with the num_mr type in a mode definition.
  ! prop_file     -- For aerosol species this is a filename, which is
  !                  identified by a ".nc" suffix.  The file contains optical and
  !                  other physical properties of the aerosol.
  !
  ! A mode definition must contain only 1 string for the number mixing ratio components
  ! and at least 1 string for the species.
  subroutine parse_mode_defs(nl_in, modes)
    use cam_logfile,                  only: iulog
    use cam_abortutils,               only: endrun, check_allocate
    use shr_kind_mod,                 only: shr_kind_cm

    character(len=*), intent(inout) :: nl_in(:)    ! namelist input (blanks are removed on output)
    type(modes_t),    intent(inout) :: modes       ! structure containing parsed input

    ! Local variables
    integer :: m
    integer :: nmodes, nstr
    integer :: mbeg, mcur
    integer :: nspec, ispec
    integer :: strlen, iend, ipos
    logical :: num_mr_found
    character(len=len(nl_in(1))) :: tmpstr
    character(len=1)  :: tmp_src_a
    character(len=32) :: tmp_name_a
    character(len=1)  :: tmp_src_c
    character(len=32) :: tmp_name_c
    character(len=32) :: tmp_type

    integer                      :: errflg
    character(len=shr_kind_cm)   :: errmsg
    character(len=*), parameter  :: subname = 'parse_mode_defs'

    ! Determine number of modes defined by counting number of strings that are
    ! terminated by ':='
    ! (algorithm stops counting at first blank element).
    nmodes = 0
    nstr = 0
    do m = 1, n_mode_str

      if (len_trim(nl_in(m)) == 0) exit
      nstr = nstr + 1

      ! There are no fields in the input strings in which a blank character is allowed.
      ! To simplify the parsing go through the input strings and remove blanks.
      tmpstr = adjustl(nl_in(m))
      nl_in(m) = tmpstr
      do
        strlen = len_trim(nl_in(m))
        ipos = index(nl_in(m), ' ')
        if (ipos == 0 .or. ipos > strlen) exit
        tmpstr = nl_in(m) (:ipos - 1)//nl_in(m) (ipos + 1:strlen)
        nl_in(m) = tmpstr
      end do
      ! count strings with ':=' terminator
      if (nl_in(m) (strlen - 1:strlen) == ':=') nmodes = nmodes + 1

    end do
    modes%nmodes = nmodes

    ! return if no modes defined
    if (nmodes == 0) return

    ! allocate components that depend on nmodes
    allocate ( &
      modes%names(nmodes), &
      modes%types(nmodes), &
      modes%comps(nmodes), &
      stat=errflg, errmsg=errmsg)
    call check_allocate(errflg, subname, 'modes%names, modes%types, modes%comps(nmodes)', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    mcur = 1              ! index of current string being processed

    ! loop over modes
    do m = 1, nmodes

      mbeg = mcur  ! remember the first string of a mode

      ! check that first string in mode definition is ':=' terminated
      iend = len_trim(nl_in(mcur))
      if (nl_in(mcur) (iend - 1:iend) /= ':=') call parse_error('= not found', nl_in(mcur))

      ! count species in mode definition.  definition will contain 1 string with
      ! with a ':+' terminator for each specie
      nspec = 0
      mcur = mcur + 1
      do
        iend = len_trim(nl_in(mcur))
        if (nl_in(mcur) (iend - 1:iend) /= ':+') exit
        nspec = nspec + 1
        mcur = mcur + 1
      end do

      ! a mode must have at least one specie
      if (nspec == 0) call parse_error('mode must have at least one specie', nl_in(mbeg))

      ! allocate components that depend on number of species
      allocate ( &
        modes%comps(m)%source_mmr_a(nspec), &
        modes%comps(m)%camname_mmr_a(nspec), &
        modes%comps(m)%source_mmr_c(nspec), &
        modes%comps(m)%camname_mmr_c(nspec), &
        modes%comps(m)%type(nspec), &
        modes%comps(m)%props(nspec), &
        stat=errflg, errmsg=errmsg)
      call check_allocate(errflg, subname, 'modes%comps(m)%...(nspec)', &
                          file=__FILE__, line=__LINE__, errmsg=errmsg)

      ! initialize components
      modes%comps(m)%nspec = nspec
      modes%comps(m)%source_num_a = ' '
      modes%comps(m)%camname_num_a = ' '
      modes%comps(m)%source_num_c = ' '
      modes%comps(m)%camname_num_c = ' '
      do ispec = 1, nspec
        modes%comps(m)%source_mmr_a(ispec) = ' '
        modes%comps(m)%camname_mmr_a(ispec) = ' '
        modes%comps(m)%source_mmr_c(ispec) = ' '
        modes%comps(m)%camname_mmr_c(ispec) = ' '
        modes%comps(m)%type(ispec) = ' '
        modes%comps(m)%props(ispec) = ' '
      end do

      ! return to first string in mode definition
      mcur = mbeg
      tmpstr = nl_in(mcur)

      ! mode name
      ipos = index(tmpstr, ':')
      if (ipos < 2) call parse_error('mode name not found', tmpstr)
      modes%names(m) = tmpstr(:ipos - 1)
      tmpstr = tmpstr(ipos + 1:)

      ! mode type
      ipos = index(tmpstr, ':')
      if (ipos == 0) call parse_error('mode type not found', tmpstr)
      ! check for valid mode type
      call check_mode_type(tmpstr, 1, ipos - 1)
      modes%types(m) = tmpstr(:ipos - 1)
      tmpstr = tmpstr(ipos + 1:)

      ! mode type must be followed by '='
      if (tmpstr(1:1) /= '=') call parse_error('= not found', tmpstr)

      ! move to next string
      mcur = mcur + 1
      tmpstr = nl_in(mcur)

      ! process mode component strings
      num_mr_found = .false.   ! keep track of whether number mixing ratio component is found
      ispec = 0                ! keep track of the number of species found
      do

        ! source of interstitial component
        ipos = index(tmpstr, ':')
        if (ipos < 2) call parse_error('expect to find source field first', tmpstr)
        ! check for valid source
        if (tmpstr(:ipos - 1) /= 'A' .and. tmpstr(:ipos - 1) /= 'N' .and. tmpstr(:ipos - 1) /= 'Z') &
          call parse_error('source must be A, N or Z', tmpstr)
        tmp_src_a = tmpstr(:ipos - 1)
        tmpstr = tmpstr(ipos + 1:)

        ! name of interstitial component
        ipos = index(tmpstr, ':')
        if (ipos == 0) call parse_error('next separator not found', tmpstr)
        tmp_name_a = tmpstr(:ipos - 1)
        tmpstr = tmpstr(ipos + 1:)

        ! source of cloud borne component
        ipos = index(tmpstr, ':')
        if (ipos < 2) call parse_error('expect to find a source field', tmpstr)
        ! check for valid source
        if (tmpstr(:ipos - 1) /= 'A' .and. tmpstr(:ipos - 1) /= 'N' .and. tmpstr(:ipos - 1) /= 'Z') &
          call parse_error('source must be A, N or Z', tmpstr)
        tmp_src_c = tmpstr(:ipos - 1)
        tmpstr = tmpstr(ipos + 1:)

        ! name of cloud borne component
        ipos = index(tmpstr, ':')
        if (ipos == 0) call parse_error('next separator not found', tmpstr)
        tmp_name_c = tmpstr(:ipos - 1)
        tmpstr = tmpstr(ipos + 1:)

        ! component type
        ipos = scan(tmpstr, ': ')
        if (ipos == 0) call parse_error('next separator not found', tmpstr)

        if (tmpstr(:ipos - 1) == 'num_mr') then

          ! there can only be one number mixing ratio component
          if (num_mr_found) call parse_error('more than 1 number component', nl_in(mcur))

          num_mr_found = .true.
          modes%comps(m)%source_num_a = tmp_src_a
          modes%comps(m)%camname_num_a = tmp_name_a
          modes%comps(m)%source_num_c = tmp_src_c
          modes%comps(m)%camname_num_c = tmp_name_c
          tmpstr = tmpstr(ipos + 1:)

        else

          ! check for valid specie type
          call check_specie_type(tmpstr, 1, ipos - 1)
          tmp_type = tmpstr(:ipos - 1)
          tmpstr = tmpstr(ipos + 1:)

          ! get the properties file
          ipos = scan(tmpstr, ': ')
          if (ipos == 0) call parse_error('next separator not found', tmpstr)
          ! check for valid filename -- must have .nc extension
          if (tmpstr(ipos - 3:ipos - 1) /= '.nc') &
            call parse_error('filename not valid', tmpstr)

          ispec = ispec + 1
          modes%comps(m)%source_mmr_a(ispec) = tmp_src_a
          modes%comps(m)%camname_mmr_a(ispec) = tmp_name_a
          modes%comps(m)%source_mmr_c(ispec) = tmp_src_c
          modes%comps(m)%camname_mmr_c(ispec) = tmp_name_c
          modes%comps(m)%type(ispec) = tmp_type
          modes%comps(m)%props(ispec) = tmpstr(:ipos - 1)
          tmpstr = tmpstr(ipos + 1:)
        end if

        ! check if there are more components.  either the current character is
        ! a ' ' which means this string is the final mode component, or the character
        ! is a '+' which means there are more components
        if (tmpstr(1:1) == ' ') exit

        if (tmpstr(1:1) /= '+') &
          call parse_error('+ field not found', tmpstr)

        ! continue to next component...
        mcur = mcur + 1
        tmpstr = nl_in(mcur)
      end do

      ! check that a number component was found
      if (.not. num_mr_found) call parse_error('number component not found', nl_in(mbeg))

      ! check that the right number of species were found
      if (ispec /= nspec) call parse_error('component parsing got wrong number of species', nl_in(mbeg))

      ! continue to next mode...
      mcur = mcur + 1
      tmpstr = nl_in(mcur)
    end do

  contains
    ! internal subroutines used for error checking and reporting
    subroutine parse_error(msg, str)
      character(len=*), intent(in) :: msg
      character(len=*), intent(in) :: str

      write (iulog, *) subname//': ERROR: '//msg
      write (iulog, *) ' input string: '//trim(str)
      call endrun(subname//': ERROR: '//msg)
    end subroutine parse_error

    subroutine check_specie_type(str, ib, ie)
      character(len=*), intent(in) :: str
      integer, intent(in) :: ib, ie

      integer :: i

      do i = 1, num_spec_types
        if (str(ib:ie) == trim(spec_type_names(i))) return
      end do

      call parse_error('specie type not valid', str(ib:ie))
    end subroutine check_specie_type

    subroutine check_mode_type(str, ib, ie)
      character(len=*), intent(in) :: str
      integer, intent(in) :: ib, ie  ! begin, end character of mode type substring

      integer :: i

      do i = 1, num_mode_types
        if (str(ib:ie) == trim(mode_type_names(i))) return
      end do

      call parse_error('mode type not valid', str(ib:ie))
    end subroutine check_mode_type
  end subroutine parse_mode_defs

  ! Initialize the mode definitions by looking up the relevent indices in the
  ! constituent properties object, and getting the physprop IDs
  subroutine init_mode_comps(modes)
    use cam_abortutils,               only: endrun, check_allocate
    use shr_kind_mod,                 only: shr_kind_cm

    use ccpp_scheme_utils,            only: ccpp_constituent_index
    use aerosol_physical_properties,  only: physprop_get_id

    ! Arguments
    type(modes_t), intent(inout) :: modes

    ! Local variables
    integer :: m, ispec, nspec
    integer                      :: errflg
    character(len=shr_kind_cm)   :: errmsg
    character(len=*), parameter  :: subname = 'init_mode_comps'

    mode_loop: do m = 1, modes%nmodes
      ! Number mixing ratio components (interstitial and cloud borne):
      if(modes%comps(m)%source_num_a(1:1) == 'Z') then
        modes%comps(m)%idx_num_a = -1
      else
        call ccpp_constituent_index(trim(modes%comps(m)%camname_num_a), &
                                    modes%comps(m)%idx_num_a, errflg, errmsg)
        if(errflg /= 0) call endrun(subname//': '//errmsg)
        if(modes%comps(m)%idx_num_a < 0) call endrun(subname//': cannot find constituent '//trim(modes%comps(m)%camname_num_a))
      end if

      if(modes%comps(m)%source_num_a(1:1) == 'Z') then
        modes%comps(m)%idx_num_c = -1
      else
        call ccpp_constituent_index(trim(modes%comps(m)%camname_num_c), &
                                    modes%comps(m)%idx_num_c, errflg, errmsg)
        if(errflg /= 0) call endrun(subname//': '//errmsg)
        if(modes%comps(m)%idx_num_c < 0) call endrun(subname//': cannot find constituent '//trim(modes%comps(m)%camname_num_c))
      end if

      ! Allocate memory for species (individual species MMR under each mode)
      ! e.g., so4_a1, ncl_a1, dst_a1 are all mode 1 MMRs ... num_a1 one number concentration.
      nspec = modes%comps(m)%nspec
      allocate( &
        modes%comps(m)%idx_mmr_a(nspec), &
        modes%comps(m)%idx_mmr_c(nspec), &
        modes%comps(m)%idx_props(nspec), stat=errflg, errmsg=errmsg)
      call check_allocate(errflg, subname, 'modes%comps(m)%idx_mmr_a, idx_mmr_c, idx_props(nspec)', &
                          file=__FILE__, line=__LINE__, errmsg=errmsg)

      spec_loop: do ispec = 1, nspec
        ! Indices for species mixing ratio components:
        ! Interstitial species mass mixing ratio
        if (modes%comps(m)%source_mmr_a(ispec)(1:1) == 'Z') then
          modes%comps(m)%idx_mmr_a(ispec) = -1
        else
          call ccpp_constituent_index(trim(modes%comps(m)%camname_mmr_a(ispec)), &
                                      modes%comps(m)%idx_mmr_a(ispec), errflg, errmsg)
          if (errflg /= 0) call endrun(subname//': '//errmsg)
          if (modes%comps(m)%idx_mmr_a(ispec) < 0) &
            call endrun(subname//': cannot find constituent '//trim(modes%comps(m)%camname_mmr_a(ispec)))
        end if

        ! Cloud-borne species mass mixing ratio
        if (modes%comps(m)%source_mmr_c(ispec)(1:1) == 'Z') then
          modes%comps(m)%idx_mmr_c(ispec) = -1
        else
          call ccpp_constituent_index(trim(modes%comps(m)%camname_mmr_c(ispec)), &
                                      modes%comps(m)%idx_mmr_c(ispec), errflg, errmsg)
          if (errflg /= 0) call endrun(subname//': '//errmsg)
          if (modes%comps(m)%idx_mmr_c(ispec) < 0) &
            call endrun(subname//': cannot find constituent '//trim(modes%comps(m)%camname_mmr_c(ispec)))
        end if

        ! Get physprop ID
        modes%comps(m)%idx_props(ispec) = physprop_get_id(modes%comps(m)%props(ispec))
        if (modes%comps(m)%idx_props(ispec) == -1) then
          call endrun(subname//': ERROR physprop idx not found for '//trim(modes%comps(m)%props(ispec)))
        end if
      end do spec_loop
    end do mode_loop

  end subroutine init_mode_comps

end module radiative_aerosols_modal

! Sectional support types and subroutines for radiative_aerosols.
!
! The contents of this file were split off from the original CAM rad_constituents
! for types and subroutines pertaining to specifically sectional aerosol.
module radiative_aerosols_sectional

  implicit none
  private

  public :: parse_bin_defs
  public :: init_bin_comps

  !----------------------------------------------------------------------
  ! Public module types for use by radiative_aerosols module:
  !----------------------------------------------------------------------

  ! Maximum size of bin definition namelist string.
  integer, parameter, public   :: n_bin_str  = 640

  ! Type to provide access to the components of a bin
  type, public :: bin_component_t
    integer :: nspec                                ! # of species per bin (dimension for below arrays:)

    character(len=1)            :: source_num_a     ! source of interstitial number conc field
    character(len=32)           :: camname_num_a    ! constituent standard name for number mixing ratio of interstitial species
    character(len=1)            :: source_num_c     ! source of cloud borne number conc field
    character(len=32)           :: camname_num_c    ! constituent standard name for number mixing ratio of cloud borne species

    character(len=1)            :: source_mass_a    ! source of interstitial number conc field
    character(len=32)           :: camname_mass_a   ! constituent standard name for number mixing ratio of interstitial species
    character(len=1)            :: source_mass_c    ! source of cloud borne number conc field
    character(len=32)           :: camname_mass_c   ! constituent standard name for number mixing ratio of cloud borne species

    character(len=1),   pointer :: source_mmr_a(:)  ! source of interstitial mmr field
    character(len=32),  pointer :: camname_mmr_a(:) ! constituent standard name for mmr species
    character(len=1),   pointer :: source_mmr_c(:)  ! source of cloud borne specie mmr fields
    character(len=32),  pointer :: camname_mmr_c(:) ! constituent standard name for mmr of cloud borne components
    character(len=32),  pointer :: type(:)          ! species type
    character(len=32),  pointer :: morph(:)         ! species morphology
    character(len=256), pointer :: props(:)         ! file containing specie properties

    integer                     :: idx_num_a        ! constituent index for number mixing ratio of interstitial species
    integer                     :: idx_num_c        ! constituent index for number mixing ratio of cloud-borne species
    integer                     :: idx_mass_a       ! constituent index for mass mixing ratio of interstitial species
    integer                     :: idx_mass_c       ! constituent index for mass mixing ratio of cloud-borne species

    integer,            pointer :: idx_mmr_a(:)     ! constituent index for mmr of interstitial species
    integer,            pointer :: idx_mmr_c(:)     ! constituent index for mmr of cloud-borne species
    integer,            pointer :: idx_props(:)     ! ID used to access physical properties of mode species from phys_prop module
  end type bin_component_t

  ! Type to provide access to all bins
  type, public :: bins_t
    integer :: nbins
    character(len=32),     pointer :: names(:) ! names used to identify a mode in the climate/diag lists
    type(bin_component_t), pointer :: comps(:) ! components which define the mode
  end type bins_t

  ! Bin definition object
  type(bins_t), target, public :: bins

  !----------------------------------------------------------------------
  ! Internal to this module
  !----------------------------------------------------------------------
  integer, parameter :: num_spec_types = 8
  character(len=9), parameter :: spec_type_names(num_spec_types) = (/ &
                                 'sulfate  ', 'ammonium ', 'nitrate  ', 'p-organic', &
                                 's-organic', 'black-c  ', 'seasalt  ', 'dust     '/)
  integer, parameter :: num_bin_morphs = 2
  character(len=8), parameter :: bin_morph_names(num_bin_morphs) = &
                                 (/'shell   ', 'core    '/)

contains
  ! Parse the bin definition specifiers.  The specifiers are of the form:
  !
  ! 'bin_name:=',
  !  'source_num_a:camname_num_a:source_num_c:camname_num_c:num_mr:+',
  !  'source_mmr_a:camname_mmr_a:source_mmr_c:camname_mmr_c:spec_type:prop_file[:+]'[,]
  !  ['source_mmr_a:camname_mmr_a:source_mmr_c:camname_mmr_c:spec_type:prop_file][:+][']
  !
  ! where the ':' separated fields are:
  ! bin_name -- name of the bin.
  ! =         -- this line terminator identifies the initial string in a
  !              mode definition
  ! +         -- this line terminator indicates that the mode definition is
  !              continued in the next string
  ! source_num_a  -- Source of interstitial number mixing ratio,  'A', 'N', or 'Z'
  ! camname_num_a -- the name of the interstitial number component.  This name must be
  !                  registered in the constituent arrays when source=A or in the
  !                  physics buffer when source=N
  ! source_num_c  -- Source of cloud borne number mixing ratio,  'A', 'N', or 'Z'
  ! camname_num_c -- the name of the cloud borne number component.  This name must be
  !                  registered in the constituent arrays when source=A or in the
  !                  physics buffer when source=N
  ! source_mmr_a  -- Source of interstitial specie mass mixing ratio,  'A', 'N' or 'Z'
  ! camname_mmr_a -- the name of the interstitial specie.  This name must be
  !                  registered in the constituent arrays when source=A or in the
  !                  physics buffer when source=N
  ! source_mmr_c  -- Source of cloud borne specie mass mixing ratio,  'A', 'N' or 'Z'
  ! camname_mmr_c -- the name of the cloud borne specie.  This name must be
  !                  registered in the constituent arrays when source=A or in the
  !                  physics buffer when source=N
  ! spec_type -- species type.  Valid values are particle, shell, and core.
  ! prop_file -- For aerosol species this is a filename, which is
  !              identified by a ".nc" suffix.  The file contains optical and
  !              other physical properties of the aerosol.
  !
  ! A bin definition must contain at least 1 string for the species and can contain
  ! a maximum of 1 particle type.
  subroutine parse_bin_defs(nl_in, bins)
    use cam_logfile,                  only: iulog
    use cam_abortutils,               only: endrun, check_allocate
    use shr_kind_mod,                 only: shr_kind_cm

    character(len=*), intent(inout) :: nl_in(:)    ! namelist input (blanks are removed on output)
    type(bins_t),     intent(inout) :: bins        ! structure containing parsed input

    ! Local variables
    logical :: num_mr_found, mass_mr_found
    logical :: particle_mr_found
    integer :: m
    integer :: nbins, nstr, istr
    integer :: mbeg, mcur
    integer :: nspec, ispec
    integer :: strlen, ibeg, iend, ipos
    logical :: part_mr_found

    character(len=len(nl_in(1))) :: tmpstr
    character(len=1)  :: tmp_src_a
    character(len=32) :: tmp_name_a
    character(len=1)  :: tmp_src_c
    character(len=32) :: tmp_name_c
    character(len=32) :: tmp_type
    character(len=32) :: tmp_morph

    integer                      :: errflg
    character(len=shr_kind_cm)   :: errmsg
    character(len=*), parameter  :: subname = 'parse_bin_defs'

    ! Determine number of bins defined by counting number of strings that are
    ! terminated by ':='
    ! (algorithm stops counting at first blank element).
    nbins = 0
    nstr = 0
    do m = 1, n_bin_str

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
      if (nl_in(m) (strlen - 1:strlen) == ':=') nbins = nbins + 1

    end do
    bins%nbins = nbins

    ! return if no bins defined
    if (nbins == 0) return

    ! allocate components that depend on nmodes
    allocate ( &
      bins%names(nbins), &
      bins%comps(nbins), &
      stat=errflg, errmsg=errmsg)
    call check_allocate(errflg, subname, 'bins%names, bins%comps(nbins)', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    mcur = 1              ! index of current string being processed

    ! loop over bins
    bins_loop: do m = 1, nbins

      mbeg = mcur  ! remember the first string of a bin

      ! check that first string in bin definition is ':=' terminated
      iend = len_trim(nl_in(mcur))
      if (nl_in(mcur) (iend - 1:iend) /= ':=') call parse_error('= not found', nl_in(mcur))

      ! count species in bin definition.  definition will contain 1 string with
      ! with a ':+' terminator for each specie
      nspec = 0
      mcur = mcur + 1
      do
        iend = len_trim(nl_in(mcur))
        if (nl_in(mcur) (iend - 1:iend) /= ':+') exit
        if (nl_in(mcur) (iend - 4:iend) /= 'mmr:+') nspec = nspec + 1
        mcur = mcur + 1
      end do

      ! a bin must have at least one specie
      if (nspec == 0) call parse_error('bin must have at least one specie', nl_in(mbeg))

      ! allocate components that depend on number of species
      allocate ( &
        bins%comps(m)%source_mmr_a(nspec), &
        bins%comps(m)%camname_mmr_a(nspec), &
        bins%comps(m)%source_mmr_c(nspec), &
        bins%comps(m)%camname_mmr_c(nspec), &
        bins%comps(m)%type(nspec), &
        bins%comps(m)%morph(nspec), &
        bins%comps(m)%props(nspec), &
        stat=errflg, errmsg=errmsg)

      call check_allocate(errflg, subname, 'bins%comps(m)%...(nspec)', &
                          file=__FILE__, line=__LINE__, errmsg=errmsg)

      ! initialize components
      bins%comps(m)%nspec = nspec
      bins%comps(m)%source_num_a = ' '
      bins%comps(m)%camname_num_a = ' '
      bins%comps(m)%source_num_c = ' '
      bins%comps(m)%camname_num_c = ' '
      bins%comps(m)%source_mass_a = 'U'           ! unset
      bins%comps(m)%camname_mass_a = 'NOTSET'
      bins%comps(m)%source_mass_c = 'U'           ! unset
      bins%comps(m)%camname_mass_c = 'NOTSET'
      do ispec = 1, nspec
        bins%comps(m)%source_mmr_a(ispec) = ' '
        bins%comps(m)%camname_mmr_a(ispec) = ' '
        bins%comps(m)%source_mmr_c(ispec) = ' '
        bins%comps(m)%camname_mmr_c(ispec) = ' '
        bins%comps(m)%type(ispec) = ' '
        bins%comps(m)%props(ispec) = ' '
      end do

      ! return to first string in mode definition
      mcur = mbeg
      tmpstr = nl_in(mcur)

      ! bin name
      ipos = index(tmpstr, ':')
      if (ipos < 2) call parse_error('bin name not found', tmpstr)
      bins%names(m) = tmpstr(:ipos - 1)
      tmpstr = tmpstr(ipos + 1:)

      ! bin name must be followed by '='
      if (tmpstr(1:1) /= '=') call parse_error('= not found', tmpstr)

      ! move to next string
      mcur = mcur + 1
      tmpstr = nl_in(mcur)

      ! process bin component strings
      particle_mr_found = .false.   ! keep track of whether particle mixing ratio component is found
      num_mr_found = .false.        ! keep track of whether number mixing ratio component is found
      mass_mr_found = .false.       ! keep track of whether number mixing ratio component is found
      ispec = 0                     ! keep track of the number of species found
      comps_loop: do

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

        if (tmpstr(:ipos - 1) == 'num') then

          ! there can only be one number mixing ratio component
          if (num_mr_found) call parse_error('more than 1 number component', nl_in(mcur))

          num_mr_found = .true.
          bins%comps(m)%source_num_a = tmp_src_a
          bins%comps(m)%camname_num_a = tmp_name_a
          bins%comps(m)%source_num_c = tmp_src_c
          bins%comps(m)%camname_num_c = tmp_name_c
          tmpstr = tmpstr(ipos + 1:)

        else if (tmpstr(:ipos - 1) == 'mmr') then

          ! there can only be one number mixing ratio component
          if (mass_mr_found) call parse_error('more than 1 mass mixing ratio component', nl_in(mcur))

          mass_mr_found = .true.
          bins%comps(m)%source_mass_a = tmp_src_a
          bins%comps(m)%camname_mass_a = tmp_name_a
          bins%comps(m)%source_mass_c = tmp_src_c
          bins%comps(m)%camname_mass_c = tmp_name_c
          tmpstr = tmpstr(ipos + 1:)

        else

          ! check for valid species type
          call check_bin_type(tmpstr, 1, ipos - 1)
          tmp_type = tmpstr(:ipos - 1)
          tmpstr = tmpstr(ipos + 1:)

          ipos = index(tmpstr, ':')
          if (ipos == 0) call parse_error('next separator not found', tmpstr)

          ! check for valid species type
          call check_bin_morph(tmpstr, 1, ipos - 1)
          tmp_morph = tmpstr(:ipos - 1)
          tmpstr = tmpstr(ipos + 1:)

          ! get the properties file
          ipos = scan(tmpstr, ': ')
          if (ipos == 0) call parse_error('next separator not found', tmpstr)

          ! check for valid filename -- must have .nc extension
          if (tmpstr(ipos - 3:ipos - 1) /= '.nc') &
            call parse_error('filename not valid', tmpstr)

          ispec = ispec + 1

          bins%comps(m)%source_mmr_a(ispec) = tmp_src_a
          bins%comps(m)%camname_mmr_a(ispec) = tmp_name_a
          bins%comps(m)%source_mmr_c(ispec) = tmp_src_c
          bins%comps(m)%camname_mmr_c(ispec) = tmp_name_c
          bins%comps(m)%type(ispec) = tmp_type
          bins%comps(m)%morph(ispec) = tmp_morph

          bins%comps(m)%props(ispec) = tmpstr(:ipos - 1)
          tmpstr = tmpstr(ipos + 1:)

        end if

        ! check if there are more components.  either the current character is
        ! a ' ' which means this string is the final mode component, or the character
        ! is a '+' which means there are more components
        if (tmpstr(1:1) == ' ') then
          exit comps_loop
        end if

        if (tmpstr(1:1) /= '+') &
          call parse_error('+ field not found', tmpstr)

        ! continue to next component...
        mcur = mcur + 1
        tmpstr = nl_in(mcur)
      end do comps_loop

      ! check that a number component was found
      if (.not. num_mr_found) call parse_error('number component not found', nl_in(mbeg))

      ! check that the right number of species were found
      if (ispec /= nspec) then
        write (*, *) 'ispec, nspec = ', ispec, nspec
        call parse_error('component parsing got wrong number of species', nl_in(mbeg))
      end if

      ! continue to next bin...
      mcur = mcur + 1
      tmpstr = nl_in(mcur)
    end do bins_loop

    !------------------------------------------------------------------------------------------------
  contains
    !------------------------------------------------------------------------------------------------

    ! internal subroutines used for error checking and reporting

    subroutine parse_error(msg, str)

      character(len=*), intent(in) :: msg
      character(len=*), intent(in) :: str

      write (iulog, *) subname//': ERROR: '//msg
      write (iulog, *) ' input string: '//trim(str)
      call endrun(subname//': ERROR: '//msg)

    end subroutine parse_error

    !------------------------------------------------------------------------------------------------

    subroutine check_bin_morph(str, ib, ie)

      character(len=*), intent(in) :: str
      integer, intent(in) :: ib, ie

      integer :: i

      do i = 1, num_bin_morphs
        if (str(ib:ie) == trim(bin_morph_names(i))) return
      end do

      call parse_error('bin morph not valid', str(ib:ie))

    end subroutine check_bin_morph

    !------------------------------------------------------------------------------------------------
    subroutine check_bin_type(str, ib, ie)

      character(len=*), intent(in) :: str
      integer, intent(in) :: ib, ie  ! begin, end character of bin type substring

      integer :: i

      do i = 1, num_spec_types
        if (str(ib:ie) == trim(spec_type_names(i))) return
      end do

      call parse_error('bin species type not valid', str(ib:ie))

    end subroutine check_bin_type

    !------------------------------------------------------------------------------------------------

  end subroutine parse_bin_defs

  ! Initialize the bin definitions by looking up the relevent indices in the
  ! constituent and pbuf arrays, and getting the physprop IDs
  subroutine init_bin_comps(bins)
    use cam_abortutils,               only: endrun, check_allocate
    use shr_kind_mod,                 only: shr_kind_cm

    use ccpp_scheme_utils,            only: ccpp_constituent_index
    use aerosol_physical_properties,  only: physprop_get_id

    ! Arguments
    type(bins_t), intent(inout) :: bins

    ! Local variables
    integer :: m, ispec, nspec

    integer                      :: errflg
    character(len=shr_kind_cm)   :: errmsg
    character(len=*), parameter  :: subname = 'init_bin_comps'

    bin_loop: do m = 1, bins%nbins

      ! Interstitial number mixing ratio
      if (bins%comps(m)%source_num_a(1:1) == 'Z') then
        bins%comps(m)%idx_num_a = -1
      else
        call ccpp_constituent_index(trim(bins%comps(m)%camname_num_a), &
                                    bins%comps(m)%idx_num_a, errflg, errmsg)
        if (errflg /= 0) call endrun(subname//': '//errmsg)
        if (bins%comps(m)%idx_num_a < 0) &
          call endrun(subname//': cannot find constituent '//trim(bins%comps(m)%camname_num_a))
      end if

      ! Cloud-borne number mixing ratio
      if (bins%comps(m)%source_num_c(1:1) == 'Z') then
        bins%comps(m)%idx_num_c = -1
      else
        call ccpp_constituent_index(trim(bins%comps(m)%camname_num_c), &
                                    bins%comps(m)%idx_num_c, errflg, errmsg)
        if (errflg /= 0) call endrun(subname//': '//errmsg)
        if (bins%comps(m)%idx_num_c < 0) &
          call endrun(subname//': cannot find constituent '//trim(bins%comps(m)%camname_num_c))
      end if

      ! Interstitial total mass mixing ratio (optional)
      if (bins%comps(m)%source_mass_a(1:1) /= 'U' .and. bins%comps(m)%camname_mass_a /= 'NOTSET') then
        if (bins%comps(m)%source_mass_a(1:1) == 'Z') then
          bins%comps(m)%idx_mass_a = -1
        else
          call ccpp_constituent_index(trim(bins%comps(m)%camname_mass_a), &
                                      bins%comps(m)%idx_mass_a, errflg, errmsg)
          if (errflg /= 0) call endrun(subname//': '//errmsg)
          if (bins%comps(m)%idx_mass_a < 0) &
            call endrun(subname//': cannot find constituent '//trim(bins%comps(m)%camname_mass_a))
        end if
      end if

      ! Cloud-borne total mass mixing ratio (optional)
      if (bins%comps(m)%source_mass_c(1:1) /= 'U' .and. bins%comps(m)%camname_mass_c /= 'NOTSET') then
        if (bins%comps(m)%source_mass_c(1:1) == 'Z') then
          bins%comps(m)%idx_mass_c = -1
        else
          call ccpp_constituent_index(trim(bins%comps(m)%camname_mass_c), &
                                      bins%comps(m)%idx_mass_c, errflg, errmsg)
          if (errflg /= 0) call endrun(subname//': '//errmsg)
          if (bins%comps(m)%idx_mass_c < 0) &
            call endrun(subname//': cannot find constituent '//trim(bins%comps(m)%camname_mass_c))
        end if
      end if

      ! Allocate memory for species
      nspec = bins%comps(m)%nspec
      allocate( &
        bins%comps(m)%idx_mmr_a(nspec), &
        bins%comps(m)%idx_mmr_c(nspec), &
        bins%comps(m)%idx_props(nspec), stat=errflg, errmsg=errmsg)
      call check_allocate(errflg, subname, 'bins%comps(m)%idx_mmr_a, idx_mmr_c, idx_props(nspec)', &
                          file=__FILE__, line=__LINE__, errmsg=errmsg)

      spec_loop: do ispec = 1, nspec

        ! Interstitial species mass mixing ratio
        if (bins%comps(m)%source_mmr_a(ispec)(1:1) == 'Z') then
          bins%comps(m)%idx_mmr_a(ispec) = -1
        else
          call ccpp_constituent_index(trim(bins%comps(m)%camname_mmr_a(ispec)), &
                                      bins%comps(m)%idx_mmr_a(ispec), errflg, errmsg)
          if (errflg /= 0) call endrun(subname//': '//errmsg)
          if (bins%comps(m)%idx_mmr_a(ispec) < 0) &
            call endrun(subname//': cannot find constituent '//trim(bins%comps(m)%camname_mmr_a(ispec)))
        end if

        ! Cloud-borne species mass mixing ratio
        if (bins%comps(m)%source_mmr_c(ispec)(1:1) == 'Z') then
          bins%comps(m)%idx_mmr_c(ispec) = -1
        else
          call ccpp_constituent_index(trim(bins%comps(m)%camname_mmr_c(ispec)), &
                                      bins%comps(m)%idx_mmr_c(ispec), errflg, errmsg)
          if (errflg /= 0) call endrun(subname//': '//errmsg)
          if (bins%comps(m)%idx_mmr_c(ispec) < 0) &
            call endrun(subname//': cannot find constituent '//trim(bins%comps(m)%camname_mmr_c(ispec)))
        end if

        ! Get physprop ID
        bins%comps(m)%idx_props(ispec) = physprop_get_id(bins%comps(m)%props(ispec))
        if (bins%comps(m)%idx_props(ispec) == -1) then
          call endrun(subname//': ERROR idx not found for '//trim(bins%comps(m)%props(ispec)))
        end if

      end do spec_loop
    end do bin_loop

  end subroutine init_bin_comps

end module radiative_aerosols_sectional

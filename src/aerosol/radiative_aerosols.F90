! CAM-SIMA version of rad_constituents specific for aerosols.
!
! In CAM-SIMA, the rad_climate list has been split into gases and aerosols.
! This module only handles the aerosol constituents, either as an active aerosol model,
! or as prescribed values (non-advected constituents) from the prescribed_aerosols scheme.
!
! The scheme that provides the aerosol species (i.e., aero model or prescribed)
! registers the constituents; this module does not register them.
! It only retrieves the information from the constituents object,
! for interfacing with the abstract aerosol interface.
!
! Haipeng Lin, AMP/CGD/NSF NCAR, Winter 2025 - Spring 2026.
module radiative_aerosols

  use radiative_aerosols_modal,     only: n_mode_str
  use radiative_aerosols_sectional, only: n_bin_str

  implicit none
  private

  ! readnl (init 0):
  !   read namelist (rad_aer_climate...) incl. mode and bin definitions for modal and sectional aerosol models;
  !   based on this file list, accummulate unique files for aerosol_physical_properties.
  !   initialize mode (modal) and bin (sectional) objects based on namelist definition.
  public :: radiative_aerosols_readnl

  ! init 1:
  !   initialize aerosol physical properties (read physical properties)
  !   populate indices (const and physprop) in the mode and bin objects
  !   populate indices (const and physprop) in the aerosol objects
  public :: radiative_aerosols_init

  ! utility subroutines used by abstract aerosol interface and physics schemes
  ! that require information about radiatively active aerosol:
  !TODO public :: rad_cnst_get_info
  !TODO public :: rad_cnst_get_aer_props
  !TODO public :: rad_cnst_get_aer_mmr

! to implement subroutines:
! rad_cnst_get_info(list_idx, aernames=out, naero=out)
! rad_cnst_get_aer_props(ilist, bin_ndx,
!                        density_aer=out, hygro_aer=out, aername=out, refindex_aer_sw=out, refindex_aer_lw=out)
! and
!      ! refactive index table parameters
    ! call rad_cnst_get_aer_props(list_ndx, bin_ndx, &
    !      opticstype=opticstype, &
    !      sw_hygro_ext=sw_hygroscopic_ext, &
    !      sw_hygro_ssa=sw_hygroscopic_ssa, &
    !      sw_hygro_asm=sw_hygroscopic_asm, &
    !      lw_hygro_ext=lw_hygroscopic_ext, &
    !      sw_nonhygro_ext=sw_insoluble_ext, &
    !      sw_nonhygro_ssa=sw_insoluble_ssa, &
    !      sw_nonhygro_asm=sw_insoluble_asm, &
    !      lw_ext=lw_insoluble_ext, &
    !      r_sw_ext=r_sw_ext, r_sw_scat=r_sw_scat, r_sw_ascat=r_sw_ascat, &
    !      r_lw_abs=r_lw_abs, mu=r_mu )
! rad_cnst_get_aer_mmr(list_ndx, bin_ndx, self%state, self%pbuf, mmr=out)

  !----------------------------------------------------------------------
  ! Hardcoded dimensional parameters
  !----------------------------------------------------------------------
  integer, parameter         :: n_rad_cnst = 80

  !----------------------------------------------------------------------
  ! Namelist inputs
  !----------------------------------------------------------------------
  character(len=256), public :: iceopticsfile
  character(len=256), public :: liqopticsfile
  character(len=32),  public :: icecldoptics
  character(len=32),  public :: liqcldoptics
  logical,            public :: oldcldoptics = .false.

  character(len=256), dimension(n_mode_str) :: mode_defs   = ' '
  character(len=256), dimension(n_bin_str)  :: bin_defs    = ' '
  character(len=256) :: rad_aer_climate(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_1(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_2(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_3(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_4(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_5(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_6(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_7(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_8(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_9(n_rad_cnst) = ' '
  character(len=256) :: rad_aer_diag_10(n_rad_cnst) = ' '

  !----------------------------------------------------------------------
  ! Internal type containers for radiatively active aerosol.
  !----------------------------------------------------------------------

  ! type to provide access to the data parsed from the rad_climate and rad_aer_diag_* strings
  type :: rad_cnst_namelist_t
    integer :: ncnst
    character(len=  1), pointer :: source(:)  ! A         advected constituent
                                              ! N     non-advected constituent (previously pbuf)
                                              ! M          aerosol mode (modal only)
                                              ! B          aerosol bin  (sectional only)
                                              ! Z     zero value
    character(len= 64), pointer :: camname(:) ! standard name of constituent
    character(len=256), pointer :: radname(:) ! radname is the name as identfied in radiation,
                                              ! /fullpath/physprop.nc
    character(len=  1), pointer :: type(:)    ! A        aerosol
                                              ! M        aerosol mode (modal only)
                                              ! B        aerosol bin  (sectional only)
  end type rad_cnst_namelist_t

  ! Storage for bulk aerosol components in the climate/diagnostic lists
  type :: aerosol_t
    character(len=1)   :: source              ! A         advected constituent
                                              ! N     non-advected constituent (previously pbuf)
                                              ! Z     zero value
    integer            :: idx                 ! index of constituent
    character(len=64)  :: camname             ! standard name of constituent

    ! for interacting with aerosol_physical_properties:
    character(len=256) :: physprop_file       ! filename of netcdf containing phys. props.
    integer            :: physprop_id         ! ID to access from phys_prop

    character(len=32)  :: mass_name           ! name for mass per layer field in history output
  end type aerosol_t

  ! Storage for any aerosol in the climate/diagnostic lists
  type :: aerlist_t
    integer                  :: numaerosols   ! # of aerosols
    type(aerosol_t), pointer :: aer(:)        ! dimension(numaerosols)

    ! diagnostic name only:
    ! set to "  " for climate list, or two character integer (e.g. 02) for diag list.
    character(len=2)         :: hist_suffix
  end type aerlist_t

  ! Storage for modal aerosol components (modes) in the climate/diagnostic lists
  ! TODO: this is a partial stub
  type :: modelist_t
    integer            :: nmodes              ! # of modes
    integer, pointer   :: idx(:)              ! index of the mode in the "modes" object

    ! for interacting with aerosol_physical_properties:
    character(len=256), pointer :: physprop_files(:)   ! filenames of netcdf containing phys. props.
    integer, pointer            :: physprop_ids(:)     ! IDs to access from phys_prop

    character(len=32)  :: mass_name           ! name for mass per layer field in history output

    ! diagnostic name only:
    ! set to "  " for climate list, or two character integer (e.g. 02) for diag list.
    character(len=2)         :: hist_suffix
  end type modelist_t

  ! Storage for sectional aerosol components (bins) in the climate/diagnostic lists
  ! TODO: this is a partial stub
  type :: binlist_t
    integer            :: nbins               ! # of bins
    integer, pointer   :: idx(:)              ! index of the bin in the "bins" object

    ! for interacting with aerosol_physical_properties:
    character(len=256), pointer :: physprop_files(:)   ! filenames of netcdf containing phys. props.
    integer, pointer            :: physprop_ids(:)     ! IDs to access from phys_prop

    character(len=32)  :: mass_name           ! name for mass per layer field in history output

    ! diagnostic name only:
    ! set to "  " for climate list, or two character integer (e.g. 02) for diag list.
    character(len=2)         :: hist_suffix
  end type binlist_t

  ! for below aerosol and call lists:
  ! index 0         = climate list (always active)
  !       1..N_DIAG = diagnostic

  integer, parameter        :: N_DIAG = 10

  ! container to hold namelist inputs
  type(rad_cnst_namelist_t) :: namelist(0:N_DIAG)

  ! list of aerosols used in climate/diagnostic calcs
  type(aerlist_t),   target :: aerosol_list(0:N_DIAG)

  ! list of aerosol modes (modal aerosols only) used in climate/diagnostic calcs
  type(modelist_t),  target :: aerosol_mode_list(0:N_DIAG)

  ! list of aerosol bins (sectional aerosols only) used in climate/diagnostic cals
  type(binlist_t),   target :: aerosol_bin_list(0:N_DIAG)

  ! which radiation calls are active [flag]
  logical                   :: active_calls(0:N_DIAG) = .false.

contains

  ! Read and parse the namelist specifier for radiatively active aerosol.
  ! Accummulates the physical property filenames into a unique file filelist
  ! used by the aerosol_physical_properties module.
  subroutine radiative_aerosols_readnl(nlfile)
    use shr_nl_mod,                   only: find_group_name => shr_nl_find_group_name
    use shr_kind_mod,                 only: shr_kind_cm
    use mpi,                          only: mpi_character, mpi_logical
    use spmd_utils,                   only: mpicom, masterproc
    use cam_logfile,                  only: iulog
    use cam_abortutils,               only: endrun

    use radiative_aerosols_modal,     only: parse_mode_defs, modes
    use radiative_aerosols_sectional, only: parse_bin_defs, bins

    use aerosol_physical_properties,  only: physprop_accum_unique_files

    ! filepath for file containing namelist input
    character(len=*), intent(in) :: nlfile

    ! Local variables
    integer                      :: unitn, i
    character(len=2)             :: suffix
    character(len=1), pointer    :: ctype(:)
    character(len=*), parameter  :: subname = 'radiative_aerosols_readnl'

    integer                      :: errflg
    character(len=shr_kind_cm)   :: errmsg

    namelist /rad_cnst_nl/ mode_defs,        &
                           bin_defs,         &
                           rad_aer_climate,  &  ! for climate calculations
                           rad_aer_diag_1,   &  ! 1 through 10 are for diagnostics only.
                           rad_aer_diag_2,   &
                           rad_aer_diag_3,   &
                           rad_aer_diag_4,   &
                           rad_aer_diag_5,   &
                           rad_aer_diag_6,   &
                           rad_aer_diag_7,   &
                           rad_aer_diag_8,   &
                           rad_aer_diag_9,   &
                           rad_aer_diag_10,  &
                           iceopticsfile,    &
                           liqopticsfile,    &
                           icecldoptics,     &
                           liqcldoptics,     &
                           oldcldoptics

    errmsg = ''

    ! Read namelist
    if (masterproc) then
       open(newunit=unitn, file=trim(nlfile), status='old')
       call find_group_name(unitn, 'rad_cnst_nl', status=errflg)
       if (errflg == 0) then
          read(unitn, rad_cnst_nl, iostat=errflg, iomsg=errmsg)
          if (errflg /= 0) then
             call endrun(subname // ':: ERROR reading namelist: ' // trim(errmsg))
          end if
       end if
       close(unitn)
    end if

    ! Broadcast namelist variables
    call mpi_bcast(mode_defs,       len(mode_defs(1))*n_mode_str,       mpi_character, 0, mpicom, errflg)
    call mpi_bcast(bin_defs,        len(bin_defs(1))*n_bin_str,         mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_climate, len(rad_aer_climate(1))*n_rad_cnst, mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_1,  len(rad_aer_diag_1(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_2,  len(rad_aer_diag_2(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_3,  len(rad_aer_diag_3(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_4,  len(rad_aer_diag_4(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_5,  len(rad_aer_diag_5(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_6,  len(rad_aer_diag_6(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_7,  len(rad_aer_diag_7(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_8,  len(rad_aer_diag_8(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_9,  len(rad_aer_diag_9(1))*n_rad_cnst,  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(rad_aer_diag_10, len(rad_aer_diag_10(1))*n_rad_cnst, mpi_character, 0, mpicom, errflg)
    call mpi_bcast(iceopticsfile,   len(iceopticsfile),                 mpi_character, 0, mpicom, errflg)
    call mpi_bcast(liqopticsfile,   len(liqopticsfile),                 mpi_character, 0, mpicom, errflg)
    call mpi_bcast(icecldoptics,    len(icecldoptics),                  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(liqcldoptics,    len(liqcldoptics),                  mpi_character, 0, mpicom, errflg)
    call mpi_bcast(oldcldoptics,    1,                                  mpi_logical,   0, mpicom, errflg)

    !-----------------------------------------------------------------------
    ! Parse the namelist input strings
    !-----------------------------------------------------------------------

    ! Mode definition strings
    call parse_mode_defs(mode_defs, modes)

    ! Bin definition strings
    call parse_bin_defs(bin_defs, bins)

    ! Lists of externally mixed entities for climate and diagnostic calculations
    do i = 0, N_DIAG
       select case (i)
       case(0)
          call parse_rad_specifier(rad_aer_climate, namelist(i))
       ! TODO: diagnostic lists are stubbed out for now. (hplin, 2/10/26)
       ! case(1)
       !    call parse_rad_specifier(rad_aer_diag_1,  namelist(i))
       ! case(2)
       !    call parse_rad_specifier(rad_aer_diag_2,  namelist(i))
       ! case(3)
       !    call parse_rad_specifier(rad_aer_diag_3,  namelist(i))
       ! case(4)
       !    call parse_rad_specifier(rad_aer_diag_4,  namelist(i))
       ! case(5)
       !    call parse_rad_specifier(rad_aer_diag_5,  namelist(i))
       ! case(6)
       !    call parse_rad_specifier(rad_aer_diag_6,  namelist(i))
       ! case(7)
       !    call parse_rad_specifier(rad_aer_diag_7,  namelist(i))
       ! case(8)
       !    call parse_rad_specifier(rad_aer_diag_8,  namelist(i))
       ! case(9)
       !    call parse_rad_specifier(rad_aer_diag_9,  namelist(i))
       ! case(10)
       !    call parse_rad_specifier(rad_aer_diag_10, namelist(i))
       end select
    end do

    ! Were there any constituents specified for the nth diagnostic call?
    ! If so, radiation will make a call with those constituents.
    active_calls(:) = (namelist(:)%ncnst > 0)

    !-----------------------------------------------------------------------
    ! Initialize the gas and aerosol lists with the information from the
    ! namelist. This is done here so that this information is available via
    ! the query functions at the time when the register methods are called.
    !-----------------------------------------------------------------------

    ! Set the hist_suffix fields which distinguish the climate and diagnostic lists
    ! in the history output names
    do i = 0, N_DIAG
       if (active_calls(i)) then
          if (i > 0) then
             write(suffix, fmt='(i2.2)') i
          else
             suffix = '  '
          end if
          aerosol_list(i)%hist_suffix       = suffix
          aerosol_mode_list(i)%hist_suffix  = suffix
          aerosol_bin_list(i)%hist_suffix   = suffix
       end if
    end do

    ! Create a list of the unique set of filenames containing property data.
    ! Start with the bulk aerosol species in the climate/diagnostic lists.
    !
    ! physprop_accum_unique_files ingests
    !   radname
    !   type
    ! and stores it in-module as uniquefilenames containing an unique set.
    do i = 0, N_DIAG
       if (active_calls(i)) then
          call physprop_accum_unique_files(namelist(i)%radname, namelist(i)%type)
       end if
    end do

    ! Add physical property files for the species from the mode definitions
    ! TODO: commented out as type definition is stubbed out
    ! do i = 1, modes%nmodes
    !    allocate(ctype(modes%comps(i)%nspec))
    !    ctype = 'A'
    !    call physprop_accum_unique_files(modes%comps(i)%props, ctype)
    !    deallocate(ctype)
    ! end do

    ! Add physical property files for the species from the bin (sectional) definitions
    ! TODO: commented out as type definition is stubbed out
    ! do i = 1, bins%nbins
    !    allocate(ctype(bins%comps(i)%nspec))
    !    ctype = 'A'
    !    call physprop_accum_unique_files(bins%comps(i)%props, ctype)
    !    deallocate(ctype)
    ! end do

  end subroutine radiative_aerosols_readnl

  ! Private method for parsing the radiation namelist specifiers.
  ! This is a separate subroutine so parsing the 0:N_DIAG specifiers can be done
  ! by calling this subroutine multiple times with the specifier string,
  ! which is reorganized by this parser into the ddt rad_cnst_namelist_t
  ! (one for each list):
  !
  ! The specifiers are of the form 'source_camname:radname' where:
  ! source  -- A      advected constituent
  !            B      sectional aerosol bin
  !            M      modal aerosol mode
  !            Z      zero
  !            N      non-advected constituent (prescribed)
  ! camname -- the standard name of the constituent.
  ! radname -- For gases this is a name that identifies the constituent to the
  !            radiative transfer codes.  These names are contained in the
  !            radconstants module.  For aerosols this is a filename, which is
  !            identified by a ".nc" suffix.  The file contains optical and
  !            other physical properties of the aerosol.
  !
  ! This code also identifies whether the constituent is a gas or an aerosol
  ! and adds that info to a structure that stores the parsed data.
  subroutine parse_rad_specifier(specifier, namelist_data)
    use cam_abortutils,     only: endrun, check_allocate
    use shr_kind_mod,       only: shr_kind_cm

    character(len=*),          dimension(:), intent(in) :: specifier
    type(rad_cnst_namelist_t),               intent(inout) :: namelist_data

    ! Local variables
    integer                    :: number, i, j
    integer                    :: ipos, strlen
    integer                    :: errflg
    character(len=shr_kind_cm) :: errmsg

    character(len=256) :: tmpstr
    character(len=1)   :: source(n_rad_cnst)
    character(len=64)  :: camname(n_rad_cnst)
    character(len=256) :: radname(n_rad_cnst)
    character(len=1)   :: type(n_rad_cnst)

    character(len=*), parameter :: subname = 'parse_rad_specifier'

    number = 0

    parse_loop: do i = 1, n_rad_cnst
      if (len_trim(specifier(i)) == 0) then
         exit parse_loop
      endif

      ! There are no fields in the input strings in which a blank character is allowed.
      ! To simplify the parsing go through the input strings and remove blanks.
      tmpstr = adjustl(specifier(i))
      do
         strlen = len_trim(tmpstr)
         ipos = index(tmpstr, ' ')
         if (ipos == 0 .or. ipos > strlen) exit
         tmpstr = tmpstr(:ipos-1) // tmpstr(ipos+1:strlen)
      end do

      ! Locate the ':' separating source from camname.
      j = index(tmpstr, ':')
      source(i) = tmpstr(:j-1)
      tmpstr = tmpstr(j+1:)

      ! locate the ':' separating camname from radname
      j = scan(tmpstr, ':')

      camname(i) = tmpstr(:j-1)
      radname(i) = tmpstr(j+1:)

      ! determine the type of constituent
      if (source(i) == 'M') then
         type(i) = 'M'
      else if (source(i) == 'B') then
         type(i) = 'B'
      else if(index(radname(i), ".nc") > 0) then
         type(i) = 'A'
      else
         call endrun(subname//': undefined type of source for radiative aerosol specifier')
      end if

      number = number+1
    end do parse_loop

    namelist_data%ncnst = number

    if (number == 0) return

    allocate(namelist_data%source (number), stat=errflg, errmsg=errmsg)
    call check_allocate(errflg, subname, 'namelist_data%source(number)', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    allocate(namelist_data%camname(number), stat=errflg, errmsg=errmsg)
    call check_allocate(errflg, subname, 'namelist_data%camname(number)', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    allocate(namelist_data%radname(number), stat=errflg, errmsg=errmsg)
    call check_allocate(errflg, subname, 'namelist_data%radname(number)', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    allocate(namelist_data%type(number), stat=errflg, errmsg=errmsg)
    call check_allocate(errflg, subname, 'namelist_data%type(number)', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    namelist_data%source(:namelist_data%ncnst)  = source (:namelist_data%ncnst)
    namelist_data%camname(:namelist_data%ncnst) = camname(:namelist_data%ncnst)
    namelist_data%radname(:namelist_data%ncnst) = radname(:namelist_data%ncnst)
    namelist_data%type(:namelist_data%ncnst)    = type(:namelist_data%ncnst)

  end subroutine parse_rad_specifier

  ! Initialize radiatively active aerosol data including physical properties
  ! based on the accummulated file list previously constructed in readnl.
  !
  ! This assumes that registration of all constituents is complete (by physics)
  !
  ! 1) the aerosol lists are initialized.
  ! 2) the mode and bin definitions are finalized.
  ! 3) indices in the constituent array are matched against lists.
  ! 4) indices in the physical properties array are matched against lists.
  ! TODO: initialize history output for climate diagnostic quantities --
  !        not sure if this should be a "physics scheme"
  subroutine radiative_aerosols_init()
    use cam_logfile,                  only: iulog
    use spmd_utils,                   only: masterproc

    use aerosol_physical_properties,  only: physprop_init

    use radiative_aerosols_modal,     only: init_mode_comps, modes
    use radiative_aerosols_sectional, only: init_bin_comps, bins

    integer :: i

    character(len=*), parameter  :: subname = 'radiative_aerosols_init'

    ! Read the physical property netCDF files to populate objects:
    call physprop_init()

    ! Initialize the mode definitions.
    call init_mode_comps(modes)

    ! Initialize the sectional bin definitions.
    call init_bin_comps(bins)

    ! Initialize the bulk aerosol, modal aerosol, and sectional aerosol lists.
    ! This step splits the input climate/diagnostic lists into the corresponding
    ! bulk, modal, and sectional aerosol lists.
    if (masterproc) write(iulog,*) subname//': Radiation constituent lists:'
    do i = 0, N_DIAG
      ! for each climate/diagnostic list..
      if (active_calls(i)) then
        ! Call first-phase initialization to set information available at readnl time
        ! (before constituents have finished registration by physics scheme)
        call list_initialize(namelist(i),          & ! below output:
                             aerosol_list(i),      &
                             aerosol_mode_list(i), &
                             aerosol_bin_list(i))

        ! TODO check debug level here.
        if (masterproc) then
           call print_lists(aerosol_list(i), aerosol_mode_list(i), aerosol_bin_list(i))
        end if
      end if
    end do

  end subroutine radiative_aerosols_init

  ! Initialize the aerosol lists with the
  ! entities specified in the climate or diagnostic lists, and populate constituent indices for non-Z.
  subroutine list_initialize(namelist, &
                             aerosol_list, aerosol_mode_list, aerosol_bin_list)
    use cam_abortutils,               only: endrun, check_allocate
    use cam_logfile,                  only: iulog
    use spmd_utils,                   only: masterproc
    use shr_kind_mod,                 only: shr_kind_cm

    use radiative_aerosols_modal,     only: modes
    use radiative_aerosols_sectional, only: bins

    use ccpp_scheme_utils,            only: ccpp_constituent_index
    use aerosol_physical_properties,  only: physprop_get_id

    ! Input arguments:
    ! parsed namelist input for climate or diagnostic lists:
    type(rad_cnst_namelist_t), intent(in)    :: namelist

    ! Input/output arguments:
    type(aerlist_t),           intent(inout) :: aerosol_list
    type(modelist_t),          intent(inout) :: aerosol_mode_list
    type(binlist_t),           intent(inout) :: aerosol_bin_list

    ! Local variables
    integer :: ii, m
    integer :: ba_idx, ma_idx, sa_idx
    integer                      :: errflg
    character(len=shr_kind_cm)   :: errmsg

    character(len=*), parameter  :: subname = 'list_initialize'

    ! Count the number of bulk aerosols and aerosol modes in the list
    aerosol_list%numaerosols = 0
    aerosol_mode_list%nmodes = 0
    aerosol_bin_list%nbins   = 0
    nl_count_loop: do ii = 1, namelist%ncnst
      if (trim(namelist%type(ii)) == 'A') aerosol_list%numaerosols = aerosol_list%numaerosols + 1
      if (trim(namelist%type(ii)) == 'M') aerosol_mode_list%nmodes = aerosol_mode_list%nmodes + 1
      if (trim(namelist%type(ii)) == 'B') aerosol_bin_list%nbins   = aerosol_bin_list%nbins + 1
    end do nl_count_loop

    ! allocate storage for the aerosol, gas, and mode lists
    allocate( &
      aerosol_list%aer(aerosol_list%numaerosols),                 & ! aerosol pointers
      aerosol_mode_list%idx           (aerosol_mode_list%nmodes), & ! ...modal data
      aerosol_mode_list%physprop_files(aerosol_mode_list%nmodes), &
      aerosol_mode_list%physprop_ids  (aerosol_mode_list%nmodes), &
      aerosol_bin_list%idx           (aerosol_bin_list%nbins),    & ! ...sectional data
      aerosol_bin_list%physprop_files(aerosol_bin_list%nbins),    &
      aerosol_bin_list%physprop_ids  (aerosol_bin_list%nbins),    &
      stat=errflg, &
      errmsg=errmsg)
    call check_allocate(errflg, subname, 'list_initialize_before_register various', &
                        file=__FILE__, line=__LINE__, errmsg=errmsg)

    if (masterproc) then
      write(iulog,*) ''
      if (len_trim(aerosol_list%hist_suffix) == 0) then
        write(iulog,*) subname//': namelist input for climate list'
      else
        write(iulog,*) subname//': namelist input for diagnostic list '//aerosol_list%hist_suffix
      end if
    end if

    ! Loop over the radiatively active components specified in the namelist
    ba_idx = 0
    ma_idx = 0
    sa_idx = 0
    nl_values_loop: do ii = 1, namelist%ncnst
      if (masterproc) then
        write(iulog,*) "  rad namelist spec: "// trim(namelist%source(ii)) &
                       //":"//trim(namelist%camname(ii))//":"//trim(namelist%radname(ii))
      end if

      ! Check that the source specifier is legal.
      ! TODO hplin check if this is necessary
      if (namelist%source(ii) /= 'A' .and. &
          namelist%source(ii) /= 'M' .and. &
          namelist%source(ii) /= 'N' .and. &
          namelist%source(ii) /= 'Z' .and. &
          namelist%source(ii) /= 'B') then
        call endrun(subname//": source must either be A, B, M, N or Z: illegal specifier in namelist input: "//namelist%source(ii))
      end if

      ! Add component to appropriate list
      if (namelist%type(ii) == 'A') then
        ! Add to bulk aerosol list
        ba_idx = ba_idx + 1

        aerosol_list%aer(ba_idx)%source        = namelist%source(ii)
        aerosol_list%aer(ba_idx)%camname       = namelist%camname(ii)
        aerosol_list%aer(ba_idx)%physprop_file = namelist%radname(ii)

      else if (namelist%type(ii) == 'M') then
        ! Add to modal aerosol list
        ma_idx = ma_idx + 1

        ! Look through the mode definitions for the name of the specified mode.  The
        ! index into the modes object all the information relevent to the mode definition.
        aerosol_mode_list%idx(ma_idx) = -1
        mode_search_loop: do m = 1, modes%nmodes
          if (trim(namelist%camname(ii)) == trim(modes%names(m))) then
              aerosol_mode_list%idx(ma_idx) = m
            exit mode_search_loop
          end if
        end do mode_search_loop

        if (aerosol_mode_list%idx(ma_idx) == -1) then
          call endrun(subname//': ERROR cannot find mode name '//trim(namelist%camname(ii)))
        end if

        ! Also save the name of the physprop file
        aerosol_mode_list%physprop_files(ma_idx) = namelist%radname(ii)

      else if (namelist%type(ii) == 'B') then
        ! Add to sectional aerosol (bin) list
        sa_idx = sa_idx + 1

        ! Look through the bin definitions for the name of the specified bin.  The
        ! index into the bins object all the information relevent to the mode definition.
        aerosol_bin_list%idx(sa_idx) = -1
        bin_search_loop: do m = 1, bins%nbins
          if (trim(namelist%camname(ii)) == trim(bins%names(m))) then
            aerosol_bin_list%idx(sa_idx) = m
            exit bin_search_loop
          end if
        end do bin_search_loop

        if (aerosol_bin_list%idx(sa_idx) == -1) then
          call endrun(subname//': ERROR cannot find bin name '//trim(namelist%camname(ii)))
        end if

        ! Also save the name of the physprop file
        aerosol_bin_list%physprop_files(sa_idx) = namelist%radname(ii)
      else
        call endrun(subname//': ERROR invalid radiative aerosol specifier for '//trim(namelist%radname(ii)))
      end if
    end do nl_values_loop

    ! Now look up indices within the constituents object.
    ! The modal and sectional number and MMR indices are managed by their modules respectively
    ! via init_mode_comps and init_bin_comps,
    ! and are not initialized here.

    ! Loop over bulk aerosols
    do ii = 1, aerosol_list%numaerosols
      if (aerosol_list%aer(ii)%source(1:1) == 'Z') then
        aerosol_list%aer(ii)%idx = -1
      else
        call ccpp_constituent_index(trim(aerosol_list%aer(ii)%camname), &
                                    aerosol_list%aer(ii)%idx, errflg, errmsg)
        if (errflg /= 0) call endrun(subname//': '//errmsg)
        if (aerosol_list%aer(ii)%idx < 0) &
          call endrun(subname//': cannot find constituent '//trim(aerosol_list%aer(ii)%camname))
      end if

      ! Get the physprop_id from the phys_prop module
      aerosol_list%aer(ii)%physprop_id = physprop_get_id(aerosol_list%aer(ii)%physprop_file)
    end do

    ! Loop over modes
    do ii = 1, aerosol_mode_list%nmodes
      aerosol_mode_list%physprop_ids(ii) = physprop_get_id(aerosol_mode_list%physprop_files(ii))
    end do

    ! Loop over bins
    do ii = 1, aerosol_bin_list%nbins
      aerosol_bin_list%physprop_ids(ii) = physprop_get_id(aerosol_bin_list%physprop_files(ii))
    end do
  end subroutine list_initialize

  ! For debug:
  ! Print summary of bulk, modal, and sectional aerosol lists.
  ! This is just the information read from the namelist.
  subroutine print_lists(aerosol_list, aerosol_mode_list, aerosol_bin_list)
    use cam_logfile,                  only: iulog

    use radiative_aerosols_modal,     only: modes
    use radiative_aerosols_sectional, only: bins

    type(aerlist_t),  intent(in) :: aerosol_list
    type(modelist_t), intent(in) :: aerosol_mode_list
    type(binlist_t),  intent(in) :: aerosol_bin_list

    integer :: i, id

    write(iulog, *) ''
    if (len_trim(aerosol_list%hist_suffix) == 0) then
      write (iulog, *) ' bulk aerosol list for climate calculations'
    else
      write (iulog, *) ' bulk aerosol list for diag'//aerosol_list%hist_suffix//' calculations'
    end if

    do i = 1, aerosol_list%numaerosols
      write (iulog, *) '  '//trim(aerosol_list%aer(i)%source)//':'//trim(aerosol_list%aer(i)%camname)// &
        ' optics and phys props in :'//trim(aerosol_list%aer(i)%physprop_file)
    end do

    write(iulog, *) ''
    if (len_trim(aerosol_mode_list%hist_suffix) == 0) then
      write (iulog, *) ' modal aerosol list for climate calculations'
    else
      write (iulog, *) ' modal aerosol list for diag'//aerosol_mode_list%hist_suffix//' calculations'
    end if

    do i = 1, aerosol_mode_list%nmodes
      id = aerosol_mode_list%idx(i)
      write (iulog, *) '  '//trim(modes%names(id))
    end do

    write(iulog, *) ''
    if (len_trim(aerosol_bin_list%hist_suffix) == 0) then
      write (iulog, *) ' bin aerosol list for climate calculations'
    else
      write (iulog, *) ' bin aerosol list for diag'//aerosol_bin_list%hist_suffix//' calculations'
    end if

    do i = 1, aerosol_bin_list%nbins
      id = aerosol_bin_list%idx(i)
      write (iulog, *) '  '//trim(bins%names(id))
    end do

  end subroutine print_lists


end module radiative_aerosols

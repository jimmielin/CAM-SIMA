! CAM-SIMA version of rad_constituents specific for aerosols.
! In CAM-SIMA, the rad_climate list has been split into gases and aerosols.
! This module only handles the aerosol constituents, either as an active aerosol model,
! or as prescribed values (non-advected constituents) from the prescribed_aerosols scheme.
!
! The scheme that provides the aerosol species (i.e., aero model or prescribed) registers the constituents;
! this module does not register them; it only retrieves the information from the constituents object,
! for interfacing with the abstract aerosol interface.
!
! A         advected constituent
! N     non-advected constituent (previously pbuf)
! Z     zero value


! to implement types:
! aerlist_t
! modelist_t
! binlist_t

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

module radiative_aerosols
  implicit none
  private

  public :: rad_cnst_get_info
  public :: rad_cnst_get_aer_props
  public :: rad_cnst_get_aer_mmr

  !----------------------------------------------------------------------
  ! Internal type containers for radiatively active aerosol.
  !----------------------------------------------------------------------

  ! Storage for bulk aerosol components in the climate/diagnostic lists
  type :: aerosol_t
     character(len=1)   :: source         ! A for state (advected), N for pbuf (non-advected), Z for zero
     character(len=64)  :: camname        ! name of constituent in physics state or buffer
     character(len=cs1) :: physprop_file  ! physprop filename
     character(len=32)  :: mass_name      ! name for mass per layer field in history output
     integer            :: idx            ! index of constituent in physics state or buffer
     integer            :: physprop_id    ! ID used to access physical properties from phys_prop module
  end type aerosol_t

  type :: aerlist_t
     integer                  :: numaerosols  ! number of aerosols
     character(len=2)         :: list_id      ! set to "  " for climate list, or two character integer
                                              ! (include leading zero) to identify diagnostic list
     type(aerosol_t), pointer :: aer(:)       ! dimension(numaerosols)
  end type aerlist_t

  type(aerlist_t), target :: aerosollist(0:N_DIAG) ! list of aerosols used in climate/diagnostic calcs

  ! hplin: below for modal...? not needed for bulk for now - UNTESTED
  !
  ! ! storage for modal aerosol components in the climate/diagnostic lists
  ! type :: modelist_t
  !    integer          :: nmodes              ! number of modes
  !    character(len=2) :: list_id             ! set to "  " for climate list, or two character integer
  !                                            ! (include leading zero) to identify diagnostic list
  !    integer,   pointer :: idx(:)            ! index of the mode in the mode definition object
  !    character(len=cs1), pointer :: physprop_files(:) ! physprop filename
  !    integer,   pointer :: idx_props(:)      ! index of the mode properties in the physprop object
  ! end type modelist_t

  ! type(modelist_t), target :: ma_list(0:N_DIAG) ! list of aerosol modes used in climate/diagnostic calcs

  ! ! storage for modal aerosol components in the climate/diagnostic lists
  ! type :: binlist_t
  !    integer          :: nbins               ! number of bins
  !    character(len=2) :: list_id             ! set to "  " for climate list, or two character integer
  !                                            ! (include leading zero) to identify diagnostic list
  !    integer,   pointer :: idx(:)            ! index of the bin in the bin definition object
  !    character(len=cs1), pointer :: physprop_files(:) ! physprop filename
  !    integer,   pointer :: idx_props(:)      ! index of the bin properties in the physprop object
  ! end type binlist_t

  ! type(binlist_t), target :: sa_list(0:N_DIAG) ! list of aerosol bins used in climate/diagnostic calcs

  ! ! type to provide access to the components of a mode
  ! type :: mode_component_t
  !    integer :: nspec
  !    ! For "source" variables below, value is:
  !    ! 'N' if non-advected constituent
  !    ! 'A' if advected     constituent
  !    character(len=  1) :: source_num_a  ! source of interstitial number conc field
  !    character(len= 32) :: camname_num_a ! name registered in constituents for number mixing ratio of interstitial species
  !    character(len=  1) :: source_num_c  ! source of cloud borne number conc field
  !    character(len= 32) :: camname_num_c ! name registered in constituents for number mixing ratio of cloud borne species
  !    character(len=  1), pointer :: source_mmr_a(:)  ! source of interstitial specie mmr fields
  !    character(len= 32), pointer :: camname_mmr_a(:) ! name registered in constituents for mmr of interstitial components
  !    character(len=  1), pointer :: source_mmr_c(:)  ! source of cloud borne specie mmr fields
  !    character(len= 32), pointer :: camname_mmr_c(:) ! name registered in constituents for mmr of cloud borne components
  !    character(len= 32), pointer :: type(:)          ! specie type (as used in MAM code)
  !    character(len=cs1), pointer :: props(:)         ! file containing specie properties
  !    integer          :: idx_num_a    ! index in constituents for number mixing ratio of interstitial species
  !    integer          :: idx_num_c    ! index in constituents (non-adv) for number mixing ratio of interstitial species
  !    integer, pointer :: idx_mmr_a(:) ! index in constituents for mmr of interstitial species
  !    integer, pointer :: idx_mmr_c(:) ! index in constituents (non-adv) for mmr of interstitial species
  !    integer, pointer :: idx_props(:) ! ID used to access physical properties of mode species from phys_prop module
  ! end type mode_component_t

  ! ! type to provide access to all modes
  ! type :: modes_t
  !    integer :: nmodes
  !    character(len= 32),     pointer :: names(:) ! names used to identify a mode in the climate/diag lists
  !    character(len= 32),     pointer :: types(:) ! type of mode (as used in MAM code)
  !    type(mode_component_t), pointer :: comps(:) ! components which define the mode
  ! end type modes_t

  ! type(modes_t), target :: modes  ! mode definitions

  ! ! type to provide access to the components of a bin
  ! type :: bin_component_t
  !    integer :: nspec
  !    ! For "source" variables below, value is:
  !    ! 'N' if non-advected constituent
  !    ! 'A' if     advected constituent

  !    ! TODO hplin -- need to port to constituent infra
  !    ! (check handling of _c cloud borne spec.)
  !    ! also check idx_props that need to be changed to aero_phys_props ccpp module
  !    character(len=  1) :: source_num_a   ! source of interstitial number conc field
  !    character(len= 32) :: camname_num_a  ! name registered in constituents for number mixing ratio of interstitial species
  !    character(len=  1) :: source_num_c   ! source of cloud borne number conc field
  !    character(len= 32) :: camname_num_c  ! name registered in constituents for number mixing ratio of cloud borne species

  !    character(len=  1) :: source_mass_a  ! source of interstitial number conc field
  !    character(len= 32) :: camname_mass_a ! name registered in constituents for number mixing ratio of interstitial species
  !    character(len=  1) :: source_mass_c  ! source of cloud borne number conc field
  !    character(len= 32) :: camname_mass_c ! name registered in constituents for number mixing ratio of cloud borne species

  !    character(len=  1), pointer :: source_mmr_a(:)  ! source of interstitial mmr field
  !    character(len= 32), pointer :: camname_mmr_a(:) ! name registered in constituents for mmr species
  !    character(len=  1), pointer :: source_mmr_c(:)  ! source of cloud borne specie mmr fields
  !    character(len= 32), pointer :: camname_mmr_c(:) ! name registered in constituents for mmr of cloud borne components
  !    character(len= 32), pointer :: type(:)          ! species type
  !    character(len= 32), pointer :: morph(:)         ! species morphology
  !    character(len=cs1), pointer :: props(:)         ! file containing species properties

  !    integer          :: idx_num_a    ! index in constituents for number mixing ratio of interstitial species
  !    integer          :: idx_num_c    ! index in constituents (non-adv) for number mixing ratio of cloud-borne species
  !    integer          :: idx_mass_a   ! index in constituents for mass mixing ratio of interstitial species
  !    integer          :: idx_mass_c   ! index in constituents (non-adv) for mass mixing ratio of cloud-borne species

  !    integer, pointer :: idx_mmr_a(:) ! index in constituents for mmr of interstitial species
  !    integer, pointer :: idx_mmr_c(:) ! index in constituents for mmr of cloud-borne species
  !    integer, pointer :: idx_props(:) ! ID used to access physical properties of mode species from phys_prop module
  ! end type bin_component_t

  ! ! type to provide access to all bins
  ! type :: bins_t
  !    integer :: nbins
  !    character(len= 32),    pointer :: names(:) ! names used to identify a mode in the climate/diag lists
  !    type(bin_component_t), pointer :: comps(:) ! components which define the mode
  ! end type bins_t

  ! type(bins_t), target :: bins  ! mode definitions

contains


end module radiative_aerosols

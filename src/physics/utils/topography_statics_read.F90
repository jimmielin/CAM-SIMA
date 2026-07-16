! Read the static subgrid topography fields consumed by physics (SGH, SGH30,
! LANDM_COSLAT) from the topography dataset (namelist bnd_topo) into their
! CAM-SIMA registry variables (sgh, sgh30, landm).
!
! In CAM these fields are read by phys_inidat (physpkg.F90) from the topo
! file into pbuf; PHIS itself is handled by the dycore (see SE set_phis) and
! the ridge fields by gravity_wave_drag_ridge_read. This module fills the
! physics-side gap for full-dycore CAM-SIMA runs; snapshot-driven (FPHYStest)
! runs leave bnd_topo unset and keep reading these fields from the snapshot
! via their ic_file_input_names.
!
! Mirrors CAM's semantics: without a topo file all fields keep their
! registry initial value of zero (the aquaplanet configuration); with a topo
! file SGH and LANDM_COSLAT are required, and a missing SGH30 falls back to
! SGH values with a warning.
!
! The fields are marked initialized so the first-timestep initial-condition
! read does not overwrite them or warn about their absence from ncdata.
!
! Not CCPP-ized: written for grid decomposition-aware I/O in CAM-SIMA,
! following the gravity_wave_drag_ridge_read / fraction_landuse_read
! pattern, but writing directly into the registry-generated physics_types
! variables. Must be called AFTER phys_init (which allocates them).
module topography_statics_read

  implicit none
  private

  public :: topography_statics_read_file

contains

  subroutine topography_statics_read_file()
    use spmd_utils,           only: masterproc
    use cam_logfile,          only: iulog
    use cam_abortutils,       only: endrun
    use pio,                  only: file_desc_t
    use cam_initfiles,        only: topo_file_get_id, bnd_topo, unset_path_str
    use cam_field_read,       only: cam_read_field
    use phys_vars_init_check, only: mark_as_initialized
    use physics_types,        only: sgh, sgh30, landm

    ! Local variables
    type(file_desc_t), pointer  :: fh_topo
    logical                     :: found
    character(len=*), parameter :: subname = 'topography_statics_read_file'

    if (bnd_topo == unset_path_str) then
      if (masterproc) then
        write(iulog,*) trim(subname)//': no topo file (bnd_topo unset); '// &
             'SGH, SGH30 and LANDM_COSLAT keep their initial values'
      end if
      return
    end if

    fh_topo => topo_file_get_id()
    if (.not. associated(fh_topo)) then
      call endrun(trim(subname)//': bnd_topo is set but the topo file is not open')
    end if

    if (masterproc) then
      write(iulog,*) trim(subname)//': reading SGH, SGH30, LANDM_COSLAT from topo file'
    end if

    call cam_read_field('SGH', fh_topo, sgh, found)
    if (.not. found) then
      call endrun(trim(subname)//': SGH not found on topo file')
    end if

    call cam_read_field('SGH30', fh_topo, sgh30, found)
    if (.not. found) then
      if (masterproc) then
        write(iulog,*) 'Warning: Error reading SGH30 from topo file.'
        write(iulog,*) 'The field SGH30 will be filled using data from SGH.'
      end if
      sgh30 = sgh
    end if

    call cam_read_field('LANDM_COSLAT', fh_topo, landm, found)
    if (.not. found) then
      call endrun(trim(subname)//': LANDM_COSLAT not found on topo dataset.')
    end if

    call mark_as_initialized('standard_deviation_of_subgrid_orography_for_orographic_gravity_wave_drag')
    call mark_as_initialized('standard_deviation_of_subgrid_orography_for_turbulent_orographic_form_drag')
    call mark_as_initialized('smoothed_land_area_fraction')

  end subroutine topography_statics_read_file

end module topography_statics_read

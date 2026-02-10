! CAM-SIMA version of aerosol_optics_cam.
! This is a minimal re-implementation of aerosol optics code providing aerosol optical properties
! for use by CCPP physics schemes.
!
! This module is in the host model level for now for development, but the goal
! is to have it as a CCPP scheme to provide run phases that output the SW/LW
! optical properties for use by the radiation.
! In CAM, aerosol_optics_cam_sw/lw are called and the intent(out) arguments are
! provided to the radiation. We do not want this at the host model level.

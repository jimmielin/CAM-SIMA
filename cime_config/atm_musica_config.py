"""
The URLs and tags provided in this script are read by buildlib to build
and install the MUSICA library, as well as to download the MUSICA configuration.
"""

MUSICA_CCPP_SCHEME_NAME = "musica_ccpp"
MUSICA_CONFIG_DIR_NAME = "musica_configurations"
MUSICA_REPO_URL = "https://github.com/NCAR/musica.git"
MUSICA_TAG = "25fff7ae42d146bf3f83ad5ac18b3caac8701ddd"
CHEMISTRY_DATA_REPO_URL = "https://github.com/NCAR/cam-sima-chemistry-data.git"
CHEMISTRY_DATA_TAG = "1ea9d1b8b04980738894d30a864f9a000daf2e5c"


def link_musica_configuration(caseroot, rundir):
    """
    Symlink every file under <caseroot>/musica_configurations into
    <rundir>/musica_configurations, the location the musica_ccpp namelist
    defaults point to. Does nothing if the caseroot directory does not exist.

    Called from buildnml, and from buildlib right after the configuration is
    downloaded: under create_test the namelist phase runs before the model
    build and the run phase skips buildnml, so buildnml alone never sees the
    downloaded directory and the run fails with "MUSICA Parsing: File not found".
    """
    import os
    from CIME.utils import symlink_force

    musica_config_src_dir = os.path.join(caseroot, MUSICA_CONFIG_DIR_NAME)
    musica_config_dest_dir = os.path.join(rundir, MUSICA_CONFIG_DIR_NAME)

    if not os.path.exists(musica_config_src_dir):
        return

    os.makedirs(musica_config_dest_dir, exist_ok=True)
    for root, _, files in os.walk(musica_config_src_dir):
        rel_path = os.path.relpath(root, musica_config_src_dir)
        dest_dir = os.path.join(musica_config_dest_dir, rel_path)

        os.makedirs(dest_dir, exist_ok=True)
        for file in files:
            symlink_force(os.path.join(root, file), os.path.join(dest_dir, file))

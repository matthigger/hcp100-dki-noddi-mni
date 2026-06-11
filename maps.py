"""Naming contract for QSIRecon's final MNI scalar maps.

A finished HCP subject is defined by exactly six scalar maps in
MNI152NLin2009cAsym space, written by two QSIRecon reconstruction passes:

    DKI  (Dipy; Jensen & Helpern 2010) on a b<=2000 DWI -> FA / MD / MK
    NODDI (AMICO; Zhang 2012; Daducci 2015) on the full DWI -> ICVF / ISOVF / OD

The wrapper entrypoint (run_hcp.py) and the verification step both import this
module so "which files constitute a done subject" lives in exactly one place.
"""

from pathlib import Path

# The standard space the recon specs target (QSIPrep/QSIRecon's default).
MNI = "space-MNI152NLin2009cAsym"

# Isotropic voxel size (mm) of the final MNI maps, passed as QSIRecon's
# --output-resolution. HCP is recon-only, so without this flag the output grid
# would inherit HCP's 1.25mm native DWI resolution; pin it to 2mm.
OUTPUT_RESOLUTION = 2

# The six scalar maps that define a finished subject.
DKI_PARAMS = ("fa", "md", "mk")
NODDI_PARAMS = ("icvf", "isovf", "od")


def mni_map_relpaths(sbj: str) -> list:
    """Build the six final-map paths relative to a QSIRecon output root.

    Paths are POSIX-style and relative to the directory that contains
    derivatives/qsirecon-*/, so the same list drives existence checks and
    output verification.

    Args:
        sbj (str): bare subject id, no "sub-" prefix (e.g. "100307").

    Returns:
        rels (list[str]): six
            derivatives/qsirecon-<suffix>/sub-<id>/dwi/<id>_<space>_model-<m>_param-<p>_dwimap.nii.gz
            relpaths (DKI first, then NODDI).
    """
    s = f"sub-{sbj}"
    rels = []
    for p in DKI_PARAMS:
        rels.append(f"derivatives/qsirecon-DIPYDKI/{s}/dwi/"
                    f"{s}_{MNI}_model-dki_param-{p}_dwimap.nii.gz")
    for p in NODDI_PARAMS:
        rels.append(f"derivatives/qsirecon-NODDI/{s}/dwi/"
                    f"{s}_{MNI}_model-noddi_param-{p}_dwimap.nii.gz")
    return rels


def mni_maps(qsirecon_dir, sbj: str) -> list:
    """Build the six absolute final-map Paths under a QSIRecon output root.

    Args:
        qsirecon_dir (str | Path): a QSIRecon output root.
        sbj (str): bare subject id, no "sub-" prefix.

    Returns:
        paths (list[Path]): the six map paths under qsirecon_dir.
    """
    return [Path(qsirecon_dir) / rel for rel in mni_map_relpaths(sbj)]


def done(qsirecon_dir, sbj: str) -> bool:
    """Return True when all six final MNI maps exist under qsirecon_dir."""
    return all(p.exists() for p in mni_maps(qsirecon_dir, sbj))

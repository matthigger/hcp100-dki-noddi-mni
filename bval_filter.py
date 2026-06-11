"""Restrict a DWI to its low-b shells for the DKI reconstruction pass.

QSIRecon's dipy_dki node fits the diffusion-kurtosis cumulant expansion
(Jensen & Helpern 2010) on whatever shells the input DWI carries, and exposes
no shell-selection parameter. The cumulant expansion is a Taylor series of
ln S in powers of b truncated at the kurtosis term, valid only to
b ~ 2000-2500 s/mm^2; fitting it to higher b underestimates the kurtosis and,
because D and K are estimated jointly, biases the embedded tensor and therefore
FA/MD too.

So before the DKI pass we hand QSIRecon a copy of the DWI with the high-b
volumes dropped. HCP-YA carries a b3000 shell, which is removed here; the NODDI
pass (Zhang 2012; AMICO, Daducci 2015) runs on the full, unfiltered DWI — it is
a high-b model and uses every shell.
"""

from pathlib import Path

import nibabel as nib
import numpy as np


def filter_dwi_bmax(dwi_path, bval_path, bvec_path, out_dir, b_max=2000,
                    margin=150):
    """Write a copy of a DWI keeping only its b <= b_max volumes.

    Reads a 4D DWI plus its FSL-style bval/bvec sidecars, keeps every volume
    whose b-value is <= b_max + margin (so the b0 volumes and every retained
    shell survive), and writes the filtered DWI + bval + bvec into out_dir under
    the input filenames.

    Args:
        dwi_path (Path): 4D DWI NIfTI, data shape (i, j, k, n_vol).
        bval_path (Path): FSL bval sidecar — one whitespace-separated row of
            n_vol b-values.
        bvec_path (Path): FSL bvec sidecar — 3 rows x n_vol gradient directions.
        out_dir (Path): writable directory for the filtered copy.
        b_max (int): shell ceiling in s/mm^2. 2000 keeps the DKI cumulant
            expansion valid (Jensen & Helpern 2010).
        margin (int): tolerance above b_max for scanner roundoff on the nominal
            shell value (a nominal 2000 shell can record 2005).

    Returns:
        out (dict): maps 'dwi'/'bval'/'bvec' to the written Path.

    Raises:
        ValueError: if fewer than three distinct shells (incl. b0) survive; the
            DKI fit needs a b0 plus at least two non-zero shells.
    """
    dwi_path, bval_path, bvec_path = map(Path, (dwi_path, bval_path, bvec_path))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bvals = np.loadtxt(bval_path)
    bvecs = np.loadtxt(bvec_path)
    keep = bvals <= b_max + margin

    n_shell = np.unique(np.round(bvals[keep] / 100.0) * 100).size
    if n_shell < 3:
        raise ValueError(
            f"only {n_shell} distinct shell(s) (incl. b0) survive b<={b_max} "
            f"for {dwi_path.name}; DKI needs a b0 plus >=2 non-zero shells"
        )

    img = nib.load(str(dwi_path))
    data = np.asanyarray(img.dataobj)[..., keep]

    out = {
        "dwi": out_dir / dwi_path.name,
        "bval": out_dir / bval_path.name,
        "bvec": out_dir / bvec_path.name,
    }
    nib.save(nib.Nifti1Image(data, img.affine, img.header), str(out["dwi"]))
    np.savetxt(out["bval"], bvals[keep][np.newaxis, :], fmt="%g")
    np.savetxt(out["bvec"], bvecs[:, keep], fmt="%.6f")
    return out

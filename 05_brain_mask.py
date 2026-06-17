#!/usr/bin/env python3
"""Build the cohort brain mask: voxels with nonzero FA in every subject.

The dataset's six scalar maps (maps.py) all live on the same MNI152NLin2009cAsym
2mm grid, but each carries a slightly different support -- DKI FA is exactly zero
outside the brain and in voxels the cumulant fit could not resolve. A single
shared mask is convenient for any downstream analysis that needs one common voxel
set across all subjects (e.g. GLOW's Ward region tree).

This step takes the intersection: a voxel is in the mask iff its DKI FA map is
finite and nonzero for *every* contributing subject. That is deliberately
conservative -- a voxel zero (or non-finite) in even one subject is dropped -- so
the mask is the largest voxel set on which all subjects carry a real FA value.
Because it is an all-subject intersection, it cannot be reproduced from a partial
download; it is a property of the whole cohort.

It reads the same sources verify.py accepts (BABS result zips, a dir/glob of
them, or an unzipped QSIRecon output root) and writes one uint8 NIfTI on the FA
grid. Run with the babs env (nibabel + numpy):

    micromamba run -n babs python 05_brain_mask.py ~/babs_hcp/outputs/sub-*.zip \
        --out brain_mask_space-MNI152NLin2009cAsym.nii.gz
"""

import argparse
import sys
from pathlib import Path

import nibabel as nib
import numpy as np

import maps
import verify

# Default output name, mirroring the maps' BIDS-style space tag (maps.MNI).
DEFAULT_OUT = f"brain_mask_{maps.MNI}.nii.gz"


def fa_relpath(sbj: str) -> str:
    """Return the DKI FA map relpath for a subject (the mask's reference grid).

    Args:
        sbj (str): bare subject id, no "sub-" prefix.

    Returns:
        rel (str): the single param-fa relpath from maps.mni_map_relpaths.
    """
    rels = [r for r in maps.mni_map_relpaths(sbj) if "_param-fa_" in r]
    if not rels:
        raise ValueError(f"no FA map relpath for sub-{sbj}")
    return rels[0]


def build_mask(sources: dict, foldername: str):
    """Intersect nonzero-FA support over every subject's DKI FA map.

    Args:
        sources (dict[str, Path]): subject id -> result zip or unzipped root
            (as returned by verify.collect_sources).
        foldername (str): inner wrapper folder inside a result zip.

    Returns:
        mask (np.array): (i, j, k) bool, True where FA is finite and nonzero in
            all contributing subjects; None if no FA map could be loaded.
        ref_img: the first loaded FA nibabel image, providing the output grid
            (affine + header); None alongside a None mask.
        n_used (int): number of subjects whose FA map contributed to the mask.
    """
    mask = None
    ref_img = None
    n_used = 0
    for sbj in sorted(sources):
        img = verify.load_map(sources[sbj], fa_relpath(sbj), foldername)
        if img is None:
            sys.stderr.write(f"skipping sub-{sbj}: FA map missing/unreadable\n")
            continue
        data = np.squeeze(np.asanyarray(img.dataobj))
        good = np.isfinite(data) & (data != 0)
        if mask is None:
            mask, ref_img = good, img
        elif good.shape != mask.shape:
            sys.stderr.write(
                f"skipping sub-{sbj}: FA grid {good.shape} != {mask.shape}\n")
            continue
        else:
            mask &= good
        n_used += 1
    return mask, ref_img, n_used


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the cohort brain mask (intersection of nonzero FA).")
    ap.add_argument("paths", nargs="+",
                    help="result .zip(s), a dir/glob of sub-*_*.zip, or an "
                         "unzipped QSIRecon output root")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"output mask path (default: {DEFAULT_OUT})")
    ap.add_argument("--participant-label", "--participant_label", default=None,
                    help="bare subject id; required for an unzipped root, "
                         "overrides the parsed id for a single zip")
    ap.add_argument("--zip-foldername", default="qsirecon",
                    help="inner wrapper folder inside a result zip "
                         "(default: qsirecon)")
    args = ap.parse_args(argv)

    sources = verify.collect_sources(args.paths, args.participant_label)
    if not sources:
        sys.stderr.write("no subjects to build a mask from\n")
        return 1

    mask, ref_img, n_used = build_mask(sources, args.zip_foldername)
    if mask is None:
        sys.stderr.write("no FA maps could be loaded\n")
        return 1

    out_img = nib.Nifti1Image(mask.astype(np.uint8), ref_img.affine,
                              ref_img.header)
    out_img.header.set_data_dtype(np.uint8)
    nib.save(out_img, args.out)

    print(f"wrote {args.out}: {int(mask.sum())} voxels "
          f"from {n_used}/{len(sources)} subjects")
    return 0


if __name__ == "__main__":
    sys.exit(main())

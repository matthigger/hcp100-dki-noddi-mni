#!/usr/bin/env python3
"""QC gate: check that BABS result outputs are real, valid scalar maps.

A finished subject is defined by the six MNI maps in maps.py. A green BABS job
means the wrapper found those six files, but it does not prove the images are
sane (right space, right grid, a non-empty brain, plausible parameter ranges).
This script promotes the ad-hoc manual look into a repeatable check.

For each subject it loads every expected map (maps.mni_map_relpaths) and asserts:
  * the file exists and opens with nibabel;
  * it is 3D with an isotropic voxel size matching maps.OUTPUT_RESOLUTION;
  * its name carries the expected space tag (maps.MNI);
  * a non-trivial fraction of voxels are finite and nonzero (non-empty brain);
  * its values stay in range for that parameter -- the bounded fractions
    fa/icvf/isovf/od in [0, ~1], md (a diffusivity) non-negative, and mk
    (mean kurtosis, which is signed) within a generous sanity band; all finite.

Inputs may be BABS result zips (named sub-<id>_<foldername>-<version>.zip, the
map at <foldername>/<maps relpath> inside), a dir/glob of such zips, or an
unzipped QSIRecon output root (post-`babs merge`). It prints a PASS/FAIL line
per subject and an "N/M subjects passed" summary, exiting nonzero on any failure.

Reproducibility check (--compare-to): the pipeline is reproducible within
tolerance, not bit-for-bit (multithreaded ANTs registration). To detect drift
(e.g. a changed TemplateFlow target or container), re-run a subject and pass the
canonical/published outputs as --compare-to: each map's per-voxel spatial Pearson
correlation against the reference must be >= --corr-threshold (default 0.999).
Nothing is committed as a reference -- you compare against your published deposit.

Run with the babs env (has nibabel + numpy), e.g.:

    micromamba run -n babs python verify.py ~/babs_hcp/outputs/sub-*.zip
    micromamba run -n babs python verify.py fresh/ --compare-to published/
"""

import argparse
import glob
import gzip
import io
import re
import sys
import zipfile
from pathlib import Path

import nibabel as nib
import numpy as np

import maps

# Parameters whose physical range is the unit interval (a small slack absorbs
# QSIRecon's interpolation/dtype overshoot at the brain edge).
BOUNDED_PARAMS = ("fa", "icvf", "isovf", "od")
UPPER_BOUND = 1.05

# Diffusivity-like params must be non-negative.
NONNEG_PARAMS = ("md",)

# Mean kurtosis is signed: noise and fit instability drive it slightly negative
# in CSF and edge voxels, so we only sanity-bound it rather than require >= 0
# (the DKI cumulant fit, Jensen & Helpern 2010).
SIGNED_PARAMS = ("mk",)
MK_RANGE = (-2.0, 10.0)

# Voxel-size match tolerance (mm) and the minimum fraction of finite-nonzero
# voxels we accept as a non-empty brain (a 2mm MNI brain fills well over this).
RES_TOL = 0.05
MIN_NONZERO_FRAC = 0.01

# Pull the param token out of a map filename, e.g. ..._param-fa_dwimap.nii.gz.
_PARAM_RE = re.compile(r"_param-([a-z0-9]+)_")
# Recover the bare subject id from a BABS result zip name, e.g.
# sub-100307_qsirecon-26-0-0.zip -> 100307.
_ZIP_SBJ_RE = re.compile(r"sub-([A-Za-z0-9]+)_")


def param_of(relpath: str) -> str:
    """Return the param token (fa, md, ..., od) parsed from a map filename."""
    m = _PARAM_RE.search(Path(relpath).name)
    if not m:
        raise ValueError(f"no _param-<p>_ token in {relpath}")
    return m.group(1)


def spatial_corr(a, b):
    """Compare two maps over brain voxels.

    Brain voxels are those finite in both maps and nonzero in either, so the
    zero background does not inflate the correlation.

    Args:
        a (np.array): first map's voxel data, any shape.
        b (np.array): second map's voxel data, same shape as a.

    Returns:
        r (float): Pearson correlation over brain voxels (1.0 if both are
            constant-and-equal there; nan if the maps do not overlap).
        maxdiff (float): max absolute voxel difference over brain voxels.
        nrmse (float): RMS difference normalized by the RMS of b (the reference).
    """
    a = np.asanyarray(a, dtype=np.float64).ravel()
    b = np.asanyarray(b, dtype=np.float64).ravel()
    if a.shape != b.shape:
        return float("nan"), float("nan"), float("nan")
    mask = np.isfinite(a) & np.isfinite(b) & ((a != 0) | (b != 0))
    if mask.sum() < 2:
        return float("nan"), float("nan"), float("nan")
    av, bv = a[mask], b[mask]
    if av.std() == 0 or bv.std() == 0:
        r = 1.0 if np.allclose(av, bv) else 0.0
    else:
        r = float(np.corrcoef(av, bv)[0, 1])
    maxdiff = float(np.max(np.abs(av - bv)))
    denom = float(np.sqrt(np.mean(bv ** 2))) or 1.0
    nrmse = float(np.sqrt(np.mean((av - bv) ** 2)) / denom)
    return r, maxdiff, nrmse


def check_image(img, relpath: str, resolution: float) -> list:
    """Validate one loaded map against the contract; return failure reasons.

    Args:
        img: a loaded nibabel image (e.g. Nifti1Image).
        relpath (str): the map's path, used for the space tag and param token.
        resolution (float): expected isotropic voxel size in mm.

    Returns:
        fails (list[str]): one short reason per failed check; empty means PASS.
    """
    fails = []
    name = Path(relpath).name

    if maps.MNI not in name:
        fails.append(f"space tag {maps.MNI} not in name")

    # Drop trailing singleton axes (a 3D map is sometimes stored (i, j, k, 1)).
    data = np.asanyarray(img.dataobj)
    data = np.squeeze(data)
    if data.ndim != 3:
        fails.append(f"not 3D (shape {data.shape})")

    # zooms are per-axis voxel sizes in mm; the spatial three must be isotropic
    # and equal to the pinned --output-resolution.
    zooms = np.asarray(img.header.get_zooms()[:3], dtype=float)
    if zooms.size < 3:
        fails.append(f"missing voxel sizes (zooms {tuple(zooms)})")
    else:
        if float(zooms.max() - zooms.min()) > RES_TOL:
            fails.append(f"anisotropic voxels {tuple(np.round(zooms, 3))}")
        if abs(float(zooms.mean()) - resolution) > RES_TOL:
            fails.append(
                f"voxel size {zooms.mean():.3f}mm != {resolution}mm")

    finite = np.isfinite(data)
    if not finite.all():
        fails.append(f"{int((~finite).sum())} non-finite voxels")

    nonzero_frac = float((finite & (data != 0)).sum()) / max(data.size, 1)
    if nonzero_frac < MIN_NONZERO_FRAC:
        fails.append(f"empty brain (nonzero frac {nonzero_frac:.4f})")

    # Range check only over finite voxels so a NaN does not mask a bound miss.
    vals = data[finite]
    if vals.size:
        param = param_of(relpath)
        lo, hi = float(vals.min()), float(vals.max())
        if param in BOUNDED_PARAMS:
            if lo < 0 or hi > UPPER_BOUND:
                fails.append(
                    f"{param} out of [0,{UPPER_BOUND}] (min {lo:.3g}, "
                    f"max {hi:.3g})")
        elif param in NONNEG_PARAMS:
            if lo < 0:
                fails.append(f"{param} has negative values (min {lo:.3g})")
        elif param in SIGNED_PARAMS:
            if lo < MK_RANGE[0] or hi > MK_RANGE[1]:
                fails.append(
                    f"{param} out of [{MK_RANGE[0]},{MK_RANGE[1]}] "
                    f"(min {lo:.3g}, max {hi:.3g})")
    return fails


def load_from_zip(zip_path: Path, relpath: str):
    """Load a map stored inside a BABS result zip, or None if absent.

    Args:
        zip_path (Path): the .zip result archive.
        relpath (str): the path of the map inside the zip (foldername already
            prepended).

    Returns:
        img: the loaded nibabel image, or None when the entry is missing.
    """
    with zipfile.ZipFile(zip_path) as zf:
        try:
            raw = zf.read(relpath)
        except KeyError:
            return None
    # The stored entry is the on-disk .nii.gz (gzip-compressed); decompress to
    # the bare NIfTI stream and hand nibabel a BytesIO file-map, so the image
    # never touches disk.
    nii = gzip.decompress(raw) if relpath.endswith(".gz") else raw
    fh = nib.FileHolder(fileobj=io.BytesIO(nii))
    return nib.Nifti1Image.from_file_map({"header": fh, "image": fh})


def load_map(source: Path, rel: str, foldername: str):
    """Load one map for a subject from a result zip or an unzipped root.

    Args:
        source (Path): a result .zip, or a directory holding derivatives/.
        rel (str): the map relpath from maps.mni_map_relpaths.
        foldername (str): the inner wrapper folder inside a result zip.

    Returns:
        img: the loaded nibabel image, or None if absent / unreadable.
    """
    if source.is_file() and source.suffix == ".zip":
        try:
            return load_from_zip(source, f"{foldername}/{rel}")
        except Exception:
            return None
    p = source / rel
    if not p.exists():
        return None
    try:
        return nib.load(str(p))
    except Exception:
        return None


def verify_subject(source: Path, sbj: str, foldername: str, resolution: float,
                   ref_source: Path = None, corr_threshold: float = 0.999):
    """Check one subject's six maps; optionally correlate against a reference.

    Args:
        source (Path): the subject's result zip or unzipped output root.
        sbj (str): bare subject id (no "sub-" prefix).
        foldername (str): inner wrapper folder inside a result zip.
        resolution (float): expected isotropic voxel size in mm.
        ref_source (Path | None): a reference copy of this subject's outputs
            (zip or root) for the per-voxel reproducibility check, or None.
        corr_threshold (float): minimum per-map spatial correlation to pass.

    Returns:
        fails (dict[str, list[str]]): map relpath -> failure reasons (empty
            list = passed).
        min_r (float | None): min spatial correlation across the six maps when
            ref_source is given, else None.
    """
    fails, min_r = {}, None
    for rel in maps.mni_map_relpaths(sbj):
        img = load_map(source, rel, foldername)
        if img is None:
            fails[rel] = ["missing"]
            continue
        fails[rel] = check_image(img, rel, resolution)
        if ref_source is not None:
            ref_img = load_map(ref_source, rel, foldername)
            if ref_img is None:
                fails[rel].append("missing in reference")
                continue
            r, maxdiff, nrmse = spatial_corr(
                np.asanyarray(img.dataobj), np.asanyarray(ref_img.dataobj))
            min_r = r if min_r is None else min(min_r, r)
            if not (r >= corr_threshold):
                fails[rel].append(
                    f"r={r:.5f} < {corr_threshold} vs reference "
                    f"(maxdiff {maxdiff:.3g}, nrmse {nrmse:.3g})")
    return fails, min_r


def report(sbj: str, fails: dict, min_r: float = None) -> bool:
    """Print one PASS/FAIL line for a subject; return True when it passed.

    Args:
        sbj (str): bare subject id.
        fails (dict[str, list[str]]): map relpath -> failure reasons.
        min_r (float | None): min spatial correlation vs reference, if compared.

    Returns:
        ok (bool): True when every map passed.
    """
    bad = {rel: rs for rel, rs in fails.items() if rs}
    tag = f" (min r={min_r:.5f})" if min_r is not None else ""
    if not bad:
        print(f"PASS sub-{sbj}: {len(fails)} maps OK{tag}")
        return True
    print(f"FAIL sub-{sbj}: {len(bad)}/{len(fails)} maps failed{tag}")
    for rel, reasons in bad.items():
        print(f"  {Path(rel).name}: {'; '.join(reasons)}")
    return False


def find_zips(path: Path) -> list:
    """Expand a path into BABS result zips (a file, a dir, or a glob).

    Args:
        path (Path): a .zip file, a directory holding sub-*_*.zip, or a glob.

    Returns:
        zips (list[Path]): matching zip paths, sorted; empty if none match.
    """
    if path.is_file() and path.suffix == ".zip":
        return [path]
    if path.is_dir():
        return sorted(path.glob("sub-*_*.zip"))
    return sorted(Path(p) for p in glob.glob(str(path)) if p.endswith(".zip"))


def subject_of_zip(zip_path: Path, override: str = None) -> str:
    """Return the bare subject id for a result zip (name parse, or override)."""
    if override:
        return override[4:] if override.startswith("sub-") else override
    m = _ZIP_SBJ_RE.search(zip_path.name)
    if not m:
        raise ValueError(f"cannot parse subject id from {zip_path.name}")
    return m.group(1)


def collect_sources(paths, participant_label: str = None) -> dict:
    """Map each subject id to its output source (a result zip or a root).

    Args:
        paths (list[str]): result .zip(s), a dir/glob of sub-*_*.zip, or an
            unzipped QSIRecon output root.
        participant_label (str | None): bare/sub- id; required to name an
            unzipped root, and overrides the parsed id for a single zip.

    Returns:
        sources (dict[str, Path]): subject id -> zip Path or root Path.
    """
    out = {}
    for raw in paths:
        p = Path(raw)
        zips = find_zips(p)
        if zips:
            single = len(zips) == 1
            for zp in zips:
                try:
                    out[subject_of_zip(zp, participant_label if single else None)] = zp
                except ValueError as e:
                    sys.stderr.write(f"skipping {zp}: {e}\n")
        elif p.is_dir():
            if not participant_label:
                sys.stderr.write(
                    f"skipping {p}: --participant-label required for an "
                    f"unzipped root\n")
                continue
            sbj = participant_label[4:] if participant_label.startswith("sub-") \
                else participant_label
            out[sbj] = p
        else:
            sys.stderr.write(f"skipping {raw}: no zips and not a directory\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify BABS QSIRecon result maps are valid.")
    ap.add_argument("paths", nargs="+",
                    help="result .zip(s), a dir/glob of sub-*_*.zip, or an "
                         "unzipped QSIRecon output root")
    ap.add_argument("--participant-label", "--participant_label", default=None,
                    help="bare subject id; required for an unzipped root, "
                         "overrides the parsed id for a single zip")
    ap.add_argument("--zip-foldername", default="qsirecon",
                    help="inner wrapper folder inside a result zip "
                         "(default: qsirecon)")
    ap.add_argument("--resolution", type=float,
                    default=float(maps.OUTPUT_RESOLUTION),
                    help="expected isotropic voxel size in mm "
                         f"(default: {float(maps.OUTPUT_RESOLUTION)})")
    ap.add_argument("--compare-to", "--compare_to", default=None,
                    help="reference outputs (zip/dir/glob/root) to spatially "
                         "correlate matching subjects against (drift check)")
    ap.add_argument("--corr-threshold", "--corr_threshold", type=float,
                    default=0.999,
                    help="min per-map spatial correlation vs --compare-to "
                         "(default: 0.999)")
    args = ap.parse_args(argv)

    fresh = collect_sources(args.paths, args.participant_label)
    ref = (collect_sources([args.compare_to], args.participant_label)
           if args.compare_to else {})

    results = []
    for sbj in sorted(fresh):
        ref_source = ref.get(sbj) if ref else None
        if args.compare_to and ref_source is None:
            sys.stderr.write(
                f"note: sub-{sbj} not in --compare-to; plausibility only\n")
        fails, min_r = verify_subject(
            fresh[sbj], sbj, args.zip_foldername, args.resolution,
            ref_source, args.corr_threshold)
        results.append(report(sbj, fails, min_r))

    if not results:
        sys.stderr.write("no subjects to verify\n")
        return 1

    n_pass = sum(results)
    print(f"{n_pass}/{len(results)} subjects passed")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

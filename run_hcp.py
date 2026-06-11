#!/usr/bin/env python3
"""BIDS-App-shaped wrapper that runs the two HCP QSIRecon passes in-container.

BABS drives one container call per subject and treats a non-zero exit as a
failed job. The HCP recipe needs two QSIRecon calls plus a data-prep step
between them and deliberately tolerates a cosmetic non-zero exit, so we hide all
of that behind this wrapper and present BABS an ordinary BIDS App:

    run_hcp.py <in_dir> <out_dir> participant --participant-label <label> [flags]

For each subject it:
  1. resolves the bare HCP id from the BIDS label (drops any "sub-" prefix);
  2. stages an hcpya-layout tree <id>/T1w/... that QSIRecon's hcpya ingest wants
     (the input dataset stores it as sub-<id>/T1w/...);
  3. runs QSIRecon with noddi_mni.yaml on the FULL DWI (NODDI; Zhang 2012,
     Daducci 2015);
  4. runs QSIRecon with dki_mni.yaml on a b<=2000-filtered copy (DKI; Jensen &
     Helpern 2010 — see bval_filter.py for why the b3000 shell is dropped);
  5. exits 0 iff all six final MNI maps exist (maps.done), else 1.

Both passes use --input-type hcpya, --use-plugin Linear (linear_plugin.yml), and
--output-resolution 2, and write into <out_dir>/qsirecon (so BABS zips the
folder literally named "qsirecon"). The hcpya path produces no dseg, so
QSIRecon's report node crashes and the process exits non-zero even on success;
we therefore judge success by the maps, not the exit code.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from bval_filter import filter_dwi_bmax
from maps import OUTPUT_RESOLUTION, done, mni_maps

NODDI_SPEC = _HERE / "noddi_mni.yaml"
DKI_SPEC = _HERE / "dki_mni.yaml"
PLUGIN = _HERE / "linear_plugin.yml"

# Files QSIRecon's hcpya ingest reads, relative to a subject's T1w/ dir.
T1W_FILES = ("T1w_acpc_dc_restore_brain.nii.gz", "brainmask_fs.nii.gz",
             "T1w_acpc_dc_restore_1.25.nii.gz")
DIFFUSION_EXTRA = ("nodif_brain_mask.nii.gz",)

# Seed ANTs so the T1w->MNI registration is repeatable run-to-run. We deliberately
# do NOT pin ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1: that makes registration
# bit-for-bit reproducible but single-threaded, which is ~4x slower (~4 h/subject)
# and infeasible for the full cohort. With ITK multithreaded, outputs reproduce to
# within tolerance (correlation), which is what verify.py checks.
REPRO_ENV = {
    "ANTS_RANDOM_SEED": "1",
}


def qsirecon_exe():
    """Return the qsirecon executable path (PATH, then the conda fallback)."""
    exe = shutil.which("qsirecon")
    if exe:
        return exe
    fallback = "/opt/conda/bin/qsirecon"
    if Path(fallback).exists():
        return fallback
    raise FileNotFoundError("qsirecon not found on PATH or /opt/conda/bin")


def stage_full(src_t1w, dst_root, hcp_id):
    """Mirror a subject's full hcpya tree into dst_root/<hcp_id>/T1w.

    Symlinks the structural + Diffusion files so QSIRecon reads the full DWI
    unchanged without copying ~1 GB.

    Args:
        src_t1w (Path): the subject's source T1w/ directory.
        dst_root (Path): staging root; the subject dir is created beneath it.
        hcp_id (str): bare HCP id used as the staged subject directory name.

    Returns:
        dst_root (Path): the staging root to hand QSIRecon as its input.
    """
    t1w = dst_root / hcp_id / "T1w"
    (t1w / "Diffusion").mkdir(parents=True, exist_ok=True)
    for f in T1W_FILES:
        if (src_t1w / f).exists():
            os.symlink(src_t1w / f, t1w / f)
    src_diff = src_t1w / "Diffusion"
    for f in ("data.nii.gz", "bvals", "bvecs") + DIFFUSION_EXTRA:
        if (src_diff / f).exists():
            os.symlink(src_diff / f, t1w / "Diffusion" / f)
    return dst_root


def stage_dki(src_t1w, dst_root, hcp_id):
    """Build a b<=2000-filtered hcpya tree at dst_root/<hcp_id>/T1w.

    Copies the structural files and writes a bval-filtered Diffusion, so the DKI
    cumulant fit never sees the b3000 shell (Jensen & Helpern 2010).

    Args:
        src_t1w (Path): the subject's source T1w/ directory.
        dst_root (Path): staging root for the filtered tree.
        hcp_id (str): bare HCP id used as the staged subject directory name.

    Returns:
        dst_root (Path): the staging root to hand QSIRecon as its input.
    """
    t1w = dst_root / hcp_id / "T1w"
    (t1w / "Diffusion").mkdir(parents=True, exist_ok=True)
    for f in T1W_FILES:
        if (src_t1w / f).exists():
            shutil.copy(src_t1w / f, t1w / f)
    src_diff = src_t1w / "Diffusion"
    filter_dwi_bmax(src_diff / "data.nii.gz", src_diff / "bvals",
                    src_diff / "bvecs", t1w / "Diffusion", b_max=2000)
    for f in DIFFUSION_EXTRA:
        if (src_diff / f).exists():
            shutil.copy(src_diff / f, t1w / "Diffusion" / f)
    return dst_root


def run_qsirecon(in_root, out_dir, hcp_id, spec, work, fs_license, nprocs,
                 mem):
    """Run one QSIRecon hcpya pass; return its exit code.

    Args:
        in_root (Path): staging root containing <hcp_id>/T1w/...
        out_dir (Path): QSIRecon output root (derivatives/ are written beneath).
        hcp_id (str): bare HCP participant label.
        spec (Path): recon-spec YAML (noddi_mni.yaml or dki_mni.yaml).
        work (Path): per-pass nipype working directory.
        fs_license (str | None): FreeSurfer license path, forwarded if given.
        nprocs (int): --nprocs and --omp-nthreads value.
        mem (int): --mem value in MB.

    Returns:
        rc (int): the QSIRecon process exit code (1 is expected on hcpya; the
            caller judges success by the maps, not this code).
    """
    work.mkdir(parents=True, exist_ok=True)
    cmd = [qsirecon_exe(), str(in_root), str(out_dir), "participant",
           "--participant-label", hcp_id,
           "--recon-spec", str(spec),
           "--input-type", "hcpya",
           "--use-plugin", str(PLUGIN),
           "--output-resolution", str(OUTPUT_RESOLUTION),
           "--nprocs", str(nprocs), "--omp-nthreads", str(nprocs),
           "--mem", str(mem), "-w", str(work)]
    if fs_license:
        cmd += ["--fs-license-file", fs_license]
    print("RUN:", " ".join(cmd), flush=True)
    return subprocess.run(cmd, env={**os.environ, **REPRO_ENV}).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description="HCP two-pass QSIRecon wrapper")
    ap.add_argument("in_dir")
    ap.add_argument("out_dir")
    ap.add_argument("analysis_level", nargs="?", default="participant")
    ap.add_argument("--participant-label", "--participant_label", default=None)
    ap.add_argument("--fs-license-file", "--fs_license_file", default=None)
    ap.add_argument("--nprocs", "--n_cpus", type=int, default=8)
    ap.add_argument("--omp-nthreads", type=int, default=None)
    ap.add_argument("--mem", "--mem_mb", type=int, default=40000)
    ap.add_argument("--output-resolution", type=float, default=OUTPUT_RESOLUTION)
    # Tolerate (and ignore) any other flags BABS may inject.
    args, _ignored = ap.parse_known_args(argv)

    in_dir = Path(args.in_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    label = args.participant_label
    if not label:
        sys.exit("--participant-label is required")
    hcp_id = label[4:] if label.startswith("sub-") else label

    # Input dataset stores the subject as sub-<id>/T1w/...; fall back to a bare
    # <id>/T1w/... layout for robustness.
    for cand in (in_dir / f"sub-{hcp_id}" / "T1w", in_dir / hcp_id / "T1w"):
        if cand.exists():
            src_t1w = cand
            break
    else:
        sys.exit(f"no T1w tree for {hcp_id} under {in_dir}")

    # BABS hands us the output dir already nested as outputs/qsirecon (it zips
    # the "qsirecon" folder), so QSIRecon's derivatives go straight into out_dir.
    qsirecon_out = out_dir
    qsirecon_out.mkdir(parents=True, exist_ok=True)
    nprocs = args.nprocs
    fs = args.fs_license_file

    # Scratch lives one level up (outputs/), which BABS deletes and never zips,
    # so heavy nipype work dirs cannot leak into the result zip.
    scratch = Path(tempfile.mkdtemp(prefix="babs_hcp_", dir=out_dir.parent))
    try:
        noddi_in = stage_full(src_t1w, scratch / "noddi_in", hcp_id)
        rc_n = run_qsirecon(noddi_in, qsirecon_out, hcp_id, NODDI_SPEC,
                            scratch / "work_noddi", fs, nprocs, args.mem)

        dki_in = stage_dki(src_t1w, scratch / "dki_in", hcp_id)
        rc_d = run_qsirecon(dki_in, qsirecon_out, hcp_id, DKI_SPEC,
                            scratch / "work_dki", fs, nprocs, args.mem)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if done(qsirecon_out, hcp_id):
        print(f"OK: six maps present for sub-{hcp_id}", flush=True)
        return 0
    missing = [str(p) for p in mni_maps(qsirecon_out, hcp_id) if not p.exists()]
    print(f"INCOMPLETE (noddi rc={rc_n}, dki rc={rc_d}); missing:", flush=True)
    for m in missing:
        print("  ", m, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())

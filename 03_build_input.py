#!/usr/bin/env python3
"""Build the shareable HCP-YA input DataLad dataset for BABS.

Lays out each subject as sub-<id>/T1w/... (the files QSIRecon's hcpya ingest
reads) inside a DataLad dataset, so BABS can clone it and `datalad get` one
subject at a time per job. The dataset is the git-annex artifact shared with
collaborators (HCP-YA Open Access DUA applies).

Files are copied into the dataset and annexed (MD5E-checksummed) so the dataset
is self-contained, content-verifiable, and portable. The cohort is the committed
subjects.txt (override with --subjects).

Reads BABS_HCP_INPUT_SRC (the source HCP-YA tree) and BABS_HCP_RUNTIME from the
environment, both exported by config.sh. Run inside the babs env as:

    source ./config.sh && micromamba run -n babs python 03_build_input.py
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUNTIME = Path(os.environ.get("BABS_HCP_RUNTIME", Path.home() / "babs_hcp"))
SRC_ROOT = Path(os.environ.get("BABS_HCP_INPUT_SRC", ""))
DS = RUNTIME / "input_hcp"
SUBJECTS_FILE = Path(__file__).resolve().parent / "subjects.txt"

T1W_FILES = ("T1w_acpc_dc_restore_brain.nii.gz", "brainmask_fs.nii.gz",
             "T1w_acpc_dc_restore_1.25.nii.gz")
DIFFUSION_FILES = ("data.nii.gz", "bvals", "bvecs", "nodif_brain_mask.nii.gz")


def datalad(*args):
    subprocess.run(["datalad", *args], check=True)


def read_manifest():
    """Return the subject ids listed in subjects.txt (blanks/'#' ignored)."""
    ids = []
    for line in SUBJECTS_FILE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.append(line)
    return ids


def add_subject(sbj):
    """Copy one subject's hcpya files into DS/sub-<id>/T1w; skip if present.

    Args:
        sbj (str): bare HCP subject id (no sub- prefix).

    Returns:
        added (bool): True if newly copied, False if already present (idempotent).
    """
    src = SRC_ROOT / sbj / "T1w"
    dst = DS / f"sub-{sbj}" / "T1w"
    if (dst / "Diffusion" / "data.nii.gz").exists():
        return False
    (dst / "Diffusion").mkdir(parents=True, exist_ok=True)
    for f in T1W_FILES:
        if (src / f).exists():
            shutil.copy(src / f, dst / f)
    for f in DIFFUSION_FILES:
        if (src / "Diffusion" / f).exists():
            shutil.copy(src / "Diffusion" / f, dst / "Diffusion" / f)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", default="",
                    help="comma-separated subject ids (default: read subjects.txt)")
    args = ap.parse_args(argv)

    if not os.environ.get("BABS_HCP_INPUT_SRC"):
        sys.exit("BABS_HCP_INPUT_SRC is unset; set it in config.sh and run: "
                 "source ./config.sh && micromamba run -n babs python 03_build_input.py")
    if not SRC_ROOT.is_dir():
        sys.exit(f"BABS_HCP_INPUT_SRC does not exist: {SRC_ROOT}")

    subs = args.subjects.split(",") if args.subjects else read_manifest()
    if not subs:
        sys.exit(f"no subjects given (--subjects empty and {SUBJECTS_FILE} empty)")

    DS.mkdir(parents=True, exist_ok=True)
    if not (DS / ".datalad").exists():
        datalad("create", "-D", "HCP-YA Open Access inputs for QSIRecon", str(DS))

    # BABS globs inputs/data/*json into every job's `datalad run`, so the dataset
    # needs at least one top-level JSON (the hcpya tree has none of its own).
    desc = DS / "dataset_description.json"
    if not desc.exists():
        desc.write_text(json.dumps(
            {"Name": "HCP-YA Open Access (QSIRecon hcpya inputs)",
             "BIDSVersion": "1.8.0", "DatasetType": "raw"}, indent=2))

    added = [s for s in subs if add_subject(s)]
    print(f"copied {len(added)} new subject(s); {len(subs)} requested", flush=True)
    datalad("save", "-d", str(DS), "-m",
            f"add {len(added)} HCP-YA subject(s)" if added else "no-op")
    print("input dataset ready:", DS, flush=True)


if __name__ == "__main__":
    main()

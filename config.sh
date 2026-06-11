# Edit this file to point the project at a new dataset/machine — it is the only
# file you should need to change. Sourced by every numbered script (and exported
# so 03_build_input.py sees these as environment variables). The BABS container
# YAML is rendered from qsirecon_hcp.yaml.tmpl using these values, because BABS
# reads the YAML literally and does not expand env vars in its paths.

# Where the BABS runtime lives (DataLad datasets, RIA stores, .sif, scratch).
# Must be OUTSIDE any Dropbox/sync folder: git-annex object stores must not sync.
export BABS_HCP_RUNTIME="${BABS_HCP_RUNTIME:-$HOME/babs_hcp}"

# FreeSurfer license file (free, register at https://surfer.nmr.mgh.harvard.edu).
export FS_LICENSE="${FS_LICENSE:-$HOME/Dropbox/src_etc/freesurfer_license.txt}"

# Source HCP-YA tree that 03_build_input.py reads (one <id>/T1w/... dir per
# subject). No default: set this to your local HCP-YA download before building.
export BABS_HCP_INPUT_SRC="${BABS_HCP_INPUT_SRC:-/path/to/hcp_ya/raw_hcpya}"

# TemplateFlow is PINNED by baking the MNI152NLin2009cAsym templates into the
# .sif at build time (02_build_sif.sh) — runs are hermetic and version-stable,
# so we do NOT bind a host cache into jobs (04_run_babs.sh unsets TEMPLATEFLOW_HOME
# before `babs init`). The client version is recorded for provenance.
export TEMPLATEFLOW_CLIENT="${TEMPLATEFLOW_CLIENT:-25.1.1}"

# Name the wrapper image is built+registered under, and that `babs init` selects.
export CONTAINER_NAME="${CONTAINER_NAME:-qsirecon-hcp}"

# Base QSIRecon image the wrapper is built FROM. Pinned by content digest (not
# :latest) for reproducibility: this is the exact 12.7 GB image already validated
# with this pipeline. 02_build_sif.sh renders Apptainer.def from the .tmpl using
# this value.
export QSIRECON_IMAGE="${QSIRECON_IMAGE:-pennlinc/qsirecon@sha256:1ae7295e6b6bc347e29ce368f620fe5c0f82f641a784c0672973d9156231a5a4}"

# Result-zip naming: sub-<id>_<ZIP_FOLDERNAME>-<ZIP_VERSION>.zip. The foldername
# must match the derivatives dir run_hcp.py writes ("qsirecon"); the version is
# the QSIRecon version stamp BABS records.
export ZIP_FOLDERNAME="${ZIP_FOLDERNAME:-qsirecon}"
export ZIP_VERSION="${ZIP_VERSION:-26-0-0}"

# SLURM resources per subject job. Tuned for 4 concurrent on a 32-core / 183 GB
# node (4 x 8 cpu = 32 cpu; 4 x 44 GB = 176 GB <= 183 GB, so SLURM runs exactly 4).
# This is the validated 3-concurrent profile (8 cpu, ~25 GB/subject peak, 0 OOM)
# plus one job: worst-case ~4 x 25 = 100 GB << 188 GB physical, so it stays safe.
# NOTE: this SLURM uses TaskPlugin=task/none, so per-job memory is NOT cgroup-
# enforced; MEM_PER_JOB only gates scheduling. We therefore keep concurrency
# conservative rather than pack the RAM. CPUS_PER_JOB also becomes the wrapper's
# --nprocs/--omp-nthreads; QSIRECON_MEM_MB is qsirecon's --mem (below MEM_PER_JOB).
export SLURM_PARTITION="${SLURM_PARTITION:-compute}"
export CPUS_PER_JOB="${CPUS_PER_JOB:-8}"
export MEM_PER_JOB="${MEM_PER_JOB:-44G}"
export QSIRECON_MEM_MB="${QSIRECON_MEM_MB:-40000}"
export RUNTIME_LIMIT="${RUNTIME_LIMIT:-08:00:00}"

# Subject 04_run_babs.sh processes first to validate the pipeline before the rest.
export VALIDATE_SUB="${VALIDATE_SUB:-sub-100307}"

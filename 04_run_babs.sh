#!/usr/bin/env bash
# Initialize and run the BABS project end-to-end on the local single-node SLURM.
#
# Stages: init -> check-setup --job-test -> submit one subject and verify ->
# submit the rest -> wait -> merge -> clone the output RIA and list a result zip.
#
# Prereqs: 00_install_env.sh done; 01_fix_slurm.sh run (node 'gilmore' idle);
# the container built+registered (02_build_sif.sh) and the input dataset built
# (03_build_input.py). Run from anywhere:  bash 04_run_babs.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
source "$REPO/config.sh"
RUNTIME="$BABS_HCP_RUNTIME"
PROJECT="$RUNTIME/project"

export MAMBA_ROOT_PREFIX="$HOME/micromamba"
# TemplateFlow is baked into the .sif (pinned), so jobs must NOT bind a host
# cache: unset TEMPLATEFLOW_HOME so `babs init` adds no templateflow bind/--env.
unset TEMPLATEFLOW_HOME
mkdir -p "$RUNTIME/compute"
MM="$HOME/.local/bin/micromamba run -n babs"

wait_for_slurm() {  # block until this user's SLURM queue drains
  echo ">> waiting for SLURM jobs to finish..."
  while [ "$(squeue -h -u "$USER" 2>/dev/null | wc -l)" -ne 0 ]; do
    sleep 30
  done
}

# Render the concrete YAML from the template: BABS reads it literally and does
# not expand env vars in origin_url / paths, so we substitute config values now.
YAML="$REPO/qsirecon_hcp.yaml"
sed -e "s|__INPUT_DS__|$RUNTIME/input_hcp|g" \
    -e "s|__FS_LICENSE__|$FS_LICENSE|g" \
    -e "s|__JOB_COMPUTE_SPACE__|$RUNTIME/compute|g" \
    -e "s|__ZIP_FOLDERNAME__|$ZIP_FOLDERNAME|g" \
    -e "s|__ZIP_VERSION__|$ZIP_VERSION|g" \
    -e "s|__PARTITION__|$SLURM_PARTITION|g" \
    -e "s|__CPUS__|$CPUS_PER_JOB|g" \
    -e "s|__MEM__|$MEM_PER_JOB|g" \
    -e "s|__QSIRECON_MEM__|$QSIRECON_MEM_MB|g" \
    -e "s|__RUNTIME_LIMIT__|$RUNTIME_LIMIT|g" \
    "$REPO/qsirecon_hcp.yaml.tmpl" > "$YAML"

# 1. Initialize the BABS project (skip if it already exists).
if [ ! -d "$PROJECT" ]; then
  $MM babs init \
    --container_ds "$RUNTIME/qsirecon-container" \
    --container_name "$CONTAINER_NAME" \
    --container_config "$YAML" \
    --processing_level subject \
    --queue slurm \
    "$PROJECT"
fi

# 2. Validate the whole setup with one real test job.
$MM babs check-setup --job-test "$PROJECT"

# 3. Validate the pipeline on one subject before committing the cohort.
$MM babs submit --select "$VALIDATE_SUB" "$PROJECT"
wait_for_slurm
$MM babs status "$PROJECT"

# 4. Submit all remaining subjects, then wait for completion.
$MM babs submit "$PROJECT"
wait_for_slurm
$MM babs status "$PROJECT"

# 5. Merge per-job result branches and pull the outputs out of the RIA store.
$MM babs merge "$PROJECT"
rm -rf "$RUNTIME/outputs"
$MM datalad clone "ria+file://$PROJECT/output_ria#~data" "$RUNTIME/outputs"
echo ">> result zips:"
ls -1 "$RUNTIME/outputs" | grep '\.zip$' || true
echo ">> done.  fetch one with:  datalad get -d $RUNTIME/outputs <sub>_${ZIP_FOLDERNAME}-${ZIP_VERSION}.zip"

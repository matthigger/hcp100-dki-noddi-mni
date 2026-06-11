#!/usr/bin/env bash
# Build the wrapper Apptainer image from the pinned qsirecon image ($QSIRECON_IMAGE
# in config.sh, pinned by content digest for reproducibility), then register it as
# a DataLad dataset so `babs init` can find it under $CONTAINER_NAME.
#
# Apptainer.def is rendered from Apptainer.def.tmpl here (same sed pattern
# 04_run_babs.sh uses for the YAML), filling in the pinned image and the Bootstrap
# source. If the exact pinned digest is already in the local Docker daemon we
# bootstrap from docker-daemon (no 12.7 GB re-download); otherwise we bootstrap
# from the registry (docker), which pulls the pinned digest once.
#
# The Apptainer-bundled mksquashfs (a 2026 dev build) corrupts its heap when run
# multithreaded on a large image, so we pin -processors 1.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
source "$REPO/config.sh"
RUNTIME="$BABS_HCP_RUNTIME"
SIF="$RUNTIME/$CONTAINER_NAME.sif"
CDS="$RUNTIME/qsirecon-container"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
export APPTAINER_TMPDIR="$RUNTIME/apptainer_tmp"
mkdir -p "$RUNTIME" "$APPTAINER_TMPDIR"
MM="$HOME/.local/bin/micromamba run -n babs"

# Use the local Docker daemon's copy iff it already has the exact pinned digest
# (RepoDigests lists name@sha256:... for images pulled by digest); else pull the
# pinned digest from the registry.
if docker inspect --format '{{.RepoDigests}}' "$QSIRECON_IMAGE" 2>/dev/null \
     | grep -qF "$QSIRECON_IMAGE"; then
  BOOTSTRAP="docker-daemon"
  echo ">> pinned image present in local docker daemon; bootstrapping docker-daemon"
else
  BOOTSTRAP="docker"
  echo ">> pinned image not in local daemon; bootstrapping from registry (docker)"
fi

# Pin TemplateFlow: fetch the MNI152NLin2009cAsym references into a build-only
# stage and bake them into the image, so the normalization target is hermetic and
# version-stable (no runtime host-cache bind). The exact set baked is confirmed by
# a network-isolated test run; extend the get() list below if the test reports a miss.
TF_STAGE="$APPTAINER_TMPDIR/tf_stage"
rm -rf "$TF_STAGE"; mkdir -p "$TF_STAGE"
TEMPLATEFLOW_HOME="$TF_STAGE" $MM python -c "import templateflow.api as tf; \
tf.get('MNI152NLin2009cAsym', resolution=[1, 2], suffix=['T1w', 'T2w', 'mask'], \
desc=[None, 'brain'], extension='.nii.gz')"

# Render the concrete Apptainer.def from the template (BABS/apptainer read it
# literally), substituting the pinned image, Bootstrap source, and TF stage path.
sed -e "s|__QSIRECON_IMAGE__|$QSIRECON_IMAGE|g" \
    -e "s|__BOOTSTRAP__|$BOOTSTRAP|g" \
    -e "s|__TF_STAGE__|$TF_STAGE|g" \
    "$REPO/Apptainer.def.tmpl" > "$REPO/Apptainer.def"

echo ">> building $SIF from $BOOTSTRAP://$QSIRECON_IMAGE (TemplateFlow baked)"
cd "$REPO"
apptainer build --force --mksquashfs-args "-processors 1 -mem 4G" "$SIF" Apptainer.def
rm -rf "$TF_STAGE"

echo ">> registering container '$CONTAINER_NAME' in $CDS"
[ -d "$CDS/.datalad" ] || $MM datalad create -D "$CONTAINER_NAME container" "$CDS"
if $MM datalad containers-list -d "$CDS" 2>/dev/null | grep -q "$CONTAINER_NAME"; then
  $MM datalad containers-add --update -d "$CDS" --url "$SIF" "$CONTAINER_NAME"
else
  $MM datalad containers-add -d "$CDS" --url "$SIF" "$CONTAINER_NAME"
fi
echo ">> done. container '$CONTAINER_NAME' registered in $CDS"

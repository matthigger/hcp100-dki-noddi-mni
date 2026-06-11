#!/usr/bin/env bash
# Install micromamba and create the 'babs' environment from the committed,
# version-pinned environment.yml (datalad, git-annex, datalad-container, babs).
# git-annex is a Haskell binary that is not pip-installable, so micromamba/conda
# is the low-friction way to get the whole BABS toolchain in one shot. We pin from
# our own environment.yml rather than PennLINC's moving main branch so the build
# is reproducible.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
source "$REPO/config.sh"
RUNTIME="$BABS_HCP_RUNTIME"
mkdir -p "$HOME/.local/bin" "$RUNTIME"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"

if [ ! -x "$HOME/.local/bin/micromamba" ]; then
  echo ">> installing micromamba"
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -C "$HOME/.local" -xj bin/micromamba
fi
"$HOME/.local/bin/micromamba" --version

echo ">> creating 'babs' env from environment.yml (a few minutes)"
"$HOME/.local/bin/micromamba" create -y -f "$REPO/environment.yml"

# DataLad refuses to commit without a git identity.
git config --global user.email >/dev/null 2>&1 \
  || git config --global user.email "m.higger@northeastern.edu"
git config --global user.name >/dev/null 2>&1 \
  || git config --global user.name "Matt Higger"

echo ">> versions:"
"$HOME/.local/bin/micromamba" run -n babs bash -lc \
  'babs --version; datalad --version; git-annex version | head -1'
echo ">> done.  use:  micromamba activate babs"

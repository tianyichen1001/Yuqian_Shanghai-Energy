#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Install EnergyPlus 25.1 Linux x86_64 binary from the NREL/EnergyPlus
# GitHub release. Runs as part of the devcontainer postCreateCommand.
#
# After install, `energyplus --version` should print a v25.1.x version.
#
# The release asset filename embeds an unpredictable short SHA, e.g.
#   EnergyPlus-25.1.0-<sha>-Linux-Ubuntu22.04-x86_64.sh
# So we query the GitHub releases API for the v25.1.0 tag and pick the
# Ubuntu22.04-x86_64.sh asset by name pattern.
# -----------------------------------------------------------------------------
set -euo pipefail

EPLUS_TAG="v25.1.0"
INSTALL_DIR="/usr/local/EnergyPlus-25-1-0"
ASSET_REGEX='EnergyPlus-25\.1\.0-.*-Linux-Ubuntu22\.04-x86_64\.sh'

echo ">>> Installing EnergyPlus ${EPLUS_TAG}"

if command -v energyplus >/dev/null 2>&1; then
    echo "EnergyPlus already installed at $(command -v energyplus). Skipping."
    energyplus --version || true
    exit 0
fi

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    wget \
    curl \
    jq \
    ca-certificates \
    libx11-6 \
    libgomp1

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

# Resolve the Linux Ubuntu22.04 x86_64 installer URL from the GitHub release.
ASSET_URL="$(curl -fsSL "https://api.github.com/repos/NREL/EnergyPlus/releases/tags/${EPLUS_TAG}" \
    | jq -r --arg re "$ASSET_REGEX" '.assets[] | select(.name | test($re)) | .browser_download_url' \
    | head -n 1)"

if [ -z "$ASSET_URL" ] || [ "$ASSET_URL" = "null" ]; then
    echo "ERROR: could not find an Ubuntu22.04 x86_64 asset for ${EPLUS_TAG}." >&2
    exit 1
fi

INSTALLER="${TMPDIR}/$(basename "$ASSET_URL")"
echo ">>> Downloading ${ASSET_URL}"
wget -q --show-progress -O "${INSTALLER}" "${ASSET_URL}"
chmod +x "${INSTALLER}"

# The official installer is an interactive shell archive. We extract its
# embedded tarball with --noexec and place the binaries ourselves so the
# install is fully non-interactive.
sudo "${INSTALLER}" --skip-license --target "${INSTALL_DIR}" --noexec

# Symlink the main binary so it's on PATH.
sudo ln -sf "${INSTALL_DIR}/energyplus" /usr/local/bin/energyplus
sudo ln -sf "${INSTALL_DIR}/EnergyPlus" /usr/local/bin/EnergyPlus 2>/dev/null || true
sudo ln -sf "${INSTALL_DIR}/ExpandObjects" /usr/local/bin/ExpandObjects 2>/dev/null || true

echo ">>> EnergyPlus installed:"
energyplus --version || echo "WARNING: energyplus binary not on PATH"

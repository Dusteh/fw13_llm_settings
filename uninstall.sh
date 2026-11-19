#!/usr/bin/env bash
# Uninstall everything install.sh set up on a Framework 13 (7840U):
#   1. Remove the ryzen_smu DKMS module (--all for every kernel)
#   2. Delete the RyzenAdj binary from ~/bin
#   3. Revoke execute permissions on this repo's scripts
#
# Safe to re-run: finished steps are skipped.
#
#   ./uninstall.sh
#

set -euo pipefail

SRC_DIR="${SRC_DIR:-$HOME/.local/src}"
SMU_VERSION="0.1.7"
BIN_DIR="$HOME/bin"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

# 1. Unload ryzen_smu if it's loaded
step "Unloading ryzen_smu"
if lsmod | grep -q '^ryzen_smu '; then
    echo "Unloading ryzen_smu module …"
    sudo rmmod ryzen_smu || warn "could not unload (may be in use)"
else
    echo "ryzen_smu is already unloaded."
fi

# 2. Remove DKMS package for every kernel, then delete /usr/src tree
step "Removing ryzen_smu DKMS"
dkms_pkg="ryzen_smu/$SMU_VERSION"
if dkms status "$dkms_pkg" 2>/dev/null | grep -q installed; then
    echo "Removing $dkms_pkg for all kernels …"
    sudo dkms remove "$dkms_pkg" --all
else
    echo "DKMS package $dkms_pkg is not installed."
fi

dkms_src="/usr/src/ryzen-smu-${SMU_VERSION}"
if [ -d "$dkms_src" ]; then
    echo "Deleting DKMS source tree at $dkms_src"
    sudo rm -rf "$dkms_src"
else
    echo "DKMS source tree already removed."
fi

# 3. Remove the RyzenAdj binary from ~/bin
step "Removing RyzenAdj"
if [ -f "$BIN_DIR/ryzenadj" ]; then
    echo "Deleting $BIN_DIR/ryzenadj"
    rm -f "$BIN_DIR/ryzenadj"
else
    echo "RyzenAdj not found at $BIN_DIR/ryzenadj."
fi

# 4. Delete the cloned source repos (optional, comment out if you want to keep them)
step "Cleaning up source repos"
for d in "$SRC_DIR/ryzen_smu" "$SRC_DIR/RyzenAdj"; do
    if [ -d "$d" ]; then
        echo "Removing $d"
        rm -rf "$d"
    else
        echo "$(basename "$d") already removed."
    fi
done

# 5. Revoke execute permission on this repo's scripts
step "Revoking execute permissions"
for p in "$REPO_DIR/llm_mode.sh" "$REPO_DIR/llm_perflog.py"; do
    if [ -x "$p" ]; then
        chmod -x "$p"
        echo "Removed +x from $(basename "$p")"
    else
        echo "$(basename "$p") is not executable."
    fi
done

step "Done"
echo ""
echo "Summary of what was removed:"
echo "  DKMS module   ryzen_smu/$SMU_VERSION         — uninstalled + source pruned"
echo "  RyzenAdj       $BIN_DIR/ryzenadj              — deleted"
echo "  Source repos    $SRC_DIR/{ryzen_smu,RyzenAdj}  — pruned (if still present)"
echo ""
echo "NOTE: Power / thermal limits set by llm_mode.sh reset automatically on"
echo "      reboot or charger disconnect — no cleanup needed there."


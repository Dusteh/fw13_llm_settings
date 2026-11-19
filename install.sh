#!/usr/bin/env bash
# Install everything llm_mode.sh needs on a fresh Ubuntu/Debian system:
#   1. the amkillam fork of the ryzen_smu kernel module (DKMS), which knows Phoenix
#      and lets RyzenAdj work with Secure Boot on
#   2. RyzenAdj, built from source and copied to ~/bin/ryzenadj
#
# Safe to re-run: finished steps are skipped.
#
#   ./install.sh
#
# Overrides: SRC_DIR (where repos are cloned, default ~/.local/src),
#            RYZENADJ_REF (branch/tag/commit, default main; tested at 44438e1)
set -euo pipefail

SRC_DIR="${SRC_DIR:-$HOME/.local/src}"
RYZENADJ_REF="${RYZENADJ_REF:-main}"
SMU_REPO="https://github.com/amkillam/ryzen_smu"
SMU_VERSION="0.1.7"
RYZENADJ_REPO="https://github.com/FlyGoat/RyzenAdj"
BIN_DIR="$HOME/bin"
MOK_KEY="/var/lib/shim-signed/mok/MOK.der"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Clone a repo, or update it if it's already there, then check out a ref.
fetch_repo() {
    local url=$1 dir=$2 ref=${3:-}
    if [ -d "$dir/.git" ]; then
        git -C "$dir" fetch --quiet --tags origin
    else
        git clone --quiet "$url" "$dir"
    fi
    if [ -n "$ref" ]; then
        git -C "$dir" checkout --quiet "$ref"
        # Fast-forward if the ref is a branch.
        git -C "$dir" merge --quiet --ff-only "origin/$ref" 2>/dev/null || true
    fi
}

[ "$(id -u)" -ne 0 ] || die "run as your normal user, not root; sudo is used where needed"

step "Checking hardware and OS"
command -v apt-get >/dev/null || die "this script expects Ubuntu/Debian (apt-get not found)"
grep -q AuthenticAMD /proc/cpuinfo || die "not an AMD CPU"
cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')
echo "CPU: $cpu"
case "$cpu" in
    *7840U*) ;;
    *) warn "tested only on a Ryzen 7 7840U (Framework 13); the limits in llm_mode.sh may be wrong for this CPU" ;;
esac

cat <<'EOF'

  WARNING: llm_mode.sh changes the APU's power and thermal limits. This can damage
  your device or shorten component life. You use it at your own risk.

EOF
read -r -p "Continue? [y/N] " reply
[[ "$reply" =~ ^[Yy]$ ]] || exit 1

step "Installing build dependencies"
sudo apt-get update
sudo apt-get install -y git build-essential dkms "linux-headers-$(uname -r)" cmake libpci-dev mokutil

step "Checking Secure Boot"
if mokutil --sb-state 2>/dev/null | grep -q "SecureBoot enabled"; then
    echo "Secure Boot is on; the module must be signed with an enrolled key."
    if [ ! -f "$MOK_KEY" ]; then
        warn "$MOK_KEY not found yet; DKMS will create it on the first build"
    fi
else
    echo "Secure Boot is off."
fi

step "Installing ryzen_smu $SMU_VERSION (amkillam fork)"
# The original 0.1.5 supports Zen 1-3 only; on Phoenix it loads but never binds.
for old in $(dkms status ryzen_smu 2>/dev/null | grep -o 'ryzen_smu/[0-9.]*' | sort -u); do
    if [ "$old" != "ryzen_smu/$SMU_VERSION" ]; then
        echo "Removing $old"
        sudo rmmod ryzen_smu 2>/dev/null || true
        sudo dkms remove "$old" --all
        sudo rm -rf "/usr/src/${old/\//-}"
    fi
done
if dkms status "ryzen_smu/$SMU_VERSION" -k "$(uname -r)" 2>/dev/null | grep -q installed; then
    echo "Already installed for $(uname -r)."
else
    mkdir -p "$SRC_DIR"
    fetch_repo "$SMU_REPO" "$SRC_DIR/ryzen_smu"
    (cd "$SRC_DIR/ryzen_smu" && sudo make dkms-install)
fi

# The key is created by the first DKMS build, so check enrollment after it.
if mokutil --sb-state 2>/dev/null | grep -q "SecureBoot enabled" && [ -f "$MOK_KEY" ] \
        && ! mokutil --test-key "$MOK_KEY" 2>/dev/null | grep -q "already enrolled"; then
    warn "the DKMS signing key is not enrolled, so the module won't load under Secure Boot."
    echo "Pick a one-time password at the prompt, then reboot and choose"
    echo "'Enroll MOK' in the blue MOK Manager screen, and run this script again."
    sudo mokutil --import "$MOK_KEY"
    exit 0
fi

sudo modprobe ryzen_smu
[ -d /sys/kernel/ryzen_smu_drv ] \
    || die "ryzen_smu loaded but /sys/kernel/ryzen_smu_drv is missing (unsupported CPU?)"
echo "ryzen_smu driver version: $(cat /sys/kernel/ryzen_smu_drv/drv_version)"

step "Building RyzenAdj ($RYZENADJ_REF)"
mkdir -p "$SRC_DIR" "$BIN_DIR"
fetch_repo "$RYZENADJ_REPO" "$SRC_DIR/RyzenAdj" "$RYZENADJ_REF"
cmake -S "$SRC_DIR/RyzenAdj" -B "$SRC_DIR/RyzenAdj/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$SRC_DIR/RyzenAdj/build" -j "$(nproc)"
install -m 755 "$SRC_DIR/RyzenAdj/build/ryzenadj" "$BIN_DIR/ryzenadj"
echo "Installed $BIN_DIR/ryzenadj"

step "Checking RyzenAdj can read the limits"
sudo "$BIN_DIR/ryzenadj" -i | grep -E 'STAPM LIMIT|PPT LIMIT FAST|PPT LIMIT SLOW|APU SKIN' || true

chmod +x "$REPO_DIR/llm_mode.sh" "$REPO_DIR/llm_perflog.py"

step "Done"
cat <<EOF
Apply the 22 W coding cap before an LLM session:

    $REPO_DIR/llm_mode.sh

The cap resets on reboot and when the charger is unplugged, so run it again then.
Optional logging (needs Ollama): $REPO_DIR/llm_perflog.py start
EOF

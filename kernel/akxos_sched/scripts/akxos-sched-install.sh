#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/akxOS-Pi}"
DRIVER_DIR="$REPO_ROOT/kernel/akxos_sched"
MODULE_NAME="akxos_sched"
KO_FILE="$DRIVER_DIR/${MODULE_NAME}.ko"
PROC_FILE="/proc/akxos_sched"

echo "[akxOS] Repo root     : $REPO_ROOT"
echo "[akxOS] Driver dir    : $DRIVER_DIR"

if [ ! -d "$DRIVER_DIR" ]; then
    echo "[akxOS][error] Driver directory not found: $DRIVER_DIR" >&2
    exit 1
fi

cd "$DRIVER_DIR"

echo "[akxOS] Removing old module if loaded..."
if lsmod | grep -q "^${MODULE_NAME}\b"; then
    sudo rmmod "$MODULE_NAME"
    echo "[akxOS] Removed old $MODULE_NAME"
else
    echo "[akxOS] No loaded $MODULE_NAME module found"
fi

echo "[akxOS] Cleaning build..."
make clean

echo "[akxOS] Building module..."
make

if [ ! -f "$KO_FILE" ]; then
    echo "[akxOS][error] Build did not produce $KO_FILE" >&2
    exit 1
fi

echo "[akxOS] Loading module..."
sudo insmod "$KO_FILE"

echo "[akxOS] Verifying /proc interface..."
if [ ! -e "$PROC_FILE" ]; then
    echo "[akxOS][error] $PROC_FILE not found after insmod" >&2
    dmesg | tail -30
    exit 1
fi

echo "[akxOS] Loaded successfully. Current status:"
cat "$PROC_FILE"

echo
echo "[akxOS] Recent kernel logs:"
dmesg | tail -10

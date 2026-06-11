#!/usr/bin/env bash
# Repair the local single-node SLURM cluster (node 'gilmore') so jobs can run.
#
# The node sits in INVALID_REG with "Low socket*core*thread count" because this
# is an Intel hybrid CPU (i9-14900K: 8 P-cores w/ hyperthreading + 16 E-cores
# without). lscpu reports 1 socket x 24 cores x 2 threads = 48, but there are
# only 32 logical CPUs, so SLURM's Sockets*Cores*Threads model rejects the node.
#
# Fix: tell slurmd to trust the configured layout (SlurmdParameters=config_overrides)
# and declare a clean 32-core node line. Then restart the daemons and resume.
#
# Run with:  sudo bash 01_fix_slurm.sh   (auto-elevates if you forget sudo)
set -euo pipefail
[ "${EUID:-$(id -u)}" -eq 0 ] || exec sudo -E bash "$0" "$@"

CONF=/etc/slurm/slurm.conf
[ -f "$CONF" ] || { echo "ERROR: $CONF not found"; exit 1; }

cp -n "$CONF" "${CONF}.bak.$(date +%s)"

# 1. Make slurmd trust the configured topology instead of probing hardware.
if grep -qE '^\s*SlurmdParameters=' "$CONF"; then
  grep -qE '^\s*SlurmdParameters=.*config_overrides' "$CONF" \
    || sed -i -E 's|^(\s*SlurmdParameters=.*)$|\1,config_overrides|' "$CONF"
else
  echo 'SlurmdParameters=config_overrides' >> "$CONF"
fi

# 2. Declare a clean 32-core node line (32 cores x 1 thread = 32 CPUs).
NODELINE='NodeName=gilmore CPUs=32 Boards=1 SocketsPerBoard=1 CoresPerSocket=32 ThreadsPerCore=1 RealMemory=183339 State=UNKNOWN'
sed -i -E "s|^NodeName=gilmore.*$|${NODELINE}|" "$CONF"

echo ">> updated config:"
grep -E '^(SlurmdParameters|NodeName=gilmore|PartitionName)' "$CONF"

# 3. Restart daemons and bring the node back.
systemctl restart slurmctld
sleep 2
systemctl restart slurmd
sleep 2
scontrol update nodename=gilmore state=resume || true
sleep 2

echo ">> result:"
sinfo
scontrol show node gilmore | grep -E 'State|CPUTot|RealMemory|Reason' || true
echo ">> if State shows 'idle', SLURM is ready."

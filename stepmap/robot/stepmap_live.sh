#!/usr/bin/env bash
# StepMap live on the robot: live server (port 8060) + bridge from the measurement nodes.
# Sensors and measurement nodes are started separately (sensors.launch.py, terrain_geometry_node.py, inspect.sh).
#   ~/terrain_dataset/stepmap_live.sh [SESSION]          dashboard: http://<robot>:8060/
# Laptop copy (resumes after any disconnect):
#   stepmap live -d sessions/<SESSION> --pull http://192.168.123.18:8060   (Tailscale: http://100.65.117.65:8060)
SESSION=${1:-$(date +%Y%m%d_%H%M%S)}
source ~/terrain_dataset/env.sh >/dev/null 2>&1
# VWorld map key (Korean base map / satellite) from a file outside the repo, if present
[ -f ~/stepmap_live/vworld_key ] && export STEPMAP_VWORLD_KEY=$(cat ~/stepmap_live/vworld_key)
D=$HOME/stepmap_sessions/$SESSION
mkdir -p "$D"
cd ~/stepmap_live/stepmap || exit 1
python3 -m stepmap live -d "$D" --port 8060 -c config.yaml >> "$D/live.log" 2>&1 &
LIVE=$!
trap 'kill $LIVE 2>/dev/null' EXIT
echo "session $SESSION: live server pid $LIVE (log $D/live.log), dashboard http://$(hostname -I | awk '{print $1}'):8060/"
python3 ~/terrain_dataset/stepmap_bridge.py --ros-args -p session:="$SESSION"

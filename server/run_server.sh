#!/bin/bash
# Start the RobotX API on the robot computer.  Usage: ./run_server.sh [port]
cd "$(dirname "$0")"
source /opt/ros/jazzy/setup.bash
[ -f ~/RobotX/install/setup.bash ] && source ~/RobotX/install/setup.bash   # rx_msgs for the mission panel
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"  # must match services.yaml
exec ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port "${1:-8000}" --timeout-graceful-shutdown 3   # don't hang on open websockets

# RobotX Mission Control

- `server/` FastAPI on the robot: start/stop services (`services.yaml`), MAVROS telemetry over WebSocket.
- `web/` Vue 3 + Vite GUI on the host: auto-discovers the API, map, telemetry, services, logs.

Robot:  `~/GUI_RobotX/server/run_server.sh [port]`  (default 8000)
Host:   `cd web && npm install && npm run dev`  -> http://localhost:5173
Edit `web/src/config.js` for the robot hostnames/IPs probed by auto-connect.

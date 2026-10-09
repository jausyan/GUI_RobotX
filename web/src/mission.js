// Display names for the rx_msgs enums (mirrors ~/RobotX/src/rx_msgs/msg)
export const ROBOT_STATE = { 0: 'UNKNOWN', 1: 'KILLED', 2: 'MANUAL', 3: 'AUTO' }
export const RX_TASK = {
  0: 'Unknown', 1: 'Standing down', 2: 'Safe Passage', 3: 'Infra Survey & Repair',
  4: 'Coordinated Logistics', 5: 'Dynamic Incident',
}
// Buoy classes come from /vision_geo/map/<name>; known names get a fixed colour, any new class a palette colour.
const BUOY_FIXED = { buoy_entry: '#4da3ff', buoy_exit: '#ff8a3d', buoy_red: '#ff5d73', buoy_green: '#3ddc97', buoy_off: '#8a90ad' }
const BUOY_PALETTE = ['#f472b6', '#facc15', '#22d3ee', '#c084fc', '#a3e635', '#fb7185']
export function buoyColor(name, index = 0) {
  return BUOY_FIXED[name] ?? BUOY_PALETTE[index % BUOY_PALETTE.length]
}
export const buoyLabel = (name) => name.replace(/^buoy_/, '')
export const VEHICLES = [
  { key: 'uav', label: 'UAV', color: '#a46cff', self: true },
  { key: 'usv', label: 'USV', color: '#2ee6d6' },
  { key: 'uuv', label: 'UUV', color: '#ffc857' },
]
export const HB_TIMEOUT_S = 3

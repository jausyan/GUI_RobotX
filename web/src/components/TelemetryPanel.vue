<script setup>
import { computed } from 'vue'
import { useRobot } from '../stores/robot'
const robot = useRobot()
const t = computed(() => robot.telem || {})
const f = (v, d = 1, u = '') => (v == null || (typeof v === 'number' && isNaN(v)) ? '—' : v.toFixed(d) + u)
const fixText = computed(() => {
  const s = t.value.gps?.fix
  return s == null ? '—' : s < 0 ? 'No fix' : ['Fix', 'SBAS', 'GBAS'][s] ?? s
})
const batt = computed(() => t.value.battery?.percent)
const battClass = computed(() => (batt.value == null ? '' : batt.value < 20 ? 'bad' : batt.value < 40 ? 'warn' : 'ok'))
const hbAge = computed(() => (robot.heartbeatAge == null ? '—' : robot.heartbeatAge.toFixed(1) + ' s'))
</script>

<template>
  <section class="telem-inner">
    <header class="ph">
      <h3>Telemetry</h3>
      <span class="spacer" />
      <span v-if="robot.telem && !robot.telem.ros" class="tag warn">ROS unavailable</span>
      <span v-else class="tag" :class="robot.vehicleAlive ? 'ok' : 'bad'">{{ robot.vehicleAlive ? 'live' : 'stale' }}</span>
    </header>

    <div class="group">
      <div class="kv"><span>FCU</span><b :class="t.state?.connected ? 'ok' : ''">{{ t.state ? (t.state.connected ? 'Connected' : 'Disconnected') : '—' }}</b></div>
      <div class="kv"><span>Mode</span><b class="accent">{{ t.state?.mode || '—' }}</b></div>
      <div class="kv"><span>Armed</span><b :class="t.state?.armed ? 'bad' : ''">{{ t.state ? (t.state.armed ? 'ARMED' : 'Disarmed') : '—' }}</b></div>
      <div class="kv"><span>Heartbeat</span><b>{{ hbAge }}</b></div>
    </div>

    <div class="group">
      <div class="batt">
        <div class="batt-top"><span>Battery</span><b :class="battClass">{{ f(batt, 0, '%') }}</b><small>{{ f(t.battery?.voltage, 2, ' V') }}</small></div>
        <div class="bar"><i :class="battClass" :style="{ width: Math.max(0, Math.min(100, batt || 0)) + '%' }" /></div>
      </div>
    </div>

    <div class="group">
      <div class="kv"><span>GPS</span><b :class="t.gps && t.gps.fix >= 0 ? 'ok' : ''">{{ fixText }}</b></div>
      <div class="kv"><span title="/rian/rangefinder/rangefinder">Altitude</span><b>{{ f(t.range?.range, 2, ' m') }}</b></div>
      <div class="kv"><span>Speed</span><b>{{ f(t.hud?.groundspeed, 1, ' m/s') }}</b></div>
      <div class="kv"><span>Heading</span><b>{{ f(t.hud?.heading, 0, '°') }}</b></div>
      <div class="kv full"><span>Position</span><b class="mono">{{ f(t.gps?.lat, 7) }}, {{ f(t.gps?.lon, 7) }}</b></div>
      <div class="kv full"><span>Local pose</span><b class="mono">{{ f(t.pose?.x, 2) }}, {{ f(t.pose?.y, 2) }}, {{ f(t.pose?.z, 2) }}</b></div>
    </div>
  </section>
</template>

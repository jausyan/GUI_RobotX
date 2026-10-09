<script setup>
import { ref, computed } from 'vue'
import { useRobot } from '../stores/robot'
const robot = useRobot()
const manual = ref(robot.manualHost)
const clock = computed(() => new Date(robot.now).toISOString().replace('T', '  ').slice(0, 21) + ' UTC')
</script>

<template>
  <header class="topbar">
    <div class="brand"><span class="logo">◆</span> RobotX <em>Mission Control</em></div>
    <span class="pill" :class="robot.status === 'connected' ? 'ok' : 'warn'">
      <i class="dot" />{{ robot.status === 'connected' ? `${robot.robotName} · ${robot.host}` : 'Searching for robot API…' }}
    </span>
    <span v-if="robot.status === 'connected'" class="pill" :class="robot.vehicleAlive ? 'ok' : 'bad'">
      <i class="dot" />{{ robot.vehicleAlive ? 'Heartbeat' : 'No heartbeat' }}
    </span>
    <span v-if="robot.telem?.state" class="pill" :class="robot.telem.state.armed ? 'bad' : 'accent'">
      {{ robot.telem.state.armed ? 'ARMED' : 'DISARMED' }} · {{ robot.telem.state.mode || '—' }}
    </span>
    <span class="spacer" />
    <form v-if="robot.status !== 'connected'" @submit.prevent="robot.setManualHost(manual)">
      <input v-model="manual" placeholder="manual IP[:port] ⏎" />
    </form>
    <span class="clock">{{ clock }}</span>
  </header>
</template>

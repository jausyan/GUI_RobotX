<script setup>
import { useRobot } from '../stores/robot'
const robot = useRobot()
const stateClass = (s) => ({ running: 'ok', crashed: 'bad', stopping: 'warn' }[s] || '')
</script>

<template>
  <section class="col">
    <header class="ph">
      <h3>Services</h3>
      <span class="spacer" />
      <button :disabled="!robot.host" @click="robot.startAll()">▶ All</button>
      <button class="danger" :disabled="!robot.host" @click="robot.stopAll()">■ All</button>
    </header>
    <div class="services">
      <p v-if="!robot.host" class="muted">Not connected to the robot API.</p>
      <div v-for="s in robot.services" :key="s.name" class="svc">
        <span class="led" :class="stateClass(s.state)" />
        <div class="svc-name"><b>{{ s.label }}</b>
          <small class="muted">{{ s.state }}<template v-if="s.pid"> · {{ Math.round(s.uptime) }}s</template></small>
          <small v-if="s.detail" class="detail" :title="s.detail">{{ s.detail }}</small></div>
        <span class="spacer" />
        <button :disabled="s.state === 'running'" @click="robot.serviceAction(s.name, 'start')">Start</button>
        <button class="danger" :disabled="s.state !== 'running'" @click="robot.serviceAction(s.name, 'stop')">Stop</button>
      </div>
    </div>
  </section>
</template>

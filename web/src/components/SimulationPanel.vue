<script setup>
import { useRobot } from '../stores/robot'
const robot = useRobot()
// order of a normal run; each button publishes the string on /mission/order
const orders = [
  { order: 'RUN-START', hint: 'start the run' },
  { order: 'UAV-GO', hint: 'start vision / go' },
  { order: 'MISSION-DONE', hint: 'finish the mission' },
]
const time = (t) => new Date(t).toTimeString().slice(0, 8)
</script>

<template>
  <section class="col">
    <header class="ph">
      <h3>Simulation</h3>
      <span class="spacer" />
      <span class="tag">/mission/order</span>
    </header>
    <div class="sim">
      <button v-for="o in orders" :key="o.order" class="sim-btn" :disabled="!robot.host" @click="robot.sendOrder(o.order)">
        <b>{{ o.order }}</b><small>{{ o.hint }}</small>
      </button>
    </div>
    <ul class="events sim-log">
      <li v-for="(e, i) in robot.orderLog" :key="i">
        <time>{{ time(e.t) }}</time>
        <span :class="e.ok ? 'ok' : e.note ? 'bad' : 'muted'">{{ e.order }} {{ e.ok ? '· sent' : e.note || '…' }}</span>
      </li>
      <li v-if="!robot.orderLog.length" class="muted empty">Nothing sent yet.</li>
    </ul>
  </section>
</template>

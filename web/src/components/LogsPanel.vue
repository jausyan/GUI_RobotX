<script setup>
import { ref, watch, nextTick } from 'vue'
import { useRobot } from '../stores/robot'
const robot = useRobot()
const logName = ref('mavros')
const lines = ref([])
const box = ref(null)
let ws

function openLogs() {
  ws?.close()
  lines.value = []
  if (!robot.host) return
  ws = new WebSocket(`ws://${robot.host}/ws/logs/${logName.value}`)
  ws.onmessage = async (e) => {
    lines.value.push(e.data)
    if (lines.value.length > 500) lines.value.shift()
    await nextTick()
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  }
}
watch([logName, () => robot.host], openLogs, { immediate: true })
</script>

<template>
  <section class="col">
    <header class="ph">
      <h3>Logs</h3>
      <span class="spacer" />
      <select v-model="logName"><option v-for="s in robot.services" :key="s.name" :value="s.name">{{ s.label }}</option></select>
      <button @click="lines = []">Clear</button>
    </header>
    <pre ref="box" class="logbox">{{ lines.join('\n') || 'No output yet.' }}</pre>
  </section>
</template>

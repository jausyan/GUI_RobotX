<script setup>
import { computed, ref } from 'vue'
import { useRobot } from '../stores/robot'

const robot = useRobot()
const copied = ref('')

const gps = computed(() => robot.telem?.gps)
const hasGps = computed(() => gps.value && gps.value.lat != null && !isNaN(gps.value.lat))
const noFix = computed(() => hasGps.value && gps.value.fix < 0)

const arr = (key) => `[${robot.captures.map((c) => c[key].toFixed(7)).join(', ')}]`
const latText = computed(() => `survey_lat: ${arr('lat')}`)
const lonText = computed(() => `survey_lon: ${arr('lon')}`)

async function copy(which) {
  const text = which === 'lat' ? latText.value : which === 'lon' ? lonText.value : `${latText.value}\n${lonText.value}`
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove()
  }
  copied.value = which
  setTimeout(() => (copied.value = ''), 1200)
}
</script>

<template>
  <section class="col gps">
    <header class="ph">
      <h3>GPS Capture</h3>
      <span class="count">{{ robot.captures.length }} pts</span>
      <span class="spacer" />
      <button class="primary" :disabled="!hasGps" @click="robot.capturePoint()">● Capture position</button>
    </header>

    <div class="live">
      <span class="muted">Live</span>
      <b v-if="hasGps">{{ gps.lat.toFixed(7) }}, {{ gps.lon.toFixed(7) }}</b>
      <b v-else class="muted">no GPS data</b>
      <span v-if="noFix" class="tag warn">no fix</span>
    </div>

    <div class="gps-body">
    <div class="points">
      <table v-if="robot.captures.length">
        <thead><tr><th>#</th><th>Lat</th><th>Lon</th><th /></tr></thead>
        <tbody>
          <tr v-for="c in robot.captures" :key="c.id">
            <td class="idx">P{{ c.id }}<span v-if="c.fix < 0" class="nofix" title="captured without a GPS fix">!</span></td>
            <td>{{ c.lat.toFixed(7) }}</td>
            <td>{{ c.lon.toFixed(7) }}</td>
            <td><button class="ghost" title="Remove" @click="robot.removeCapture(c.id)">✕</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted empty">No points captured yet.</p>
    </div>

    <div class="out">
      <div class="out-row"><pre>{{ latText }}</pre>
        <button :disabled="!robot.captures.length" @click="copy('lat')">{{ copied === 'lat' ? '✓ Copied' : 'Copy' }}</button></div>
      <div class="out-row"><pre>{{ lonText }}</pre>
        <button :disabled="!robot.captures.length" @click="copy('lon')">{{ copied === 'lon' ? '✓ Copied' : 'Copy' }}</button></div>
      <div class="out-bar">
        <button :disabled="!robot.captures.length" @click="copy('both')">{{ copied === 'both' ? 'Copied ✓' : 'Copy both' }}</button>
        <button class="danger" :disabled="!robot.captures.length" @click="robot.clearCaptures()">Clear</button>
      </div>
    </div>
    </div>
  </section>
</template>

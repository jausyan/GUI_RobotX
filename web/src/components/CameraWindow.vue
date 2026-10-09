<script setup>
import { computed, ref, watch } from 'vue'
import { useRobot } from '../stores/robot'
const robot = useRobot()
const props = defineProps({ boundsEl: Object })
const emit = defineEmits(['close'])
const mini = ref(false)
const video = computed(() => robot.telem?.video)
const live = computed(() => !!video.value?.live)
const recording = computed(() => !!robot.telem?.recorder?.recording)
const recTime = computed(() => { const t = Math.floor(robot.telem?.recorder?.elapsed || 0); return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}` })
// follow the stream's own shape (848x480 = 16:9, 640x480 = 4:3); 4:3 while there is no signal
const ratio = computed(() => (video.value?.width && video.value?.height ? video.value.width / video.value.height : 4 / 3))
// a fresh URL each time the feed comes back, so the <img> reconnects instead of showing a stale stream
const nonce = ref(0)
watch(live, (v) => { if (v) nonce.value++ })
const src = computed(() => (live.value && robot.base ? `${robot.base}/video?n=${nonce.value}` : ''))
const pos = ref(null) // null = anchored top-right; otherwise {x, y}
const win = ref(null)
let drag = null

function down(e) {
  if (e.target.closest('button')) return
  const box = win.value.getBoundingClientRect()
  const parent = win.value.offsetParent.getBoundingClientRect()
  drag = { dx: e.clientX - box.left, dy: e.clientY - box.top, parent }
  pos.value = { x: box.left - parent.left, y: box.top - parent.top }
  e.currentTarget.setPointerCapture(e.pointerId)
}
function move(e) {
  if (!drag) return
  const w = win.value
  const x = e.clientX - drag.parent.left - drag.dx
  const y = e.clientY - drag.parent.top - drag.dy
  pos.value = {
    x: Math.max(0, Math.min(x, drag.parent.width - w.offsetWidth)),
    y: Math.max(0, Math.min(y, drag.parent.height - 36)),
  }
}
const up = () => (drag = null)
</script>

<template>
  <div ref="win" class="cam-win" :class="{ mini }"
       :style="pos ? { left: pos.x + 'px', top: pos.y + 'px', right: 'auto' } : {}">
    <div class="cam-head" @pointerdown="down" @pointermove="move" @pointerup="up">
      <span class="rec" :class="{ on: live }" /> <b>Camera</b>
      <span class="spacer" />
      <span v-if="recording" class="tag bad">● REC {{ recTime }}</span>
      <span v-if="live" class="tag ok">live · {{ video.width }}×{{ video.height }} · {{ video.fps }} fps</span>
      <span v-else class="tag">no signal</span>
      <button class="ghost" title="Camera settings & recording" @click="robot.cameraDialog = true">⚙</button>
      <button class="ghost" :title="mini ? 'Expand' : 'Minimize'" @click="mini = !mini">{{ mini ? '▢' : '–' }}</button>
      <button class="ghost" title="Close" @click="emit('close')">✕</button>
    </div>
    <div v-show="!mini" class="cam-body" :style="{ aspectRatio: ratio }">
      <img v-if="src" :src="src" class="cam-img" alt="camera" draggable="false" />
      <template v-else>
        <div class="reticle" />
        <span>No signal</span>
        <small>Waiting for the vision stream</small>
      </template>
    </div>
  </div>
</template>

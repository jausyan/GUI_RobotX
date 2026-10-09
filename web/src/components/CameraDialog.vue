<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRobot } from '../stores/robot'
import Modal from './Modal.vue'

const robot = useRobot()
const tab = ref('image')
const info = ref(null)                 // GET /camera
const draft = reactive({})             // control values being edited
const busy = ref(false)
const mode = reactive({ fourcc: 'MJPG', width: 1280, height: 720, fps: 30 })
const rec = reactive({ kind: 'video', name: 'dataset', interval: 1, quality: 'balanced', undistort: true })
const library = ref([])
const armDelete = ref(null)
let timer

// the controls camera_setup.sh deals with, grouped; anything the camera does not have is skipped
const GROUPS = [
  { title: 'Focus', items: [['focus_automatic_continuous', 'Autofocus'], ['focus_absolute', 'Focus distance', '0 = infinity (far)']] },
  { title: 'Exposure', items: [['auto_exposure', 'Exposure mode', 'Manual uses the exposure time below; Aperture Priority is automatic'],
    ['exposure_time_absolute', 'Exposure time', '× 100 µs — shorter = less motion blur'],
    ['exposure_dynamic_framerate', 'Dynamic framerate', 'on = the camera may drop to 15 fps in low light'], ['gain', 'Gain']] },
  { title: 'White balance', items: [['white_balance_automatic', 'Auto white balance'], ['white_balance_temperature', 'Temperature', 'Kelvin — daylight ≈ 5000–5500']] },
  { title: 'Image', items: [['brightness', 'Brightness'], ['contrast', 'Contrast'], ['saturation', 'Saturation'], ['sharpness', 'Sharpness'],
    ['backlight_compensation', 'Backlight compensation'], ['power_line_frequency', 'Power line frequency', '50 Hz in Indonesia / Singapore']] },
]

const byName = computed(() => Object.fromEntries((info.value?.controls || []).map((c) => [c.name, c])))
const dirty = computed(() => Object.keys(draft).filter((n) => byName.value[n] && draft[n] !== byName.value[n].value))
const inactive = (n) => {
  if (n === 'exposure_time_absolute') return draft.auto_exposure !== 1
  if (n === 'focus_absolute') return draft.focus_automatic_continuous === 1
  if (n === 'white_balance_temperature') return draft.white_balance_automatic === 1
  return false
}

async function load() {
  try {
    info.value = await robot.api('GET', '/camera')
    for (const c of info.value.controls) draft[c.name] = c.value
    Object.assign(mode, info.value.mode)
  } catch (e) { robot.notify(`camera: ${e.message}`, 'bad') }
}
async function loadLibrary() {
  try { library.value = await robot.api('GET', '/recordings') } catch { /* keep the old list */ }
}
onMounted(() => { load(); loadLibrary(); timer = setInterval(() => { loadLibrary(); if (tab.value === 'record') refreshUsers() }, 3000) })
onBeforeUnmount(() => clearInterval(timer))
async function refreshUsers() {
  try { info.value.users = (await robot.api('GET', '/camera')).users } catch { /* ignore */ }
}

async function applyChanges() {
  busy.value = true
  try {
    const controls = Object.fromEntries(dirty.value.map((n) => [n, draft[n]]))
    const r = await robot.api('POST', '/camera/controls', { controls })
    afterApply(r)
  } catch (e) { robot.notify(e.message, 'bad') } finally { busy.value = false }
}
async function applyAndSave() {
  busy.value = true
  try {
    if (dirty.value.length) afterApply(await robot.api('POST', '/camera/controls', { controls: Object.fromEntries(dirty.value.map((n) => [n, draft[n]])) }), true)
    const r = await robot.api('POST', '/camera/save')
    info.value.saved = r.saved
    robot.notify('Camera config saved — applied again on API start and before Vision starts')
  } catch (e) { robot.notify(e.message, 'bad') } finally { busy.value = false }
}
async function restoreSaved() {
  busy.value = true
  try { afterApply(await robot.api('POST', '/camera/restore')) }
  catch (e) { robot.notify(e.message, 'bad') } finally { busy.value = false }
}
const savedAt = computed(() => {
  const t = info.value?.saved?.saved_at
  return t ? new Date(t * 1000).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : null
})
async function preset(name) {
  busy.value = true
  try { afterApply(await robot.api('POST', `/camera/preset/${name}`)) }
  catch (e) { robot.notify(e.message, 'bad') } finally { busy.value = false }
}
function afterApply(r, quiet = false) {
  info.value.controls = r.controls
  if (r.saved) info.value.saved = r.saved
  for (const c of r.controls) draft[c.name] = c.value
  const failed = r.results.filter((x) => !x.ok && x.error !== 'not on this camera')
  if (failed.length) robot.notify(`Applied, but ${failed.map((f) => f.name).join(', ')} failed`, 'bad')
  else if (!quiet) robot.notify('Camera settings applied (not saved yet)')
}

// ---- capture mode -------------------------------------------------------------------------------
const fmt = computed(() => info.value?.modes.find((m) => m.fourcc === mode.fourcc))
const sizes = computed(() => fmt.value?.sizes || [])
const fpsList = computed(() => sizes.value.find((s) => s.width === mode.width && s.height === mode.height)?.fps || [])
const sizeKey = computed({
  get: () => `${mode.width}x${mode.height}`,
  set: (v) => { const [w, h] = v.split('x').map(Number); mode.width = w; mode.height = h; if (!fpsList.value.includes(mode.fps)) mode.fps = Math.max(...fpsList.value) },
})
async function saveMode() {
  try { await robot.api('POST', '/camera/mode', { ...mode }); robot.notify('Capture mode saved for recording') }
  catch (e) { robot.notify(e.message, 'bad') }
}

// ---- recording ---------------------------------------------------------------------------------------
const st = computed(() => robot.telem?.recorder || { recording: false })
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const mb = (b) => (b / 1048576).toFixed(b > 1e8 ? 0 : 1) + ' MB'
async function startRec() {
  try { await robot.api('POST', '/record/start', { ...rec }); robot.notify('Recording started') }
  catch (e) { robot.notify(e.message, 'bad') }
}
async function stopRec() {
  try { await robot.api('POST', '/record/stop'); robot.notify('Recording saved'); loadLibrary() }
  catch (e) { robot.notify(e.message, 'bad') }
}
async function del(id) {
  if (armDelete.value !== id) { armDelete.value = id; setTimeout(() => (armDelete.value = null), 3000); return }
  armDelete.value = null
  try { await robot.api('DELETE', `/recordings/${id}`); loadLibrary() } catch (e) { robot.notify(e.message, 'bad') }
}
</script>

<template>
  <Modal title="Camera" wide @close="robot.cameraDialog = false">
    <nav class="tabs">
      <button class="tab" :class="{ on: tab === 'image' }" @click="tab = 'image'">Image</button>
      <button class="tab" :class="{ on: tab === 'mode' }" @click="tab = 'mode'">Capture mode</button>
      <button class="tab" :class="{ on: tab === 'record' }" @click="tab = 'record'">Record dataset
        <span v-if="st.recording" class="rec on" style="display:inline-block;margin-left:6px" /></button>
      <span class="spacer" />
      <span class="muted mono">{{ info?.device }}</span>
    </nav>

    <p v-if="!info" class="muted">Reading the camera…</p>

    <!-- IMAGE CONTROLS: the camera_setup.sh settings -->
    <div v-else-if="tab === 'image'" class="cam-grid">
      <div class="preset-row">
        <button :disabled="busy" @click="preset('script')">Preset: camera_setup.sh</button>
        <button :disabled="busy" @click="preset('defaults')">Camera defaults</button>
        <button :disabled="busy" @click="load">Reload from camera</button>
        <span class="spacer" />
        <span v-if="dirty.length" class="tag warn">{{ dirty.length }} unsaved change{{ dirty.length > 1 ? 's' : '' }}</span>
      </div>
      <section v-for="g in GROUPS" :key="g.title" class="cgroup">
        <h4>{{ g.title }}</h4>
        <template v-for="[name, label, help] in g.items" :key="name">
          <div v-if="byName[name]" class="crow" :class="{ off: inactive(name) }">
            <label :title="help">{{ label }}</label>
            <input v-if="byName[name].type === 'bool'" type="checkbox" :checked="draft[name] === 1"
                   @change="draft[name] = $event.target.checked ? 1 : 0" />
            <select v-else-if="byName[name].type === 'menu'" v-model.number="draft[name]">
              <option v-for="m in byName[name].menu" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
            <template v-else>
              <input type="range" :min="byName[name].min" :max="byName[name].max" :step="byName[name].step" v-model.number="draft[name]" :disabled="inactive(name)" />
              <input type="number" class="num" :min="byName[name].min" :max="byName[name].max" v-model.number="draft[name]" :disabled="inactive(name)" />
            </template>
            <small v-if="help" class="muted help">{{ help }}</small>
          </div>
        </template>
      </section>
      <div class="actions saved-row">
        <span v-if="savedAt" class="muted">Saved config: {{ savedAt }} ·
          <b :class="info.saved.differs.length ? 'warn' : 'ok'">{{ info.saved.differs.length ? `camera differs in ${info.saved.differs.length} setting${info.saved.differs.length > 1 ? 's' : ''}` : 'camera matches' }}</b></span>
        <span v-else class="muted">No saved config yet.</span>
        <button v-if="info.saved.differs.length" :disabled="busy" @click="restoreSaved">Restore saved</button>
      </div>
      <div class="actions">
        <span class="muted">Apply works live, also while a vision node runs. A saved config is re-applied when the API starts and before Vision starts.</span>
        <span class="spacer" />
        <button :disabled="busy || !dirty.length" @click="applyChanges">Apply {{ dirty.length || '' }}</button>
        <button class="primary" :disabled="busy" @click="applyAndSave">{{ dirty.length ? 'Apply &amp; save config' : 'Save config' }}</button>
      </div>
    </div>

    <!-- CAPTURE MODE -->
    <div v-else-if="tab === 'mode'" class="cam-grid">
      <section class="cgroup">
        <h4>Resolution &amp; frame rate used for recording</h4>
        <div class="crow"><label>Format</label>
          <select v-model="mode.fourcc"><option v-for="m in info.modes" :key="m.fourcc" :value="m.fourcc">{{ m.fourcc }}{{ m.fourcc === 'MJPG' ? ' (compressed, full frame rate)' : ' (raw)' }}</option></select></div>
        <div class="crow"><label>Resolution</label>
          <select v-model="sizeKey"><option v-for="s in sizes" :key="`${s.width}x${s.height}`" :value="`${s.width}x${s.height}`">{{ s.width }} × {{ s.height }}</option></select></div>
        <div class="crow"><label>Frame rate</label>
          <select v-model.number="mode.fps"><option v-for="f in fpsList" :key="f" :value="f">{{ f }} fps</option></select></div>
        <p class="muted">The recorder opens the camera with exactly this mode. The vision nodes keep using the camera mode from
          their own config files (their calibration depends on it), so nothing here changes how detection runs.</p>
      </section>
      <div class="actions"><span class="spacer" /><button class="primary" @click="saveMode">Save mode</button></div>
    </div>

    <!-- RECORD -->
    <div v-else class="cam-grid">
      <section class="cgroup">
        <h4>Record from the camera</h4>
        <p v-if="info.users.length && !st.recording" class="warn">Camera is in use by <b>{{ info.users.join(', ') }}</b>. Stop it first
          (e.g. the Vision service) — only one program can open the camera.</p>
        <div class="crow"><label>Type</label>
          <select v-model="rec.kind" :disabled="st.recording">
            <option value="video">Video — MP4 (H.264, small files)</option>
            <option value="frames">Frames — JPEG stills every N seconds</option>
          </select></div>
        <div v-if="rec.kind === 'video'" class="crow"><label>Size / quality</label>
          <select v-model="rec.quality" :disabled="st.recording">
            <option value="high">High quality (larger)</option>
            <option value="balanced">Balanced</option>
            <option value="small">Small file</option>
          </select></div>
        <div class="crow"><label>Undistort</label>
          <input type="checkbox" :checked="rec.undistort" :disabled="st.recording" @change="rec.undistort = $event.target.checked" />
          <small class="muted help">like record_video.py: uses the vision_video calibration (valid for 640×480 only; skipped at other sizes)</small></div>
        <div v-if="rec.kind === 'frames'" class="crow"><label>Every</label>
          <input type="number" class="num" min="0.1" step="0.1" v-model.number="rec.interval" :disabled="st.recording" /> <span class="muted">seconds</span></div>
        <div class="crow"><label>Dataset name</label><input v-model="rec.name" maxlength="40" :disabled="st.recording" /></div>
        <p v-if="rec.undistort && (mode.width !== 640 || mode.height !== 480)" class="warn">Undistortion needs the 640×480 mode (the calibration size) —
          this recording will be raw {{ mode.width }}×{{ mode.height }}.</p>
        <p class="muted">Mode: {{ mode.fourcc }} {{ mode.width }}×{{ mode.height }} @ {{ mode.fps }} fps (see “Capture mode”). The current image
          settings are saved next to the recording in <code>meta.json</code>.</p>
        <div class="actions">
          <span v-if="st.recording" class="rec-stat"><i class="rec on" /> {{ clock(st.elapsed) }} · {{ mb(st.size) }}<template v-if="st.frames != null"> · {{ st.frames }} frames</template></span>
          <span class="spacer" />
          <button v-if="!st.recording" class="primary" :disabled="info.users.length > 0" @click="startRec">● Start recording</button>
          <button v-else class="danger" @click="stopRec">■ Stop &amp; save</button>
        </div>
      </section>

      <section class="cgroup">
        <h4>Recordings on the robot</h4>
        <table v-if="library.length" class="lib">
          <tbody>
            <tr v-for="r in library" :key="r.id">
              <td><b>{{ r.id }}</b><br /><small class="muted">{{ r.kind === 'video' ? 'video' : `${r.frames} frames` }}
                <template v-if="r.mode"> · {{ r.mode.width }}×{{ r.mode.height }}@{{ r.mode.fps }}</template>
                <template v-if="r.duration_s"> · {{ clock(r.duration_s) }}</template> · {{ mb(r.size) }}</small></td>
              <td class="rt">
                <a class="btn" :href="`${robot.base}/recordings/${r.id}/download`" download>Download</a>
                <button :class="{ danger: true }" @click="del(r.id)">{{ armDelete === r.id ? 'Sure?' : 'Delete' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">Nothing recorded yet.</p>
      </section>
    </div>
  </Modal>
</template>

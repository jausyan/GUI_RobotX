<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRobot } from '../stores/robot'
import Modal from './Modal.vue'

const robot = useRobot()
const profiles = ref([])
const selected = ref(null)
const form = ref(null)           // { id|null, name, ip, port } while adding / editing
const error = ref('')

async function load() {
  try {
    const d = await robot.api('GET', '/gcs/profiles')
    profiles.value = d.profiles
    selected.value = profiles.value.find((p) => p.id === d.last)?.id ?? profiles.value[0]?.id ?? null
  } catch (e) { error.value = e.message }
}
onMounted(load)

const chosen = computed(() => profiles.value.find((p) => p.id === selected.value))
const url = computed(() => (chosen.value ? `udp://@${chosen.value.ip}:${chosen.value.port}` : ''))

function confirm() { robot.gcsPrompt.resolve(selected.value) }
function cancel() { robot.gcsPrompt.resolve(null) }

function edit(p) { form.value = p ? { ...p } : { id: null, name: '', ip: '', port: 14550 }; error.value = '' }
async function save() {
  error.value = ''
  const f = form.value
  try {
    const body = { name: f.name, ip: f.ip, port: Number(f.port) }
    const saved = f.id ? await robot.api('PUT', `/gcs/profiles/${f.id}`, body) : await robot.api('POST', '/gcs/profiles', body)
    form.value = null
    await load()
    selected.value = saved.id
  } catch (e) { error.value = e.message }
}
async function remove(p) {
  try { await robot.api('DELETE', `/gcs/profiles/${p.id}`); await load() } catch (e) { error.value = e.message }
}
</script>

<template>
  <Modal :title="`Start ${robot.gcsPrompt.service} · choose ground station`" @close="cancel">
    <p class="muted hint">MAVROS forwards MAVLink to this laptop (<code>gcs_url</code>). Pick the profile of whoever is connecting.</p>

    <ul class="profiles">
      <li v-for="p in profiles" :key="p.id" :class="{ on: p.id === selected }" @click="selected = p.id">
        <input type="radio" :checked="p.id === selected" />
        <div class="pname"><b>{{ p.name }}</b><small class="muted mono">{{ p.ip }}:{{ p.port }}</small></div>
        <span class="spacer" />
        <button class="ghost" title="Edit" @click.stop="edit(p)">✎</button>
        <button class="ghost" title="Delete" @click.stop="remove(p)">🗑</button>
      </li>
      <li v-if="!profiles.length" class="muted empty">No profiles yet — add one below.</li>
    </ul>

    <form v-if="form" class="pform" @submit.prevent="save">
      <input v-model="form.name" placeholder="username / laptop name" maxlength="60" required />
      <input v-model="form.ip" placeholder="IP or hostname" required />
      <input v-model="form.port" type="number" min="1" max="65535" placeholder="port" required />
      <button class="primary" type="submit">{{ form.id ? 'Save' : 'Add' }}</button>
      <button type="button" @click="form = null">Cancel</button>
    </form>
    <button v-else class="add" @click="edit(null)">+ Add profile</button>

    <p v-if="error" class="bad">{{ error }}</p>

    <template #footer>
      <span class="muted mono url">{{ url }}</span>
      <span class="spacer" />
      <button @click="cancel">Cancel</button>
      <button class="primary" :disabled="!selected || !!form" @click="confirm">Start</button>
    </template>
  </Modal>
</template>

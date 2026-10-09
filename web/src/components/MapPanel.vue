<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import L from 'leaflet'
import { useRobot } from '../stores/robot'
import { VEHICLES, buoyColor, buoyLabel } from '../mission'
import CameraWindow from './CameraWindow.vue'

const robot = useRobot()
const el = ref(null)
const follow = ref(true)
const showMission = ref(true)
const camOpen = ref(true)
let map, marker, trail, capLayer, missionLayer, buoyLayer

const icon = (yaw) => L.divIcon({
  className: 'boat',
  html: `<div style="transform:rotate(${yaw}deg)">▲</div>`,
  iconSize: [24, 24], iconAnchor: [12, 12],
})
const vehIcon = (v, yaw) => L.divIcon({
  className: 'veh',
  html: `<div style="transform:rotate(${yaw}deg);color:${v.color}">▲</div><span style="color:${v.color}">${v.label}</span>`,
  iconSize: [34, 34], iconAnchor: [17, 12],
})

onMounted(() => {
  map = L.map(el.value, { zoomControl: true }).setView([-7.28, 112.79], 17)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, className: 'dark-tiles', attribution: '© OpenStreetMap contributors',
  }).addTo(map)
  trail = L.polyline([], { color: '#b07cff', weight: 3, opacity: 0.9 }).addTo(map)
  missionLayer = L.layerGroup().addTo(map)
  buoyLayer = L.layerGroup().addTo(map)
  capLayer = L.layerGroup().addTo(map)
  drawCaptures()
  setTimeout(() => map.invalidateSize(), 100)
  new ResizeObserver(() => map.invalidateSize()).observe(el.value)
})
onBeforeUnmount(() => map?.remove())

watch(() => robot.telem, (t) => {
  const g = t?.gps
  if (g && g.lat && !isNaN(g.lat)) {
    const ll = [g.lat, g.lon]
    const yaw = t.hud?.heading ?? t.pose?.yaw ?? 0
    if (!marker) {
      marker = L.marker(ll, { icon: icon(yaw), zIndexOffset: 1000 }).addTo(map)
      map.setView(ll, 18)
    } else {
      marker.setLatLng(ll)
      marker.setIcon(icon(yaw))
    }
    trail.setLatLngs(robot.track)
    if (follow.value) map.panTo(ll, { animate: false })
  }
  drawMission(t?.mission)
  drawBuoys(t?.vision)
})

// ---- mission overlay: course boundary, UAV geofence, USV/UUV, safe-passage buoys ----
function drawMission(m) {
  if (!missionLayer) return
  missionLayer.clearLayers()
  if (!m || !showMission.value) return
  const c = m.course
  if (c?.boundary?.length > 2)
    L.polygon(c.boundary, { color: '#a46cff', weight: 2, dashArray: '6 6', fill: true, fillOpacity: 0.04 })
      .bindTooltip(`Course ${c.id}`).addTo(missionLayer)
  if (c?.geofence?.length > 2)
    L.polygon(c.geofence, { color: '#3ddc97', weight: 2, dashArray: '2 6', fill: false })
      .bindTooltip('UAV geofence').addTo(missionLayer)
  for (const v of VEHICLES) {
    const hb = m.heartbeats?.[v.key]
    if (v.self || !hb || hb.age > 5 || (!hb.lat && !hb.lon)) continue
    L.marker([hb.lat, hb.lon], { icon: vehIcon(v, hb.heading) })
      .bindTooltip(`${v.label} · ${hb.speed.toFixed(1)} m/s`).addTo(missionLayer)
  }
}
watch(showMission, () => drawMission(robot.telem?.mission))

// ---- vision_geo buoys: one colour per class (/vision_geo/map/<class>) ----
const buoyGroups = ref([])   // [{ name, label, color, count }] for the legend
function drawBuoys(v) {
  if (!buoyLayer) return
  buoyLayer.clearLayers()
  const names = Object.keys(v?.groups || {}).sort()
  const legend = []
  names.forEach((name, i) => {
    const color = buoyColor(name, i)
    const objs = v.groups[name].objects.filter((o) => o.lat || o.lon)
    legend.push({ name, label: buoyLabel(name), color, count: objs.length })
    for (const o of objs) {
      L.circleMarker([o.lat, o.lon], { radius: 8, color: '#0d0f1a', weight: 2, fillColor: color, fillOpacity: 1 })
        .bindTooltip(`${buoyLabel(name)} #${o.id} · ${(o.conf * 100).toFixed(0)}%<br>${o.lat.toFixed(7)}, ${o.lon.toFixed(7)}`)
        .addTo(buoyLayer)
    }
  })
  buoyGroups.value = legend
}

function fitCourse() {
  const c = robot.telem?.mission?.course
  const pts = [...(c?.boundary || []), ...(c?.geofence || [])]
  if (pts.length) { follow.value = false; map.fitBounds(pts, { padding: [40, 40] }) }
}

function fitBuoys() {
  const pts = Object.values(robot.telem?.vision?.groups || {}).flatMap((g) => g.objects.filter((o) => o.lat || o.lon).map((o) => [o.lat, o.lon]))
  if (pts.length) { follow.value = false; map.fitBounds(pts, { padding: [60, 60], maxZoom: 19 }) }
}

function drawCaptures() {
  if (!capLayer) return
  capLayer.clearLayers()
  for (const c of robot.captures) {
    L.marker([c.lat, c.lon], {
      icon: L.divIcon({ className: 'cap-pin', html: `<span>${c.id}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
    }).bindTooltip(`P${c.id}: ${c.lat.toFixed(7)}, ${c.lon.toFixed(7)}`).addTo(capLayer)
  }
}
watch(() => robot.captures.map((c) => c.id).join(), drawCaptures)
function clearTrail() { robot.track.splice(0); trail?.setLatLngs([]) }
</script>

<template>
  <section class="map-wrap">
    <div ref="el" class="map-el" />
    <div class="map-tools">
      <label class="chk"><input type="checkbox" v-model="follow" /> Follow</label>
      <label class="chk"><input type="checkbox" v-model="showMission" /> Mission</label>
      <button :disabled="!robot.mission?.course" @click="fitCourse">Fit course</button>
      <button :disabled="!buoyGroups.length" @click="fitBuoys">Fit buoys</button>
      <button @click="clearTrail">Clear trail</button>
      <button v-if="!camOpen" @click="camOpen = true">Camera</button>
      <button class="primary" :disabled="!robot.telem?.gps" @click="robot.capturePoint()">● Capture</button>
    </div>
    <div v-if="buoyGroups.length" class="legend">
      <span class="legend-title">Buoys</span>
      <span v-for="g in buoyGroups" :key="g.name" class="legend-item">
        <i :style="{ background: g.color }" />{{ g.label }} <b>{{ g.count }}</b>
      </span>
    </div>
    <CameraWindow v-if="camOpen" @close="camOpen = false" />
  </section>
</template>

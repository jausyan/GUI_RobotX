<script setup>
import { onMounted } from 'vue'
import { useRobot } from './stores/robot'
import TopBar from './components/TopBar.vue'
import MapPanel from './components/MapPanel.vue'
import TelemetryPanel from './components/TelemetryPanel.vue'
import SimulationPanel from './components/SimulationPanel.vue'
import ServicesPanel from './components/ServicesPanel.vue'
import LogsPanel from './components/LogsPanel.vue'
import GpsCapture from './components/GpsCapture.vue'
import GcsDialog from './components/GcsDialog.vue'
import CameraDialog from './components/CameraDialog.vue'

const robot = useRobot()
onMounted(() => robot.start())
</script>

<template>
  <div class="layout">
    <TopBar class="top" />
    <MapPanel class="map panel" />
    <aside class="side">
      <TelemetryPanel class="telem panel" />
      <SimulationPanel class="mission-area panel" />
    </aside>
    <div class="bottom">
      <ServicesPanel class="panel" />
      <LogsPanel class="panel" />
      <GpsCapture class="panel" />
    </div>
  </div>
  <GcsDialog v-if="robot.gcsPrompt" />
  <CameraDialog v-if="robot.cameraDialog" />
  <div v-if="robot.toast" class="toast" :class="robot.toast.kind">{{ robot.toast.text }}</div>
</template>

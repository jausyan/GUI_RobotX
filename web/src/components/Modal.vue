<script setup>
defineProps({ title: String, wide: Boolean })
const emit = defineEmits(['close'])
</script>

<template>
  <div class="modal-back" @mousedown.self="emit('close')" @keydown.esc="emit('close')">
    <div class="modal" :class="{ wide }" role="dialog" tabindex="-1">
      <header class="ph">
        <h3>{{ title }}</h3>
        <span class="spacer" />
        <button class="ghost" title="Close" @click="emit('close')">✕</button>
      </header>
      <div class="modal-body"><slot /></div>
      <footer v-if="$slots.footer" class="modal-foot"><slot name="footer" /></footer>
    </div>
  </div>
</template>

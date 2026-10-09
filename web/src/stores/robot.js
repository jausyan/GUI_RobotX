import { defineStore } from 'pinia'
import { API_PORT, CANDIDATE_HOSTS, HEARTBEAT_TIMEOUT_S } from '../config'

const LS_KEY = 'robotx.lastHost'
const safe = (fn, d = null) => { try { return fn() } catch { return d } }
const CAP_KEY = 'robotx.captures'

export const useRobot = defineStore('robot', {
  state: () => ({
    host: null,            // "ip:port" of the connected API
    manualHost: safe(() => localStorage.getItem('robotx.manualHost')) || '',
    status: 'searching',   // searching | connected
    robotName: '',
    telem: null,
    lastTelemAt: 0,
    now: Date.now(),
    services: [],
    track: [],
    orderLog: [],
    captures: safe(() => JSON.parse(localStorage.getItem(CAP_KEY)), []) || [],
  }),
  getters: {
    base: (s) => (s.host ? `http://${s.host}` : null),
    // vehicle heartbeat: /mavros/state must be arriving
    heartbeatAge(s) {
      const a = s.telem?.age?.state
      return a == null ? null : a + (s.now - s.lastTelemAt) / 1000
    },
    mission: (s) => s.telem?.mission || null,
    vision: (s) => s.telem?.vision || null,
    vehicleAlive() {
      return this.heartbeatAge != null && this.heartbeatAge < HEARTBEAT_TIMEOUT_S
    },
  },
  actions: {
    candidates() {
      const last = safe(() => localStorage.getItem(LS_KEY))
      const list = [last, this.manualHost, ...CANDIDATE_HOSTS].filter(Boolean)
      return [...new Set(list)].map((h) => (h.includes(':') ? h : `${h}:${API_PORT}`))
    },
    setManualHost(h) {
      this.manualHost = h.trim()
      safe(() => localStorage.setItem('robotx.manualHost', this.manualHost))
      this.disconnect()
    },
    async probe(host) {
      try {
        const r = await fetch(`http://${host}/health`, { signal: AbortSignal.timeout(1500) })
        const j = await r.json()
        return j.app === 'robotx-api' ? j : null
      } catch { return null }
    },
    start() {
      setInterval(() => (this.now = Date.now()), 500)
      this.discoverLoop()
      setInterval(() => this.host && this.refreshServices(), 1500)
    },
    async discoverLoop() {
      for (;;) {
        if (!this.host) {
          const hosts = this.candidates()
          const res = await Promise.all(hosts.map((h) => this.probe(h)))
          const i = res.findIndex(Boolean)
          if (i >= 0) this.connect(hosts[i], res[i])
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    },
    connect(host, health) {
      this.host = host
      this.robotName = health.name
      this.status = 'connected'
      safe(() => localStorage.setItem(LS_KEY, host))
      this.openTelemetry()
    },
    disconnect() {
      this.ws?.close()
      this.ws = null
      this.host = null
      this.status = 'searching'
      this.telem = null
    },
    openTelemetry() {
      const ws = new WebSocket(`ws://${this.host}/ws/telemetry`)
      this.ws = ws
      ws.onmessage = (e) => {
        this.telem = JSON.parse(e.data)
        this.lastTelemAt = Date.now()
        const g = this.telem.gps
        if (g && g.lat && !isNaN(g.lat)) {
          const last = this.track[this.track.length - 1]
          if (!last || last[0] !== g.lat || last[1] !== g.lon) {
            this.track.push([g.lat, g.lon])
            if (this.track.length > 2000) this.track.shift()
          }
        }
      }
      ws.onclose = () => { if (this.ws === ws) this.disconnect() }
    },
    async sendOrder(order) {
      const entry = { order, t: Date.now(), ok: false, note: '' }
      this.orderLog.unshift(entry)
      this.orderLog.length = Math.min(this.orderLog.length, 8)
      try {
        const r = await fetch(`${this.base}/simulate/${order}`, { method: 'POST' })
        entry.ok = r.ok
        if (!r.ok) entry.note = (await r.json()).detail || r.status
      } catch (e) { entry.note = 'request failed' }
    },
    capturePoint() {
      const g = this.telem?.gps
      if (!g || g.lat == null || isNaN(g.lat)) return false
      const n = (this.captures.at(-1)?.id ?? 0) + 1
      this.captures.push({ id: n, lat: g.lat, lon: g.lon, alt: g.alt, fix: g.fix, t: Date.now() })
      this.saveCaptures()
      return true
    },
    removeCapture(id) {
      this.captures = this.captures.filter((c) => c.id !== id)
      this.saveCaptures()
    },
    clearCaptures() {
      this.captures = []
      this.saveCaptures()
    },
    saveCaptures() {
      safe(() => localStorage.setItem(CAP_KEY, JSON.stringify(this.captures)))
    },
    async refreshServices() {
      try {
        this.services = await (await fetch(`${this.base}/services`)).json()
      } catch { this.disconnect() }
    },
    async serviceAction(name, action) {
      await fetch(`${this.base}/services/${name}/${action}`, { method: 'POST' })
      this.refreshServices()
    },
    async stopAll() {
      await fetch(`${this.base}/services/stop-all`, { method: 'POST' })
      this.refreshServices()
    },
    async startAll() {
      for (const n of ['mavros', 'vision', 'control']) {
        await this.serviceAction(n, 'start')
        await new Promise((r) => setTimeout(r, 2000))
      }
    },
  },
})

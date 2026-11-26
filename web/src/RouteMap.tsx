import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { AirportIndex } from './airports'

// Carte des aéroports choisis (Leaflet, fond Stadia sombre ou clair selon le thème). Chargée à la
// demande : elle n'alourdit pas la page tant qu'on ne l'ouvre pas.
// shortcut: Stadia sert sans clé les pages ouvertes en local (127.0.0.1) ; servie ailleurs, l'app
// devra passer une clé Stadia (?api_key=) dans TILES.

type Props = {
  index: AirportIndex
  origins: string[]
  targets: string[]
  onToggle: (code: string) => void // ajoute ou retire un aéroport visé
  full: boolean // plus de place pour une cible
}

const TILES = (dark: boolean) => `https://tiles.stadiamaps.com/tiles/${dark ? 'alidade_smooth_dark' : 'alidade_smooth'}/{z}/{x}/{y}{r}.png`
const ATTRIBUTION =
  '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

export default function RouteMap({ index, origins, targets, onToggle, full }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const toggle = useRef(onToggle)
  const fitted = useRef(false)
  const [theme, setTheme] = useState(0) // change de thème : les couleurs des points sont relues
  useEffect(() => {
    toggle.current = onToggle
  }, [onToggle])

  // la carte et son fond, une fois ; le fond suit le thème du système
  useEffect(() => {
    if (!box.current) return
    const m = L.map(box.current, { preferCanvas: true, worldCopyJump: true }).setView([52, 15], 4)
    const media = matchMedia('(prefers-color-scheme: dark)')
    let tiles = L.tileLayer(TILES(media.matches), { attribution: ATTRIBUTION, maxZoom: 12 }).addTo(m)
    const onTheme = () => {
      tiles.remove()
      tiles = L.tileLayer(TILES(media.matches), { attribution: ATTRIBUTION, maxZoom: 12 }).addTo(m)
      setTheme((t) => t + 1)
    }
    media.addEventListener('change', onTheme)
    layer.current = L.layerGroup().addTo(m)
    map.current = m
    return () => {
      media.removeEventListener('change', onTheme)
      m.remove()
      map.current = null
    }
  }, [])

  // les aéroports : grands toujours, moyens en zoomant ; choisis par-dessus, reliés aux départs
  useEffect(() => {
    const m = map.current
    const group = layer.current
    if (!m || !group) return
    const draw = () => {
      group.clearLayers()
      const accent = css('--accent')
      const ink = css('--ink')
      const muted = css('--muted')
      const zoom = m.getZoom()
      const picked = new Set([...origins, ...targets])
      for (const { airport: a } of index.entries) {
        if (picked.has(a.iata) || a.size === 'S' || (a.size === 'M' && zoom < 6)) continue
        L.circleMarker([a.lat, a.lon], { radius: 3, weight: 0, fillColor: muted, fillOpacity: 0.55 })
          .bindTooltip(`${a.city} ${a.iata}`, { direction: 'top' })
          .on('click', () => !full && toggle.current(a.iata))
          .addTo(group)
      }
      const at = (code: string) => index.byCode.get(code)
      for (const o of origins.map(at)) {
        for (const t of targets.map(at)) {
          if (o && t) L.polyline([[o.lat, o.lon], [t.lat, t.lon]], { color: accent, weight: 1, opacity: 0.45, interactive: false }).addTo(group)
        }
      }
      for (const [codes, color, clickable] of [[origins, ink, false], [targets, accent, true]] as const) {
        for (const a of codes.map(at)) {
          if (!a) continue
          const dot = L.circleMarker([a.lat, a.lon], { radius: 6, weight: 2, color: css('--paper'), fillColor: color, fillOpacity: 1 })
            .bindTooltip(`${a.city} ${a.iata}`, { direction: 'top', permanent: clickable, className: 'map-label' }) // départs groupés : au survol
            .addTo(group)
          if (clickable) dot.on('click', () => toggle.current(a.iata))
        }
      }
    }
    draw()
    m.on('zoomend', draw)
    return () => {
      m.off('zoomend', draw)
    }
  }, [index, origins, targets, full, theme])

  // cadrer sur la sélection à l'ouverture, puis seulement si un aéroport choisi sort de la vue :
  // un clic sur la carte ne doit pas défaire le zoom en cours
  useEffect(() => {
    const m = map.current
    const points = [...origins, ...targets].flatMap((c) => {
      const a = index.byCode.get(c)
      return a ? [L.latLng(a.lat, a.lon)] : []
    })
    if (!m || points.length < 2) return
    if (!fitted.current || points.some((p) => !m.getBounds().contains(p))) {
      m.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 7 })
      fitted.current = true
    }
  }, [index, origins, targets])

  return (
    <div className="mt-3">
      <div ref={box} className="h-80 overflow-hidden rounded-md border border-line" role="region" aria-label="Carte des aéroports choisis" />
      <p className="mt-1.5 text-xs text-muted">Cliquez un aéroport pour l'ajouter aux cibles ou l'en retirer. Les plus petits apparaissent en zoomant.</p>
    </div>
  )
}

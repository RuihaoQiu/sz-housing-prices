import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { MapContainer, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'

const SZ_CENTER = [22.56, 113.96]
const DEFAULT_ZOOM = 13
const SZ_BOUNDS = [[22.47, 113.88], [22.66, 114.04]]
const LABEL_ZOOM = 16

// ═══════════════════════════════════════════════════════════
// THEME SYSTEM — change THEME_NAME to switch the entire app
// Options: 'mono', 'porcelain', 'palm', 'wire'
// ═══════════════════════════════════════════════════════════
const THEME_NAME = 'palm'

const THEMES = {
  mono: {
    LADDER: [[216,215,209],[198,197,191],[176,175,169],[143,142,136],[106,105,99],[74,73,68],[28,28,26]],
    FALLBACK: '#B0AFA9', ROAD: '#ccc',
    GRID: '#f0f0f5', AXIS: '#8e8e93', MEDIAN: '#1C1C1A', MEDIAN_DASH: '#8e8e93', COUNT: '#c7c7cc',
    ROOM: { 0:'#8F8E88', 1:'#C6C5BF', 2:'#6A6963', 3:'#1C1C1A', 4:'#4A4944', 5:'#B0AFA9' },
  },
  porcelain: {
    LADDER: [[208,227,255],[186,214,235],[154,184,224],[112,150,209],[80,112,190],[51,78,172],[8,31,92]],
    FALLBACK: '#9AB8E0', ROAD: '#BAD6EB',
    GRID: 'rgba(8,31,92,.08)', AXIS: 'rgba(8,31,92,.50)', MEDIAN: '#081F5C', MEDIAN_DASH: '#334EAC', COUNT: '#9AB8E0',
    ROOM: { 0:'#9AB8E0', 1:'#BAD6EB', 2:'#7096D1', 3:'#081F5C', 4:'#334EAC', 5:'#D0E3FF' },
  },
  palm: {
    LADDER: [[200,200,160],[172,173,121],[146,153,96],[119,131,90],[90,112,73],[67,89,59],[43,59,27]],
    FALLBACK: '#ACAD79', ROAD: '#C8C8A0',
    GRID: 'rgba(88,64,46,.08)', AXIS: 'rgba(88,64,46,.50)', MEDIAN: '#43593B', MEDIAN_DASH: '#5A7049', COUNT: '#ACAD79',
    ROOM: { 0:'#C8C8A0', 1:'#ACAD79', 2:'#77835A', 3:'#43593B', 4:'#5A7049', 5:'#F2D17E' },
  },
  wire: {
    LADDER: [[219,218,211],[192,191,183],[170,170,159],[143,142,134],[110,109,102],[74,73,67],[34,33,31]],
    FALLBACK: '#AAAA9F', ROAD: '#C0BFB7',
    GRID: 'rgba(31,30,28,.08)', AXIS: 'rgba(31,30,28,.50)', MEDIAN: '#F5572F', MEDIAN_DASH: '#F5572F', COUNT: '#AAAA9F',
    ROOM: { 0:'#DBDAD3', 1:'#C0BFB7', 2:'#8F8E86', 3:'#22211F', 4:'#6E6D66', 5:'#DBDAD3' },
  },
}

const T = THEMES[THEME_NAME] || THEMES.mono

function getColor(item) {
  let norm
  if (item.type === 'xiaoqu') {
    const val = item.high_rent ?? item.low_rent ?? item.multi_rent
    if (val == null) return T.FALLBACK
    norm = Math.min(Math.max((val - 25) / (150 - 25), 0), 1)
  } else {
    const val = item.one_bed
    if (val == null) return T.FALLBACK
    norm = Math.min(Math.max((val - 450) / (2500 - 450), 0), 1)
  }
  const t = norm * (T.LADDER.length - 1)
  const i = Math.min(Math.floor(t), T.LADDER.length - 2)
  const f = t - i
  const [r1, g1, b1] = T.LADDER[i]
  const [r2, g2, b2] = T.LADDER[i + 1]
  const r = Math.round(r1 + (r2 - r1) * f)
  const g = Math.round(g1 + (g2 - g1) * f)
  const b = Math.round(b1 + (b2 - b1) * f)
  return `rgb(${r},${g},${b})`
}

function getRadius(zoom) {
  const scale = Math.max(0.25, Math.min(2, (zoom - 10) / 5))
  return Math.round(5 * scale * 10) / 10
}

function getXiaoquPrice(item) {
  const vals = [item.high_rent, item.low_rent, item.multi_rent].filter(v => v != null)
  if (!vals.length) return null
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  if (min === max) return `${min} 元/m²`
  return `${min}-${max} 元/m²`
}

function RoadLayer() {
  const map = useMap()
  const layerRef = useRef(null)

  useEffect(() => {
    fetch(import.meta.env.BASE_URL + 'roads.json')
      .then(r => r.json())
      .then(geojson => {
        const layer = L.geoJSON(geojson, {
          style: feature => ({
            color: '#ccc',
            weight: feature.properties.w,
            opacity: 0.8,
          }),
          interactive: false,
          renderer: L.canvas(),
        })
        layer.addTo(map)
        layer.bringToBack()
        layerRef.current = layer
      })

    return () => {
      if (layerRef.current) map.removeLayer(layerRef.current)
    }
  }, [map])

  return null
}

function MapController({ center, filtered, onSelect }) {
  const map = useMap()
  const layerRef = useRef(null)
  const markersRef = useRef([])
  const labelsRef = useRef(null)

  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 100)
  }, [map])

  useEffect(() => {
    if (center) map.setView(center, 15)
  }, [center, map])

  useEffect(() => {
    if (layerRef.current) {
      map.removeLayer(layerRef.current)
    }
    if (labelsRef.current) {
      map.removeLayer(labelsRef.current)
      labelsRef.current = null
    }

    if (!map.getPane('markers')) {
      map.createPane('markers')
      map.getPane('markers').style.zIndex = 450
    }

    const layer = L.layerGroup()
    const renderer = L.canvas({ padding: 0.5, pane: 'markers' })
    const zoom = map.getZoom()
    const markers = []

    filtered.forEach(item => {
      const color = getColor(item)
      const marker = L.circleMarker([item.lat, item.lng], {
        renderer,
        pane: 'markers',
        radius: getRadius(zoom),
        color,
        fillColor: color,
        fillOpacity: 0.7,
        weight: 0,
      })
      const price = item.type === 'xiaoqu'
        ? (getXiaoquPrice(item) || '')
        : (item.one_bed ? item.one_bed + '元/月' : '')
      marker._label = `<div class="label-name">${item.name}</div>${price ? `<div class="label-price">${price}</div>` : ''}`
      marker.on('click', () => onSelect(item))
      layer.addLayer(marker)
      markers.push(marker)
    })

    layer.addTo(map)
    layerRef.current = layer
    markersRef.current = markers

    return () => {
      if (layerRef.current) map.removeLayer(layerRef.current)
    }
  }, [filtered, map, onSelect])

  const updateLabels = useCallback(() => {
    if (labelsRef.current) {
      map.removeLayer(labelsRef.current)
      labelsRef.current = null
    }

    if (map.getZoom() < LABEL_ZOOM) return

    const bounds = map.getBounds()
    const layer = L.layerGroup()

    markersRef.current.forEach(m => {
      if (bounds.contains(m.getLatLng())) {
        const label = L.marker(m.getLatLng(), {
          icon: L.divIcon({
            className: 'marker-label',
            html: m._label,
            iconSize: [80, 30],
            iconAnchor: [40, -8],
          }),
          interactive: false,
        })
        layer.addLayer(label)
      }
    })

    layer.addTo(map)
    labelsRef.current = layer
  }, [map])

  useEffect(() => {
    const onZoom = () => {
      const zoom = map.getZoom()
      markersRef.current.forEach(m => {
        m.setRadius(getRadius(zoom))
      })
      updateLabels()
    }
    map.on('zoomend', onZoom)
    map.on('moveend', updateLabels)
    return () => {
      map.off('zoomend', onZoom)
      map.off('moveend', updateLabels)
      if (labelsRef.current) map.removeLayer(labelsRef.current)
    }
  }, [map, updateLabels])

  return null
}

function SearchBar({ data, onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const inputRef = useRef()

  useEffect(() => {
    if (query.length < 1) {
      setResults([])
      return
    }
    const q = query.toLowerCase()
    const matches = data
      .filter(d => d.name.toLowerCase().includes(q) || d.address.toLowerCase().includes(q))
      .slice(0, 8)
    setResults(matches)
  }, [query, data])

  const handleSelect = (item) => {
    setQuery(item.name)
    setResults([])
    setOpen(false)
    onSelect(item)
    inputRef.current?.blur()
  }

  return (
    <div className="search-bar">
      <input
        ref={inputRef}
        type="text"
        placeholder="搜索小区或城中村名称..."
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && results.length > 0 && (
        <ul className="search-results">
          {results.map((r, i) => (
            <li key={i} onMouseDown={() => handleSelect(r)}>
              <span className="result-name">{r.name}</span>
              <span className="result-meta">
                {r.district} · {r.street}
                {r.type === 'chengzhongcun' ? ' · 城中村' : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const ROOM_LABELS = { 0: '单间', 1: '一房', 2: '两房', 3: '三房', 4: '四房', 5: '五房+' }
const ROOM_COLORS = T.ROOM

function normalizeRooms(rooms) {
  if (rooms == null) return null
  if (rooms >= 5) return 5
  return rooms
}

function formatPrice(val) {
  if (val >= 10000) return (val / 10000).toFixed(1) + 'w'
  return Math.round(val).toLocaleString()
}

function drawChart(canvas, data, mode) {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, w, h)

  // Filter to dots that have the needed values
  const dots = data.filter(r => {
    if (!r.price || !r.area) return false
    return mode === 'sqm' ? r.price_sqm : true
  })
  if (!dots.length) return

  const pad = { top: 12, right: 16, bottom: 28, left: 44 }
  const plotW = w - pad.left - pad.right
  const plotH = h - pad.top - pad.bottom

  const areas = dots.map(r => r.area)
  const values = dots.map(r => mode === 'sqm' ? r.price_sqm : r.price)
  const minA = Math.min(...areas)
  const maxA = Math.max(...areas)
  const minV = Math.min(...values)
  const maxV = Math.max(...values)
  const rangeA = maxA - minA || 1
  const rangeV = maxV - minV || 1
  const sorted = [...values].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]

  // Grid lines (horizontal)
  ctx.fillStyle = T.AXIS
  ctx.font = '10px -apple-system, sans-serif'
  ctx.textAlign = 'right'
  const yTicks = 4
  for (let i = 0; i <= yTicks; i++) {
    const val = minV + (rangeV * i / yTicks)
    const y = pad.top + plotH - (plotH * i / yTicks)
    ctx.fillText(formatPrice(val), pad.left - 6, y + 3)
    ctx.strokeStyle = T.GRID
    ctx.lineWidth = 0.5
    ctx.beginPath()
    ctx.moveTo(pad.left, y)
    ctx.lineTo(w - pad.right, y)
    ctx.stroke()
  }

  // X axis labels
  ctx.textAlign = 'center'
  ctx.fillStyle = T.AXIS
  const xTicks = 3
  for (let i = 0; i <= xTicks; i++) {
    const val = minA + (rangeA * i / xTicks)
    const x = pad.left + (plotW * i / xTicks)
    ctx.fillText(Math.round(val) + 'm²', x, h - 6)
  }

  // Median line (horizontal)
  const medianY = pad.top + plotH - ((median - minV) / rangeV) * plotH
  ctx.strokeStyle = T.MEDIAN_DASH
  ctx.lineWidth = 1
  ctx.setLineDash([4, 3])
  ctx.beginPath()
  ctx.moveTo(pad.left, medianY)
  ctx.lineTo(w - pad.right, medianY)
  ctx.stroke()
  ctx.setLineDash([])

  // Median label
  ctx.fillStyle = T.MEDIAN
  ctx.font = '10px -apple-system, sans-serif'
  ctx.textAlign = 'right'
  const medianLabel = mode === 'sqm' ? `${Math.round(median)} 元/m²` : `${formatPrice(median)} 元`
  ctx.fillText('中位 ' + medianLabel, w - pad.right, medianY - 5)

  // Scatter dots
  dots.forEach(r => {
    const val = mode === 'sqm' ? r.price_sqm : r.price
    const x = pad.left + ((r.area - minA) / rangeA) * plotW
    const y = pad.top + plotH - ((val - minV) / rangeV) * plotH
    const norm = normalizeRooms(r.rooms)
    ctx.fillStyle = norm != null ? (ROOM_COLORS[norm] || T.FALLBACK) : T.FALLBACK
    ctx.globalAlpha = 0.65
    ctx.beginPath()
    ctx.arc(x, y, 4, 0, Math.PI * 2)
    ctx.fill()
    ctx.globalAlpha = 1
  })

  // Count label (top-right corner)
  ctx.fillStyle = T.COUNT
  ctx.font = '10px -apple-system, sans-serif'
  ctx.textAlign = 'right'
  ctx.fillText(`${dots.length} 套`, w - pad.right, pad.top + 10)
}

function PriceChart({ rentals }) {
  const canvasRef = useRef(null)
  const [filter, setFilter] = useState('all')
  const [mode, setMode] = useState('total')

  const roomTypes = useMemo(() => {
    const types = new Set()
    rentals.forEach(r => {
      const norm = normalizeRooms(r.rooms)
      if (norm != null) types.add(norm)
    })
    return [...types].sort((a, b) => a - b)
  }, [rentals])

  const filtered = useMemo(() => {
    if (filter === 'all') return rentals
    return rentals.filter(r => normalizeRooms(r.rooms) === filter)
  }, [rentals, filter])

  useEffect(() => {
    drawChart(canvasRef.current, filtered, mode)
  }, [filtered, mode])

  return (
    <div className="price-chart">
      <div className="chart-controls">
        <div className="chart-filters">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>全部</button>
          {roomTypes.map(t => (
            <button
              key={t}
              className={filter === t ? 'active' : ''}
              onClick={() => setFilter(t)}
              style={{ '--dot-color': ROOM_COLORS[t] }}
            >
              <span className="filter-dot" />{ROOM_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="chart-mode">
          <button className={mode === 'total' ? 'active' : ''} onClick={() => setMode('total')}>总价</button>
          <button className={mode === 'sqm' ? 'active' : ''} onClick={() => setMode('sqm')}>单价</button>
        </div>
      </div>
      <canvas ref={canvasRef} className="chart-canvas" />
    </div>
  )
}

function InfoGrid({ community }) {
  const items = [
    { label: '商圈', value: community.所属商圈 },
    { label: '建筑', value: community.建筑类型?.replace(/\|/g, ' · ') },
    { label: '竣工', value: community.竣工时间?.replace(/年、/g, ' / ')?.replace(/年$/, '') },
    { label: '户数', value: community.总户数 },
    { label: '物业费', value: community.物业费 },
    { label: '绿化率', value: community.绿化率 },
  ].filter(i => i.value)

  return (
    <div className="info-grid">
      {items.map(({ label, value }) => (
        <div key={label} className="info-item">
          <span className="info-label">{label}</span>
          <span className="info-value">{value}</span>
        </div>
      ))}
    </div>
  )
}

function calcMarketStats(rentals) {
  const prices = rentals.map(r => r.price_sqm).filter(Boolean)
  if (prices.length < 3) return null
  const sorted = [...prices].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]
  const mean = prices.reduce((s, v) => s + v, 0) / prices.length
  const std = Math.sqrt(prices.reduce((s, v) => s + (v - mean) ** 2, 0) / prices.length)
  return {
    median: Math.round(median),
    low: Math.max(Math.round(median - 3 * std), Math.round(sorted[0])),
    high: Math.round(median + 3 * std),
    count: prices.length,
  }
}

function PriceCompare({ govItem, market }) {
  // Determine the visual range — span from lowest to highest across both
  const govVals = [govItem.high_rent, govItem.low_rent, govItem.multi_rent].filter(v => v != null)
  const govMin = govVals.length ? Math.min(...govVals) : null
  const govMax = govVals.length ? Math.max(...govVals) : null

  const allVals = [...govVals]
  if (market) { allVals.push(market.low, market.high, market.median) }
  if (!allVals.length) return null

  const lo = Math.min(...allVals) * 0.85
  const hi = Math.max(...allVals) * 1.1
  const range = hi - lo || 1
  const pct = v => ((v - lo) / range) * 100

  return (
    <div className="price-compare">
      {govMin != null && (
        <div className="compare-row">
          <span className="compare-label">政府参考</span>
          <div className="compare-bar-wrap">
            <div className="compare-range gov-range"
              style={{ left: pct(govMin) + '%', width: Math.max(pct(govMax) - pct(govMin), 0.5) + '%' }}
            />
            <span className="compare-val" style={{ left: pct(govMax) + '%' }}>
              {govMin === govMax ? `${govMin}` : `${govMin}–${govMax}`}
            </span>
          </div>
        </div>
      )}
      {market && (
        <div className="compare-row">
          <span className="compare-label">市场价</span>
          <div className="compare-bar-wrap">
            <div className="compare-range market-range"
              style={{ left: pct(market.low) + '%', width: Math.max(pct(market.high) - pct(market.low), 0.5) + '%' }}
            />
            <div className="compare-median"
              style={{ left: pct(market.median) + '%' }}
            />
            <span className="compare-val" style={{ left: pct(market.high) + '%' }}>
              {market.low}–{market.median}–{market.high}
            </span>
          </div>
        </div>
      )}
      <div className="compare-axis">
        <span>{Math.round(lo)}</span>
        <span>元/m²/月</span>
        <span>{Math.round(hi)}</span>
      </div>
    </div>
  )
}

function CommunityCard({ item, community, onClose }) {
  if (!item) return null

  const hasRentals = community?.rentals?.length > 0
  const market = hasRentals ? calcMarketStats(community.rentals) : null

  return (
    <div className="price-card community-card">
      <button className="close-btn" onClick={onClose}>×</button>
      <h3>{item.name}</h3>
      <p className="card-meta">{item.district} · {item.street}</p>

      {item.type === 'xiaoqu' && (
        <PriceCompare govItem={item} market={market} />
      )}

      {community && <InfoGrid community={community} />}

      {hasRentals && (
        <>
          <div className="section-title">在租价格分布</div>
          <PriceChart rentals={community.rentals} />
        </>
      )}

      {!community && item.type === 'chengzhongcun' && (
        <div className="card-prices">
          {item.single_room != null && (
            <div className="price-row">
              <span className="price-label">单间</span>
              <span className="price-value">{item.single_room} 元/月</span>
            </div>
          )}
          {item.one_bed != null && (
            <div className="price-row">
              <span className="price-label">一房</span>
              <span className="price-value">{item.one_bed} 元/月</span>
            </div>
          )}
          {item.two_bed != null && (
            <div className="price-row">
              <span className="price-label">两房</span>
              <span className="price-value">{item.two_bed} 元/月</span>
            </div>
          )}
          {item.three_plus != null && (
            <div className="price-row">
              <span className="price-label">三房+</span>
              <span className="price-value">{item.three_plus} 元/月</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Legend({ showType }) {
  return (
    <div className="legend">
      <div className="legend-row">
        <div className="legend-bar" style={{background:`linear-gradient(to right, ${T.LADDER.map(c=>`rgb(${c})`).join(', ')})`}} />
        <div className="legend-range">
          <span>{showType === 'xiaoqu' ? '25 元/m²/月' : '450 元/月'}</span>
          <span>{showType === 'xiaoqu' ? '150+' : '2500+'}</span>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [data, setData] = useState([])
  const [communities, setCommunities] = useState({})
  const [selected, setSelected] = useState(null)
  const [flyTarget, setFlyTarget] = useState(null)
  const [showType, setShowType] = useState('xiaoqu')

  useEffect(() => {
    fetch(import.meta.env.BASE_URL + 'data.json')
      .then(r => r.json())
      .then(setData)
    fetch(import.meta.env.BASE_URL + 'communities.json')
      .then(r => r.json())
      .then(list => {
        const byName = {}
        list.forEach(c => { byName[c.name] = c })
        setCommunities(byName)
      })
  }, [])

  const filtered = useMemo(() => {
    return data.filter(d => d.type === showType)
  }, [data, showType])

  const handleSelect = useCallback((item) => {
    if (item.type === 'xiaoqu') {
      window.location.href = import.meta.env.BASE_URL + 'xiaoqu-detail.html?name=' + encodeURIComponent(item.name)
      return
    }
    setSelected(item)
    setFlyTarget([item.lat, item.lng])
  }, [])

  return (
    <div className="app">
      <div className="top-bar">
        <h1>南山租金参考</h1>
        <SearchBar data={data} onSelect={handleSelect} />
      </div>

      <div className="filter-bar">
        <div className="type-toggle">
          <button className={showType === 'xiaoqu' ? 'active' : ''} onClick={() => setShowType('xiaoqu')}>小区</button>
          <button className={showType === 'chengzhongcun' ? 'active' : ''} onClick={() => setShowType('chengzhongcun')}>城中村</button>
        </div>
      </div>

      <MapContainer
        center={SZ_CENTER}
        zoom={DEFAULT_ZOOM}
        minZoom={10}
        maxBounds={SZ_BOUNDS}
        maxBoundsViscosity={1.0}
        className="map"
      >
        <RoadLayer />
        <MapController
          center={flyTarget}
          filtered={filtered}
          onSelect={handleSelect}
        />
      </MapContainer>

      <Legend showType={showType} />

      <CommunityCard
        item={selected}
        community={selected ? communities[selected.name] : null}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}

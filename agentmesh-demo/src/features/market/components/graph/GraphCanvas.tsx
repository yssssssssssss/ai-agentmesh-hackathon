import { useEffect, useMemo, useRef, useState } from 'react'
import { Focus, MinusCircle, PlusCircle } from 'lucide-react'
import type { MarketMeGraph } from '../../types'
import { useForceSimulation, type SimLink, type SimNode } from './useForceSimulation'

interface GraphCanvasProps {
  graph: MarketMeGraph
  meId: string
}

const ROLE_COLOR: Record<SimNode['tie_role'], string> = {
  me: '#2dd4a8', // mint-400
  incoming: '#ffab5e', // remind
  outgoing: '#5b9dff', // knowledge
  peer: '#7d8598',
}

const DIRECTION_COLOR: Record<SimLink['direction'], string> = {
  incoming: '#ffab5e',
  outgoing: '#5b9dff',
  peer: 'rgba(169, 139, 255, 0.55)',
}

interface Viewport {
  scale: number
  tx: number
  ty: number
}

interface Star {
  x: number
  y: number
  radius: number
  alpha: number
}

function generateStars(width: number, height: number, count: number): Star[] {
  const stars: Star[] = []
  for (let i = 0; i < count; i++) {
    stars.push({
      x: (i * 137.5 + 41) % width,
      y: (i * 73.3 + 17) % height,
      radius: ((i * 3) % 5) / 4 + 0.4,
      alpha: 0.08 + (((i * 19) % 30) / 100),
    })
  }
  return stars
}

export function GraphCanvas({ graph, meId }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 800, height: 460 })
  const [viewport, setViewport] = useState<Viewport>({ scale: 1, tx: 0, ty: 0 })
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [dragNode, setDragNode] = useState<string | null>(null)
  const panRef = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width && height) setSize({ width, height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
    const handler = (event: WheelEvent) => {
      if (!event.ctrlKey) return
      event.preventDefault()
      setViewport((prev) => {
        const factor = event.deltaY < 0 ? 1.08 : 1 / 1.08
        return { ...prev, scale: Math.min(2.5, Math.max(0.4, prev.scale * factor)) }
      })
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  const { nodes: simNodes, links, tick, reheat } = useForceSimulation({
    nodes: graph.nodes,
    edges: graph.edges,
    meId,
    width: size.width,
    height: size.height,
  })
  // Keep tick referenced so the compiler retains it — its update is what re-renders us.
  void tick

  const stars = useMemo(() => generateStars(size.width, size.height, 140), [size.width, size.height])

  const nodeById = useMemo(() => {
    const map = new Map<string, SimNode>()
    for (const node of simNodes) map.set(node.id, node)
    return map
  }, [simNodes])

  const clampScale = (next: number) => Math.min(2.5, Math.max(0.4, next))

  const handleBackgroundDown = (event: React.MouseEvent) => {
    panRef.current = { x: event.clientX - viewport.tx, y: event.clientY - viewport.ty }
  }
  const handleMove = (event: React.MouseEvent) => {
    if (dragNode) {
      const node = nodeById.get(dragNode)
      if (!node) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const localX = (event.clientX - rect.left - viewport.tx) / viewport.scale
      const localY = (event.clientY - rect.top - viewport.ty) / viewport.scale
      node.fx = localX
      node.fy = localY
      reheat()
    } else if (panRef.current) {
      setViewport({
        scale: viewport.scale,
        tx: event.clientX - panRef.current.x,
        ty: event.clientY - panRef.current.y,
      })
    }
  }
  const handleUp = () => {
    if (dragNode) {
      const node = nodeById.get(dragNode)
      if (node) {
        node.fx = null
        node.fy = null
      }
    }
    setDragNode(null)
    panRef.current = null
  }

  const reset = () => setViewport({ scale: 1, tx: 0, ty: 0 })

  const linkStyle = (link: SimLink) => {
    const source = typeof link.source === 'string' ? nodeById.get(link.source) : link.source
    const target = typeof link.target === 'string' ? nodeById.get(link.target) : link.target
    if (!source || !target) return null
    const dim = hoverId && hoverId !== source.id && hoverId !== target.id ? 0.08 : 0.55
    return { source, target, color: DIRECTION_COLOR[link.direction], opacity: dim }
  }

  const isDim = (nodeId: string) => hoverId != null && hoverId !== nodeId
  const anchorForNode = (node: SimNode) => ({ x: node.x ?? size.width / 2, y: node.y ?? size.height / 2 })

  const hoveredNode = hoverId ? nodeById.get(hoverId) : null

  return (
    <section
      aria-label="协作关系图"
      className="relative overflow-hidden rounded-[14px] border border-white/[0.06] bg-canvas"
    >
      <div
        ref={containerRef}
        className="relative h-[clamp(440px,66vh,720px)] w-full cursor-grab active:cursor-grabbing"
        onMouseDown={handleBackgroundDown}
        onMouseMove={handleMove}
        onMouseUp={handleUp}
        onMouseLeave={handleUp}
      >
        <svg
          role="img"
          aria-label="知识图谱"
          className="absolute inset-0 h-full w-full"
          viewBox={`0 0 ${size.width} ${size.height}`}
          preserveAspectRatio="xMidYMid slice"
        >
          <defs>
            <radialGradient id="market-halo" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.55" />
              <stop offset="60%" stopColor="currentColor" stopOpacity="0.12" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Starfield background */}
          <g aria-hidden>
            {stars.map((star, index) => (
              <circle
                key={`star-${index}`}
                cx={star.x}
                cy={star.y}
                r={star.radius}
                fill="#c5cbd6"
                opacity={star.alpha}
              />
            ))}
          </g>

          <g transform={`translate(${viewport.tx} ${viewport.ty}) scale(${viewport.scale})`}>
            {links.map((link, index) => {
              const styled = linkStyle(link)
              if (!styled) return null
              const { source, target, color, opacity } = styled
              const sx = source.x ?? 0
              const sy = source.y ?? 0
              const tx = target.x ?? 0
              const ty = target.y ?? 0
              const mx = (sx + tx) / 2
              const my = (sy + ty) / 2 - 20
              return (
                <path
                  key={`edge-${index}`}
                  d={`M ${sx} ${sy} Q ${mx} ${my} ${tx} ${ty}`}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.1}
                  strokeOpacity={opacity}
                />
              )
            })}

            {simNodes.map((node) => {
              const { x, y } = anchorForNode(node)
              const color = ROLE_COLOR[node.tie_role]
              const dim = isDim(node.id) ? 0.18 : 1
              const radius = node.tie_role === 'me' ? node.size + 4 : node.size
              return (
                <g
                  key={node.id}
                  transform={`translate(${x} ${y})`}
                  opacity={dim}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoverId(node.id)}
                  onMouseLeave={() => setHoverId((current) => (current === node.id ? null : current))}
                  onMouseDown={(event) => {
                    event.stopPropagation()
                    setDragNode(node.id)
                  }}
                >
                  <circle r={radius * 1.9} fill="url(#market-halo)" style={{ color }} />
                  <circle
                    r={radius}
                    fill={color}
                    stroke={node.tie_role === 'me' ? '#ffffff' : 'rgba(255,255,255,0.18)'}
                    strokeWidth={node.tie_role === 'me' ? 1.4 : 0.8}
                  />
                  <text
                    y={radius + 14}
                    textAnchor="middle"
                    fontSize={11}
                    fill="#e2e6ee"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {node.name}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {hoveredNode ? (
          <div
            role="tooltip"
            className="pointer-events-none absolute left-4 top-4 max-w-[260px] rounded-[10px] border border-white/[0.14] bg-surface-2/90 p-3 text-xs backdrop-blur"
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: ROLE_COLOR[hoveredNode.tie_role] }}
              />
              <span className="text-sm font-semibold text-white">{hoveredNode.name}</span>
              <span className="text-[10px] text-slate-500">{hoveredNode.group || '—'}</span>
            </div>
            {hoveredNode.offer ? (
              <p className="mt-2 text-slate-300">
                <span className="text-slate-500">可提供：</span>
                {hoveredNode.offer}
              </p>
            ) : null}
            {hoveredNode.need ? (
              <p className="mt-1 text-slate-300">
                <span className="text-slate-500">需要：</span>
                {hoveredNode.need}
              </p>
            ) : null}
            <p className="mt-2 text-slate-500">协作连结 {hoveredNode.ties}</p>
          </div>
        ) : null}

        {/* Legend */}
        <div className="pointer-events-none absolute bottom-3 left-4 flex items-center gap-3 rounded-[10px] border border-white/[0.06] bg-surface-1/80 px-3 py-2 text-[11px] text-slate-400 backdrop-blur">
          <LegendDot color={ROLE_COLOR.me} label="我" />
          <LegendDot color={ROLE_COLOR.incoming} label="帮过我" />
          <LegendDot color={ROLE_COLOR.outgoing} label="我帮过" />
          <LegendDot color={ROLE_COLOR.peer} label="同市场" />
        </div>

        {/* Toolbar */}
        <div className="absolute right-3 top-3 flex items-center gap-1 rounded-[10px] border border-white/[0.06] bg-surface-1/85 p-1 text-slate-300 backdrop-blur">
          <button
            type="button"
            title="缩小"
            className="rounded-md p-1.5 hover:bg-white/[0.06]"
            onClick={() => setViewport((prev) => ({ ...prev, scale: clampScale(prev.scale / 1.15) }))}
          >
            <MinusCircle className="h-4 w-4" />
          </button>
          <span className="min-w-[36px] text-center text-[11px] tabular-nums text-slate-400">
            {Math.round(viewport.scale * 100)}%
          </span>
          <button
            type="button"
            title="放大"
            className="rounded-md p-1.5 hover:bg-white/[0.06]"
            onClick={() => setViewport((prev) => ({ ...prev, scale: clampScale(prev.scale * 1.15) }))}
          >
            <PlusCircle className="h-4 w-4" />
          </button>
          <span aria-hidden className="mx-1 h-4 w-px bg-white/[0.08]" />
          <button
            type="button"
            title="复位"
            className="rounded-md p-1.5 hover:bg-white/[0.06]"
            onClick={reset}
          >
            <Focus className="h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  )
}

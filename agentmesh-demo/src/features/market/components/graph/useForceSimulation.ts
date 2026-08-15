import { useEffect, useMemo, useRef, useState } from 'react'
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import type { MarketMeGraphEdge, MarketMeGraphNode } from '../../types'

export interface SimNode extends SimulationNodeDatum {
  id: string
  name: string
  group: string
  size: number
  tie_role: MarketMeGraphNode['tie_role']
  offer: string
  need: string
  ties: number
}

export interface SimLink extends SimulationLinkDatum<SimNode> {
  source: string | SimNode
  target: string | SimNode
  direction: MarketMeGraphEdge['direction']
}

interface UseForceSimulationParams {
  nodes: MarketMeGraphNode[]
  edges: MarketMeGraphEdge[]
  meId: string
  width: number
  height: number
}

export interface UseForceSimulationResult {
  nodes: SimNode[]
  links: SimLink[]
  tick: number
  reheat: () => void
  simulation: Simulation<SimNode, SimLink> | null
}

/**
 * Force-directed layout for the personal market graph.
 * The "me" node is softly anchored toward the center; peers drift under
 * classic FR-style forces so ties visually cluster around ego.
 */
export function useForceSimulation({
  nodes,
  edges,
  meId,
  width,
  height,
}: UseForceSimulationParams): UseForceSimulationResult {
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const [tick, setTick] = useState(0)

  const { simNodes, simLinks } = useMemo(() => {
    const mapped: SimNode[] = nodes.map((node) => ({
      id: node.id,
      name: node.name,
      group: node.group,
      size: node.size,
      tie_role: node.tie_role,
      offer: node.offer,
      need: node.need,
      ties: node.ties,
    }))
    const idToNode = new Map(mapped.map((n) => [n.id, n]))
    const links: SimLink[] = []
    for (const edge of edges) {
      const source = idToNode.get(edge.from)
      const target = idToNode.get(edge.to)
      if (!source || !target) continue
      links.push({ source, target, direction: edge.direction })
    }
    return { simNodes: mapped, simLinks: links }
  }, [nodes, edges])

  useEffect(() => {
    if (simNodes.length === 0 || width === 0 || height === 0) {
      simRef.current?.stop()
      simRef.current = null
      return
    }
    const reducedMotion =
      typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const simulation = forceSimulation<SimNode>(simNodes)
      .force('charge', forceManyBody<SimNode>().strength(-260))
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((n) => n.id)
          .distance(120)
          .strength(0.35),
      )
      .force('center', forceCenter(width / 2, height / 2))
      .force('anchor-me-x', forceX<SimNode>(width / 2).strength((n) => (n.id === meId ? 0.55 : 0.02)))
      .force('anchor-me-y', forceY<SimNode>(height / 2).strength((n) => (n.id === meId ? 0.55 : 0.02)))
      .alphaDecay(0.03)
      .on('tick', () => setTick((t) => (t + 1) % 1_000_000))

    if (reducedMotion) {
      // Run the layout synchronously and freeze — no animated drift.
      for (let i = 0; i < 200; i++) simulation.tick()
      simulation.stop()
      setTick((t) => t + 1)
    }

    simRef.current = simulation
    return () => {
      simulation.stop()
      simRef.current = null
    }
  }, [simNodes, simLinks, meId, width, height])

  const reheat = () => {
    simRef.current?.alpha(0.4).restart()
  }

  return { nodes: simNodes, links: simLinks, tick, reheat, simulation: simRef.current }
}

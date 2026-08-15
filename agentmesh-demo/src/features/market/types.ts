import type { components } from '../../api/generated/schema'

export type MarketMeView = components['schemas']['MarketMeView']
export type MarketMePresence = components['schemas']['MarketMePresence']
export type MarketMeGraph = components['schemas']['MarketMeGraph']
export type MarketMeGraphNode = components['schemas']['MarketMeGraphNode']
export type MarketMeGraphEdge = components['schemas']['MarketMeGraphEdge']
export type MarketMeTimelineItem = components['schemas']['MarketMeTimelineItem']
export type MarketMeUser = components['schemas']['MarketMeUser']
export type MarketMeWorkerState = components['schemas']['MarketMeWorkerState']

export type TieRole = MarketMeGraphNode['tie_role']
export type Direction = MarketMeGraphEdge['direction']
export type TimelineCategory = MarketMeTimelineItem['category']
export type TimelineStatus = MarketMeTimelineItem['status']

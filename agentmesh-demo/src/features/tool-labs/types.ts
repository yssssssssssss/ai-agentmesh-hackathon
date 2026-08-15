export type WorkspaceToolId = 'aesthetic-quant' | 'experience-model'

export type AestheticProfile = 'balanced' | 'readability_first' | 'marketing_impact'
export type AestheticDepth = 'lite' | 'standard' | 'deep'

export interface RoiInput {
  id: string
  label: string
  x: number
  y: number
  width: number
  height: number
}

export interface AestheticMetric {
  label: string
  value: number
}

export interface AestheticRoiResult {
  label: string
  score: number
  brightness: number
  saturation: number
  attentionRank: number
}

export interface AestheticMockResult {
  overallScore: number
  confidence: { level: string; score: number; note: string }
  summary: string
  metrics: AestheticMetric[]
  imageStats: Array<{ label: string; value: string | number }>
  roiResults: AestheticRoiResult[]
  pairResult: Array<{ label: string; value: string | number }>
  attention: { peak: number; balance: number; distraction: number; heatmap: number[] }
  findings: string[]
  recommendations: string[]
  boundaryNotes: string[]
}

export interface ExperienceModelOption {
  id: string
  label: string
  resultLabel: string
  description: string
  bestFor: string
}

export interface ExperienceRecommendation {
  modelId: string
  score: number
  reasons: string[]
}

export interface ExperienceMockResult {
  summary: string
  frameworkSummary: string
  defaultModelIds: string[]
  reasons: Record<string, string[]>
  warnings: string[]
  boundaryNotes: string[]
}

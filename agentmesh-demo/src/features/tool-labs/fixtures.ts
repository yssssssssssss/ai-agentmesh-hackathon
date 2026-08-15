import type { AestheticMockResult, ExperienceMockResult, ExperienceModelOption, RoiInput } from './types'

export const DEFAULT_ROIS: RoiInput[] = [
  { id: 'hero', label: '主视觉区域', x: 0.12, y: 0.12, width: 0.52, height: 0.38 },
  { id: 'action', label: '行动区域', x: 0.58, y: 0.62, width: 0.3, height: 0.22 },
]

export const AESTHETIC_MOCK_RESULT: AestheticMockResult = {
  overallScore: 82,
  confidence: { level: '中高', score: 0.86, note: '固定样例用于验证信息层级，不代表真实图片置信度。' },
  summary: '画面具有清晰的视觉中心和稳定的暖色调，行动区域仍可通过对比度与留白进一步聚焦。',
  metrics: [
    { label: '整体色彩', value: 86 },
    { label: '色温', value: 79 },
    { label: '色彩丰富度', value: 81 },
    { label: '和谐度', value: 84 },
    { label: '注意力聚焦', value: 78 },
  ],
  imageStats: [
    { label: '主色', value: '#E99A5E' },
    { label: '亮度', value: 0.68 },
    { label: '饱和度', value: 0.57 },
    { label: '边缘密度', value: 0.31 },
    { label: '纹理复杂度', value: 0.42 },
    { label: '色彩复杂度', value: 0.48 },
  ],
  roiResults: [
    { label: '主视觉区域', score: 88, brightness: 0.71, saturation: 0.62, attentionRank: 1 },
    { label: '行动区域', score: 76, brightness: 0.59, saturation: 0.49, attentionRank: 2 },
  ],
  pairResult: [
    { label: '前后景对比度', value: '5.2:1' },
    { label: '亮度差', value: 0.34 },
    { label: '饱和度差', value: 0.18 },
    { label: '配色关系', value: '暖色邻近调和' },
  ],
  attention: {
    peak: 0.89,
    balance: 0.77,
    distraction: 0.24,
    heatmap: [
      0.08, 0.12, 0.18, 0.26, 0.32, 0.21, 0.14, 0.09,
      0.11, 0.2, 0.36, 0.58, 0.7, 0.42, 0.2, 0.12,
      0.14, 0.27, 0.54, 0.83, 0.92, 0.61, 0.28, 0.14,
      0.12, 0.25, 0.49, 0.72, 0.78, 0.55, 0.3, 0.16,
      0.08, 0.16, 0.28, 0.39, 0.45, 0.47, 0.5, 0.31,
      0.06, 0.12, 0.2, 0.29, 0.41, 0.62, 0.76, 0.42,
      0.05, 0.09, 0.16, 0.24, 0.35, 0.55, 0.68, 0.37,
      0.04, 0.07, 0.11, 0.16, 0.22, 0.31, 0.38, 0.21,
    ],
  },
  findings: ['主视觉形成第一注意力峰值。', '行动区域可见，但与相邻内容的层级差距有限。'],
  recommendations: ['提高行动区域文字与背景的明度差。', '减少主视觉右下区域的装饰元素，强化单一行动焦点。'],
  boundaryNotes: ['演示数据来自固定 fixture。', '注意力示意不等同于真实眼动实验或用户行为数据。'],
}

export const EXPERIENCE_MODELS: ExperienceModelOption[] = [
  { id: 'heart', label: 'HEART', resultLabel: 'HEART 模型', description: '衡量满意度、参与、采纳、留存和任务成功。', bestFor: '版本体验指标与参与度评估' },
  { id: 'gsm', label: 'GSM', resultLabel: 'GSM 模型', description: '从目标、信号和指标建立衡量体系。', bestFor: '指标设计与实验评估' },
  { id: 'jtbd', label: 'JTBD', resultLabel: 'JTBD 模型', description: '围绕用户要完成的任务理解动机。', bestFor: '需求探索与机会识别' },
  { id: 'kano', label: 'Kano', resultLabel: 'Kano 模型', description: '区分基本型、期望型与兴奋型需求。', bestFor: '功能取舍与需求排序' },
  { id: 'sus', label: 'SUS', resultLabel: 'SUS 模型', description: '快速评估系统整体可用性。', bestFor: '可用性基线与版本对比' },
  { id: 'nps', label: 'NPS', resultLabel: 'NPS 模型', description: '以推荐意愿观察忠诚与口碑。', bestFor: '品牌口碑与忠诚度' },
  { id: 'tam', label: 'TAM', resultLabel: 'TAM 模型', description: '分析感知有用性、易用性和技术接受度。', bestFor: 'AI 功能与新技术采纳' },
  { id: 'cognitive_load', label: '认知负荷', resultLabel: '认知负荷理论', description: '观察复杂度、学习成本和认知压力。', bestFor: '复杂页面与信息架构' },
  { id: 'aesthetic_usability', label: '美学可用性', resultLabel: '美学可用性效应', description: '解释视觉观感对易用性感知的影响。', bestFor: '视觉设计与品牌感知' },
  { id: 'fogg', label: 'Fogg', resultLabel: 'Fogg 行为模型', description: '从动机、能力与触发解释行为。', bestFor: '转化优化与行为引导' },
]

export const EXPERIENCE_MOCK_RESULT: ExperienceMockResult = {
  summary: '建议组合使用 HEART 衡量体验结果、Kano 判断需求优先级，并用 GSM 把研究目标落到可追踪指标。',
  frameworkSummary: '先用 HEART 定义体验结果，再以 Kano 分层需求，最后通过 GSM 建立目标、信号和指标的闭环。',
  defaultModelIds: ['heart', 'gsm', 'kano'],
  reasons: {
    heart: ['研究问题同时涉及参与和任务成功。', '适合形成版本前后的体验指标基线。'],
    gsm: ['需要把“提升体验”拆成可观察信号。', '便于后续定义实验和追踪指标。'],
    jtbd: ['适合补充用户在首页场景中的真实任务。'],
    kano: ['适合判断首页改版能力的优先级。', '能区分必须满足和增益体验。'],
    sus: ['适合补充整体易用性基线。'],
    nps: ['适合长期口碑跟踪，但与当前页面任务距离较远。'],
    tam: ['当研究对象是新 AI 能力时更有价值。'],
    cognitive_load: ['页面信息密度高时可作为辅助框架。'],
    aesthetic_usability: ['可解释视觉质量对易用性感知的影响。'],
    fogg: ['当研究重点转向行为触发时可补充使用。'],
  },
  warnings: ['本结果未读取真实业务数据，也未执行用户调研。'],
  boundaryNotes: ['演示推荐来自前端固定规则和 fixture。', '方法资料仅展示索引名称，不代表已核验 PDF 正文。'],
}

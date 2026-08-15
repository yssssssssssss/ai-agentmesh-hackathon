import { Modal } from '../../components/ui/Modal'
import { AestheticQuantMockPanel } from './AestheticQuantMockPanel'
import { ExperienceModelMockPanel } from './ExperienceModelMockPanel'
import type { WorkspaceToolId } from './types'

interface WorkspaceToolDialogProps {
  activeTool: WorkspaceToolId | null
  onClose: () => void
}

const TITLES: Record<WorkspaceToolId, { title: string; subtitle: string }> = {
  'aesthetic-quant': {
    title: '美学量化演示',
    subtitle: '配置设计稿分析参数，预览固定的量化结果界面。',
  },
  'experience-model': {
    title: '体验模型演示',
    subtitle: '组合体验研究方法，预览固定的推荐结果界面。',
  },
}

export function WorkspaceToolDialog({ activeTool, onClose }: WorkspaceToolDialogProps) {
  if (!activeTool) return null
  const copy = TITLES[activeTool]
  return (
    <Modal open onClose={onClose} title={copy.title} subtitle={copy.subtitle} size="workspace">
      {activeTool === 'aesthetic-quant' ? <AestheticQuantMockPanel /> : <ExperienceModelMockPanel />}
    </Modal>
  )
}

import { Info } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { AgentSecondaryNav, type SectionKey } from '../components/digital-human/AgentSecondaryNav'
import { ProfileSection } from '../components/digital-human/ProfileSection'
import { UnderstandingSection } from '../components/digital-human/UnderstandingSection'
import { SkillsSection } from '../components/digital-human/SkillsSection'
import { KnowledgePermissionSection } from '../components/digital-human/KnowledgePermissionSection'
import { ActivitySection } from '../components/digital-human/ActivitySection'

const VALID_SECTIONS: SectionKey[] = ['profile', 'understanding', 'skills', 'knowledge', 'activity']

/** URL ?section= 是当前分区的唯一数据源;非法或缺省回落到 profile。 */
function normalizeSection(value: string | null): SectionKey {
  return VALID_SECTIONS.includes(value as SectionKey) ? (value as SectionKey) : 'profile'
}

/**
 * 数字人管理页(/digital-human)—— full-bleed。
 * 左侧固定二级导航 + 右侧独立滚动内容区。
 * 集中管理数字人的固定档案、理解、能力、知识权限与活动记录,
 * 与首页「我的数字人」(只放动态信息)分工明确。
 */
export function DigitalHuman() {
  const [params, setParams] = useSearchParams()
  const section = normalizeSection(params.get('section'))

  const setSection = (key: SectionKey) => {
    const next = new URLSearchParams(params)
    if (key === 'profile') next.delete('section')
    else next.set('section', key)
    setParams(next, { replace: true })
  }

  return (
    <div className="flex h-full overflow-hidden">
      <AgentSecondaryNav section={section} onSelect={setSection} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1240px] px-8 py-8">
          <div role="note" className="mb-6 flex items-start gap-3 rounded-[12px] border border-remind/25 bg-remind/[0.08] px-4 py-3 text-[13px] leading-5 text-slate-300">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-remind" aria-hidden="true" />
            <p><span className="font-semibold text-remind">本地视觉演示：</span>人物、数据和状态均为示意；页面内操作只影响当前本地预览，不会写入服务端，也不会跨登录会话保存。</p>
          </div>
          {section === 'profile' && <ProfileSection />}
          {section === 'understanding' && <UnderstandingSection />}
          {section === 'skills' && <SkillsSection />}
          {section === 'knowledge' && <KnowledgePermissionSection />}
          {section === 'activity' && <ActivitySection />}
        </div>
      </div>
    </div>
  )
}

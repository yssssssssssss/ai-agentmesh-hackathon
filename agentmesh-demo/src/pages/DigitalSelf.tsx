import { WelcomeHero } from '../components/digital-self/WelcomeHero'
import { UnderstandingList } from '../components/digital-self/UnderstandingList'
import { RecentGrowth } from '../components/digital-self/RecentGrowth'
import { MyImpact } from '../components/digital-self/MyImpact'

/**
 * 我的数字人 · 首页(统一主语 = 数字人)—— 只承载需要用户关注的动态信息,
 * 固定档案与复杂配置迁至「数字人管理」独立页(/digital-human)。
 *   01 数字人总览      — WelcomeHero:问候 + 工作上下文 + 今日优先事项
 *   02 待确认的理解    — UnderstandingList:仅列出待确认项,全部见数字人管理
 *   03 数字人能力更新  — RecentGrowth:本周新知识 / Skill / 协作
 *   04 本周协作动态    — MyImpact:近期共享与协作动态(累计指标见数字人管理)
 * UnderstandingList 携带 id="understanding",供总览「确认工作理解」入口滚动到位。
 */
export function DigitalSelf() {
  return (
    <div className="space-y-5">
      <WelcomeHero />

      <section className="border-t border-white/[0.08] pt-5">
        <div className="mb-3">
          <h2 className="text-[16px] font-semibold text-slate-100">数字员工动态</h2>
          <p className="mt-0.5 text-[12px] text-slate-500">近期形成的工作理解、成长与经验价值</p>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <UnderstandingList />
          <RecentGrowth />
          <MyImpact />
        </div>
      </section>
    </div>
  )
}

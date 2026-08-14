import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart3,
  Blocks,
  BookMarked,
  CheckCircle2,
  Eye,
  FileText,
  Pencil,
  PlayCircle,
  Sparkles,
} from 'lucide-react'
import { PageHeader } from '../components/ui/PageHeader'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Drawer } from '../components/ui/Drawer'
import { Modal } from '../components/ui/Modal'
import {
  INSIGHT_OVERVIEW,
  REVIEW_PROJECT,
  type InsightPeriod,
} from '../data/mockData'
import { useDemo } from '../store/DemoContext'
import { cn } from '../lib/cn'

const EMPHASIS_TERMS = ['2026 年 618 家电会场首页改版', '1 个需要进一步关注的问题']

/** 工作洞察：从连续工作中发现问题、跨项目规律与值得复盘的经验机会。 */
export function Insights() {
  const navigate = useNavigate()
  const { showToast } = useDemo()
  const period: InsightPeriod = 'lastWeek'
  const [confirmDrawerOpen, setConfirmDrawerOpen] = useState(false)
  const [confirmStep, setConfirmStep] = useState(0)
  const [knowledgeVisibility, setKnowledgeVisibility] = useState<'private' | 'team' | 'group'>('private')
  const [reviewEditing, setReviewEditing] = useState(false)
  const [experienceDeposited, setExperienceDeposited] = useState(false)
  const [evidenceDrawerOpen, setEvidenceDrawerOpen] = useState(false)
  const [skillDrawerOpen, setSkillDrawerOpen] = useState(false)
  const [ignoreConfirmOpen, setIgnoreConfirmOpen] = useState(false)
  const [insightHidden, setInsightHidden] = useState(false)

  const overview = INSIGHT_OVERVIEW[period]

  const goWorkspace = () => navigate('/workspace')
  const viewBrief = () => {
    navigate('/workspace')
    showToast('已在 AI 工作台打开设计 Brief', 'info')
  }

  return (
    <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6">
      <div className="order-1">
        <PageHeader
          title="工作洞察"
          subtitle="数字员工先参与工作，再经过一段时间回看记录与结果，形成阶段性洞察、跨项目规律和复盘建议。"
        />
      </div>

      {/* 01 最近发生了什么：弱化为背景上下文 */}
      <section className="order-2">
        <ModuleHeading
          title="近期工作概览"
          desc="数字员工汇总正在推进的工作，并持续等待更多结果形成后续判断"
          icon={<BarChart3 className="h-[20px] w-[20px]" />}
          tone="mint"
        />
        <div className="card-base p-5">
          <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h3 className="text-[14px] font-semibold text-slate-100">2026 年 618 家电会场首页改版</h3>
                <p className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-slate-400">
                  <Emphasized text={overview.summary} terms={EMPHASIS_TERMS} />
                </p>
                 <div className="mt-2 text-[11.5px] text-slate-500">{overview.meta}</div>
               </div>
               <Badge tone="neutral">暂未进入洞察</Badge>
             </div>
           <div className="mt-5 flex flex-wrap gap-2.5 border-t border-white/[0.06] pt-4">
            <Button variant="secondary" icon={<PlayCircle className="h-4 w-4" />} onClick={goWorkspace}>继续当前项目</Button>
            <Button variant="subtle" icon={<FileText className="h-4 w-4" />} onClick={viewBrief}>查看 Brief</Button>
          </div>
        </div>
      </section>

      {/* 02 洞察反馈：页面第一视觉重点 */}
      {!insightHidden ? (
      <section className="order-4">
        <ModuleHeading
          title="洞察反馈"
          desc="数字员工基于已经发生的项目、协作与结果，形成阶段性工作判断"
          icon={<Sparkles className="h-[20px] w-[20px]" />}
          tone="remind"
          hero
        />
        <section className="card-base p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-[17px] font-semibold text-white">多个项目正在重复同一套启动准备工作</h3>
              <p className="mt-1.5 max-w-4xl text-[13px] leading-relaxed text-slate-400">
                数字员工回看近期项目发现，项目启动阶段反复出现目标、范围、数据和协作信息确认，这些步骤已形成较稳定的工作模式。
              </p>
            </div>
          </div>

          <ol className="relative mt-6 space-y-6">
            <TimelineInsight
              index="01"
              label="发现现象"
              title="多个项目存在重复的启动确认"
              meta="涉及 4 个项目 · 12 次重复确认"
            >
              近期多个项目在正式推进前，都重复进行了目标、项目范围、指标口径、数据来源和协作方等信息确认。
            </TimelineInsight>
            <TimelineInsight index="02" label="形成判断" title="这些动作已经形成稳定的启动模式">
              不同项目业务内容虽然不同，但启动阶段需要确认的信息高度相似，已经具备标准化和复用条件。
            </TimelineInsight>
            <TimelineInsight index="03" label="建议行动" title="沉淀「项目启动 Workflow」Skill" action last meta="自动产出：项目启动 Brief">
              新项目启动时，由数字员工主动完成背景理解，并依次确认目标、范围、核心指标、数据口径、协作角色和验证计划。
            </TimelineInsight>
          </ol>

          <div className="mt-6 border-t border-white/[0.06] pt-4">
            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">发现来源</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {['家电会场首屏入口分析', '超级品类日楼层结构复盘', '导购卡首屏数量测试'].map((item) => (
                <button key={item} onClick={() => showToast(`已打开「${item}」来源记录（演示）`, 'info')} className="rounded-pill border border-white/[0.07] bg-white/[0.03] px-3 py-1.5 text-[12px] text-slate-400 hover:text-slate-200">{item}</button>
              ))}
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3 border-t border-white/[0.06] pt-4">
            <Button variant="primary" icon={<Blocks className="h-4 w-4" />} onClick={() => setSkillDrawerOpen(true)}>查看项目启动 Workflow</Button>
            <Button variant="ghost" onClick={() => setIgnoreConfirmOpen(true)}>暂不关注</Button>
          </div>
        </section>
      </section>
      ) : (
        <div className="order-4 card-base flex items-center justify-between gap-4 px-5 py-4 text-[12.5px] text-slate-500">
          <span>该洞察反馈已收起，可在「历史洞察 / 已忽略」中重新查看。</span>
          <Button variant="ghost" size="sm" onClick={() => setInsightHidden(false)}>恢复显示</Button>
        </div>
      )}

      {/* 03 从已结束项目进入知识闭环 */}
      <section className="order-3">
          <ModuleHeading
            title="值得复盘的历史项目"
            desc="数字员工从已结束项目中识别具有复用价值、但尚未完成正式复盘的经验机会"
            icon={<BookMarked className="h-[20px] w-[20px]" />}
            tone="knowledge"
          />
          <section className="card-base p-6">
            {experienceDeposited && (
              <div className="mb-5 flex items-center gap-3 rounded-[12px] border border-mint-400/25 bg-mint-400/[0.08] px-4 py-3 animate-fade-in">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-mint-300" />
                <span className="text-[13px] font-medium text-slate-100">经验已沉淀，数字员工将在类似项目中自动调用。</span>
              </div>
            )}

            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-[18px] font-bold text-white">{REVIEW_PROJECT.name}</h3>
                <div className="mt-3">
                  <h4 className="text-[15px] font-semibold text-slate-100">活动日历轻量化后，在保持活动曝光的同时释放了更多消息首屏空间</h4>
                </div>
              </div>
              <Badge tone={experienceDeposited ? 'mint' : 'remind'} dot>{experienceDeposited ? '已沉淀' : '待确认经验'}</Badge>
            </div>

            <div className="mt-6 border-t border-white/[0.06] pt-5">
              <SubHeading>AI 建议沉淀的经验</SubHeading>
              <h4 className="text-[15px] font-semibold leading-relaxed text-slate-100">内容型页面中的辅助运营模块，应优先保障主任务效率</h4>
              <p className="mt-2 max-w-4xl text-[12.5px] leading-relaxed text-slate-400">
                当辅助运营模块与页面主任务竞争首屏资源时，可通过减少信息层级、聚焦高价值内容和控制模块体量降低干扰；模块是否合并，应优先判断用户认知语义是否一致。
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {['首屏资源分配', '信息减法', '模块认知边界'].map((tag) => <Badge key={tag} tone="neutral">{tag}</Badge>)}
              </div>
              <div className="mt-5 border-t border-white/[0.06] pt-4">
                <div className="mb-3 text-[11px] font-medium uppercase tracking-wide text-slate-500">AI 数据追踪结果</div>
                <div className="grid gap-4 sm:grid-cols-3">
                  {[
                    ['活动日历 CTR', '0.62%', '较上线前 +24.0%'],
                    ['下方消息首屏曝光', '+8.4%', '首屏空间释放后提升'],
                    ['消息页浏览深度', '+5.1%', '未发现明显负向影响'],
                  ].map(([label, value, hint]) => (
                    <div key={label}>
                      <div className="text-[11.5px] text-slate-500">{label}</div>
                      <div className="mt-1 text-[20px] font-semibold tabular-nums text-slate-100">{value}</div>
                      <div className="mt-1 text-[10.5px] text-slate-600">{hint}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex items-center gap-2 text-[11.5px] text-slate-500">
                  <CheckCircle2 className="h-3.5 w-3.5 text-mint-300" />设计目标基本得到验证，未发现明显负向影响
                </div>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-2.5 border-t border-white/[0.06] pt-5">
              <Button
                variant="primary"
                icon={<CheckCircle2 className="h-4 w-4" />}
                disabled={experienceDeposited}
                onClick={() => setConfirmDrawerOpen(true)}
              >
                {experienceDeposited ? '经验已沉淀' : '查看并确认复盘'}
              </Button>
              <Button variant="subtle" icon={<Eye className="h-4 w-4" />} onClick={() => setEvidenceDrawerOpen(true)}>查看项目材料</Button>
              <Button variant="ghost" onClick={() => showToast('已稍后处理，该经验仍会保留', 'info')}>稍后处理</Button>
            </div>
          </section>
        </section>

      <div className="order-5 flex items-start gap-2 pt-1 text-[12px] leading-relaxed text-slate-600">
        <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        当前项目中的判断仍需上线结果验证；只有已完成项目经过复盘、补充真实结果并由用户确认后，才会形成知识候选。
      </div>

      <Drawer
        open={confirmDrawerOpen}
        onClose={() => setConfirmDrawerOpen(false)}
        width={560}
        title="查看并确认复盘"
        subtitle="审阅 AI 完成的项目复盘并确认知识使用权限"
        headerAction={
          <button
            type="button"
            onClick={() => setReviewEditing((value) => !value)}
            className={cn('rounded-lg p-1.5 transition-colors hover:bg-white/[0.06]', reviewEditing ? 'text-mint-300' : 'text-slate-400 hover:text-white')}
            aria-label={reviewEditing ? '退出编辑' : '编辑复盘'}
            title={reviewEditing ? '退出编辑' : '编辑复盘'}
          >
            <Pencil className="h-4 w-4" />
          </button>
        }
        footer={
          <div className="flex items-center justify-between gap-2.5">
            <Button variant="ghost" onClick={() => confirmStep === 0 ? setConfirmDrawerOpen(false) : setConfirmStep(0)}>{confirmStep === 0 ? '稍后处理' : '上一步'}</Button>
            {confirmStep === 0 ? (
              <Button variant="primary" onClick={() => setConfirmStep(1)}>下一步：设置权限</Button>
            ) : (
              <Button
                variant="primary"
                icon={<CheckCircle2 className="h-4 w-4" />}
                onClick={() => {
                  setConfirmDrawerOpen(false)
                  setConfirmStep(0)
                  setExperienceDeposited(true)
                  showToast('已沉淀为个人经验，数字员工将在类似项目中自动调用')
                }}
              >
                确认并沉淀经验
              </Button>
            )}
          </div>
        }
      >
        <div className="space-y-6">
          {confirmStep === 0 ? (
            <>
              <ReviewDocumentSection title="01 项目背景" editing={reviewEditing}>
                消息页中的活动日历原方案同时展示多个活动、倒计时、利益点及多个操作入口，模块体量较大。在以查看消息为主要任务的场景下，占用了较多首屏空间，也增加了用户扫读和判断成本。
                <ul className="mt-2 space-y-1 text-[12px] text-slate-400"><li>· 降低活动模块首屏占用</li><li>· 减少信息层级和操作入口</li><li>· 保留活动内容有效曝光</li><li>· 让更多消息内容进入首屏</li></ul>
              </ReviewDocumentSection>
              <ReviewDocumentSection title="02 核心方案" editing={reviewEditing}>
                最终保留活动日历的独立模块身份，将多活动展示收敛为 2 个重点活动：移除“全部活动”“订阅”等次级入口，减少倒计时、名称和利益点堆叠，仅保留必要时效提示，并压缩模块整体高度。
              </ReviewDocumentSection>
              <ReviewDocumentSection title="03 上线结果" editing={reviewEditing}>
                <div className="mb-2 text-[11px] text-slate-600">以下为 Demo Mock 数据，用于展示数字员工自动追踪结果的能力。</div>
                <ul className="space-y-2 text-[13px] text-slate-300"><li>活动日历 CTR：0.50% → 0.62%，较上线前 +24.0%</li><li>下方消息首屏曝光：+8.4%</li><li>消息页浏览深度：+5.1%</li></ul>
                <p className="mt-2 text-[12px] text-slate-500">活动模块减少内容和空间占用后，自身效率未下降，下方消息获得更多首屏展示机会。</p>
              </ReviewDocumentSection>
              <ReviewDocumentSection title="04 关键复盘结论" editing={reviewEditing}>
                <div className="space-y-3"><div><strong className="text-slate-200">辅助模块需要优先保障页面主任务</strong><p className="mt-0.5 text-[12px] text-slate-500">消息页核心任务是消息消费，活动和运营模块需控制空间与视觉权重。</p></div><div><strong className="text-slate-200">信息减法可以提升单位空间效率</strong><p className="mt-0.5 text-[12px] text-slate-500">聚焦高价值活动、减少信息层级，更有利于快速识别核心信息。</p></div><div><strong className="text-slate-200">模块合并需要关注认知边界</strong><p className="mt-0.5 text-[12px] text-slate-500">用户任务与信息语义不一致时，结构合并不一定带来认知简化。</p></div></div>
                {reviewEditing ? (
                  <textarea
                    defaultValue="内容消费型页面中的辅助运营模块，应优先保障主任务效率。当辅助运营模块与页面主任务竞争首屏资源时，可以通过减少信息层级、聚焦高价值内容、控制模块体量降低干扰；涉及模块合并时，还需要判断不同模块的用户任务与认知语义是否一致，避免为了结构精简而增加理解成本。"
                    rows={7}
                    className="mt-4 w-full resize-none border-b border-mint-400/30 bg-transparent py-2 text-[13px] leading-relaxed text-slate-300 outline-none"
                  />
                ) : (
                  <p className="mt-4 text-[13px] leading-relaxed text-slate-300">
                    内容消费型页面中的辅助运营模块，应优先保障主任务效率。当辅助运营模块与页面主任务竞争首屏资源时，可以通过减少信息层级、聚焦高价值内容、控制模块体量降低干扰；涉及模块合并时，还需要判断不同模块的用户任务与认知语义是否一致，避免为了结构精简而增加理解成本。
                  </p>
                )}
              </ReviewDocumentSection>
              <ReviewDocumentSection title="05 适用场景" editing={reviewEditing}>
                <div className="flex flex-wrap gap-2">{['消息页', '运营入口', '首屏资源分配', '信息减法', '模块整合'].map((item) => <Badge key={item} tone="knowledge">{item}</Badge>)}</div>
                <p className="mt-2 text-[12px] text-slate-500">数字员工后续遇到类似项目时，可以优先调用该经验作为方案判断依据。</p>
              </ReviewDocumentSection>
            </>
          ) : (
            <>
              <DrawerSection title="设置使用权限">
                <div className="space-y-2">
                  {[
                    { key: 'private', label: '仅自己', desc: '仅你和你的数字员工可以检索与使用' },
                    { key: 'team', label: '团队可用', desc: '当前团队内的数字员工可以检索与引用' },
                    { key: 'group', label: '京东集团可用', desc: '京东集团内有权限的数字员工可以检索与引用' },
                  ].map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => setKnowledgeVisibility(option.key as typeof knowledgeVisibility)}
                      className={cn('w-full rounded-[10px] border px-4 py-3 text-left transition-colors', knowledgeVisibility === option.key ? 'border-mint-400/30 bg-mint-400/[0.08]' : 'border-white/[0.06] bg-surface-1 hover:border-white/[0.12]')}
                    >
                      <div className={cn('text-[13px] font-medium', knowledgeVisibility === option.key ? 'text-mint-300' : 'text-slate-200')}>{option.label}</div>
                      <div className="mt-0.5 text-[11.5px] text-slate-500">{option.desc}</div>
                    </button>
                  ))}
                </div>
              </DrawerSection>
              <DrawerSection title="授权说明">所有后续引用都会保留经验来源、适用范围与确认人。你可以在「我的知识」中随时调整共享权限。</DrawerSection>
            </>
          )}
        </div>
      </Drawer>

      <Drawer
        open={evidenceDrawerOpen}
        onClose={() => setEvidenceDrawerOpen(false)}
        width={520}
        icon={<FileText className="h-5 w-5" />}
        title="消息活动日历改版 · AI 复盘依据"
        subtitle="查看数字员工如何追踪上线表现并形成当前结论"
      >
        <div className="space-y-6">
          <DrawerSection title="项目设计方案">活动日历由多活动并列展示调整为双卡聚焦方案，减少同屏活动数量并精简信息层级。</DrawerSection>
          <DrawerSection title="上线版本">消息卡片与 Feed 主链路保持不变，活动日历模块降低体量并释放下方内容首屏空间。</DrawerSection>
          <DrawerSection title="AI 追踪指标">
            <ul className="space-y-2 text-[13px] text-slate-300">
              <li>活动日历 CTR：0.62%，较上线前提升 24.0%</li>
              <li>下方消息首屏曝光：提升 8.4%</li>
              <li>消息页浏览深度：提升 5.1%</li>
            </ul>
          </DrawerSection>
          <DrawerSection title="关键项目材料">改版设计稿、项目决策记录、上线版本记录、页面曝光与点击数据。</DrawerSection>
          <DrawerSection title="AI 如何形成结论">关联设计变更前后的模块结构，对比上线指标和页面协同指标，并检查消息消费主链路是否出现负向变化后形成判断。</DrawerSection>
        </div>
      </Drawer>

      <Drawer
        open={skillDrawerOpen}
        onClose={() => setSkillDrawerOpen(false)}
        width={520}
        icon={<Blocks className="h-5 w-5" />}
        title="项目启动 Workflow"
        subtitle="将项目启动阶段反复发生的确认工作标准化，由数字员工辅助完成项目启动校准。"
        footer={
          <div className="flex items-center justify-end gap-2.5">
            <Button variant="ghost" onClick={() => setSkillDrawerOpen(false)}>暂不创建</Button>
            <Button variant="subtle" onClick={() => showToast('已进入 Workflow 调整模式', 'info')}>调整 Workflow</Button>
            <Button variant="primary" onClick={() => { setSkillDrawerOpen(false); showToast('已创建项目启动 Skill') }}>创建项目启动 Skill</Button>
          </div>
        }
      >
        <div className="space-y-6">
          <Badge tone="knowledge">数字员工建议创建</Badge>
          <ol className="relative space-y-5">
            {[
              ['理解项目', '快速理解项目背景和已有材料', ['当前要解决什么问题', '为什么现在启动', '已有哪些项目材料']],
              ['明确目标', '对齐项目最终需要解决的问题', ['业务目标', '用户目标', '设计目标', '成功标准']],
              ['确认项目范围', '明确本次项目的工作边界', ['本次解决什么', '本次不解决什么', '涉及哪些页面 / 场域 / 端']],
              ['确认数据', '提前建立统一的数据判断基础', ['核心指标', '指标口径', '数据来源', '当前基线']],
              ['确认协作关系', '明确项目中的关键协作角色', ['产品', '研发', '数据', '业务', '决策人']],
              ['形成验证方案', '在启动阶段提前确定项目如何验证', ['上线验证指标', 'AB 实验', '定性验证', '复盘时间点']],
            ].map(([title, desc, checks], index, all) => (
              <li key={title as string} className="relative flex gap-3.5">
                {index < all.length - 1 && <span className="absolute left-[5px] top-4 h-[calc(100%+24px)] w-px bg-white/[0.09]" />}
                <span className={cn('relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-surface-2', index === all.length - 1 ? 'bg-mint-400' : 'bg-slate-500')} />
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-medium text-slate-500">0{index + 1}</div>
                  <h3 className="mt-1 text-[13.5px] font-semibold text-slate-100">{title as string}</h3>
                  <p className="mt-0.5 text-[12px] text-slate-500">{desc as string}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(checks as string[]).map((check) => <span key={check} className="rounded-pill bg-white/[0.04] px-2 py-1 text-[10.5px] text-slate-400">{check}</span>)}
                  </div>
                </div>
              </li>
            ))}
          </ol>
          <div className="border-t border-white/[0.06] pt-5">
            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Workflow 输出</div>
            <h3 className="mt-1 text-[16px] font-semibold text-white">《项目启动 Brief》</h3>
            <p className="mt-1 text-[12.5px] leading-relaxed text-slate-400">完成以上确认后，由数字员工自动整理项目背景、目标、范围、指标、协作关系和验证方案，生成统一的项目启动 Brief。</p>
            <div className="mt-3 flex flex-wrap gap-2">{['项目背景', '目标', '范围', '核心指标', '协作角色', '验证计划'].map((item) => <Badge key={item} tone="neutral">{item}</Badge>)}</div>
          </div>
        </div>
      </Drawer>

      <Modal
        open={ignoreConfirmOpen}
        onClose={() => setIgnoreConfirmOpen(false)}
        title="暂不关注这条洞察？"
        subtitle="这条洞察将从当前列表中收起，不再作为待处理内容展示。相关工作记录仍会保留。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setIgnoreConfirmOpen(false)}>取消</Button>
            <Button variant="danger" onClick={() => { setIgnoreConfirmOpen(false); setInsightHidden(true); showToast('已暂不关注，可在历史洞察中重新查看', 'info') }}>暂不关注</Button>
          </>
        }
      >
        <p className="text-[13px] leading-relaxed text-slate-400">
          数字员工仍会持续理解后续工作。如果同类问题明显升级或形成新的重要风险，仍可能生成新的洞察提醒。
        </p>
      </Modal>
    </div>
  )
}

function ReviewDocumentSection({ title, editing, children }: { title: string; editing: boolean; children: ReactNode }) {
  return (
    <section
      contentEditable={editing}
      suppressContentEditableWarning
      className={cn('rounded-[10px] transition-colors', editing && 'bg-white/[0.025] px-3 py-2 outline outline-1 outline-mint-400/15 focus:outline-mint-400/40')}
    >
      <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="text-[13px] leading-relaxed text-slate-300">{children}</div>
    </section>
  )
}

function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="text-[13px] leading-relaxed text-slate-300">{children}</div>
    </section>
  )
}

function ModuleHeading({
  title,
  desc,
  icon,
  tone = 'mint',
  hero,
}: {
  title: string
  desc?: string
  icon: ReactNode
  tone?: 'mint' | 'remind' | 'knowledge'
  hero?: boolean
}) {
  const toneClass = tone === 'remind'
    ? 'bg-remind/[0.14] text-remind'
    : tone === 'knowledge'
      ? 'bg-knowledge/[0.14] text-knowledge'
      : 'bg-mint-400/[0.14] text-mint-300'

  return (
    <div className="mb-3 flex items-center gap-3">
      <span className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px]', toneClass)}>
        {icon}
      </span>
      <div className="min-w-0">
        <h2 className={cn('font-semibold text-slate-100', hero ? 'text-[17px]' : 'text-[15px]')}>{title}</h2>
        {desc && <p className="mt-0.5 text-[12px] text-slate-500">{desc}</p>}
      </div>
    </div>
  )
}

function SubHeading({ children }: { children: ReactNode }) {
  return <div className="mb-2.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">{children}</div>
}

function TimelineInsight({
  index,
  label,
  title,
  meta,
  action,
  last,
  children,
}: {
  index: string
  label: string
  title: string
  meta?: string
  action?: boolean
  last?: boolean
  children: ReactNode
}) {
  return (
    <li className="relative flex gap-4">
      {!last && <span className="absolute left-[5px] top-4 h-[calc(100%+28px)] w-px bg-white/[0.10]" />}
      <span
        className={cn(
          'relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-surface-1',
          action ? 'bg-mint-400' : 'bg-slate-500',
        )}
      />
      <div className="min-w-0 flex-1 pb-1">
        <div className={cn('text-[11px] font-medium uppercase tracking-wide', action ? 'text-mint-300' : 'text-slate-500')}>
          {index} {label}
        </div>
        <h4 className="mt-1.5 text-[14px] font-semibold text-slate-100">{title}</h4>
        <p className="mt-1 text-[12.5px] leading-relaxed text-slate-400">{children}</p>
        {meta && <div className="mt-2 text-[11px] text-slate-500">{meta}</div>}
      </div>
    </li>
  )
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function Emphasized({ text, terms }: { text: string; terms: string[] }) {
  const valid = terms.filter(Boolean)
  if (!valid.length) return <>{text}</>
  const regexp = new RegExp(`(${valid.map(escapeRegExp).join('|')})`, 'g')
  return (
    <>
      {text.split(regexp).map((part, index) =>
        valid.includes(part) ? (
          <strong key={index} className="font-semibold text-white">{part}</strong>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

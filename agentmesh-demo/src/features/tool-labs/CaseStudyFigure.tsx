import jdNewArrivalsCaseImage from '../../assets/jd-new-arrivals-case.jpg'
import { cn } from '../../lib/cn'
import type { ToolCaseRegion } from './types'

interface CaseStudyFigureProps {
  alt: string
  regions: ToolCaseRegion[]
  showHeatmap?: boolean
  className?: string
}

const HEATMAP_SPOTS = [
  { label: '商品图热点', className: 'left-[9%] top-[67%] h-[16%] w-[43%] bg-rose/35' },
  { label: '搜索热点', className: 'left-[5%] top-[9%] h-[8%] w-[88%] bg-remind/25' },
  { label: '红包热点', className: 'left-[75%] top-[69%] h-[12%] w-[21%] bg-rose/45' },
]

export function CaseStudyFigure({ alt, regions, showHeatmap = false, className }: CaseStudyFigureProps) {
  const annotated = regions.length > 0 || showHeatmap
  return (
    <figure data-testid="case-study-figure" className={cn('rounded-overlay border border-white/[0.08] bg-base p-3 shadow-card', className)}>
      <div className="relative mx-auto w-full max-w-[360px] overflow-hidden rounded-overlay bg-white outline outline-1 -outline-offset-1 outline-white/10">
        <img
          src={jdNewArrivalsCaseImage}
          alt={alt}
          width={360}
          height={480}
          loading="lazy"
          className="block w-full"
        />
        {showHeatmap
          ? HEATMAP_SPOTS.map((spot) => (
            <span
              key={spot.label}
              aria-hidden="true"
              className={cn('pointer-events-none absolute rounded-full blur-xl mix-blend-multiply', spot.className)}
            />
          ))
          : null}
        {regions.map((region) => (
          <div
            key={region.id}
            className="absolute rounded-soft border border-mint-300/80 bg-mint-400/[0.08] shadow-[0_0_0_1px_rgba(15,18,22,0.35)]"
            style={{
              left: region.x + '%',
              top: region.y + '%',
              width: region.width + '%',
              height: region.height + '%',
            }}
          >
            <span className="absolute left-1 top-1 rounded-full bg-base/85 px-2 py-0.5 text-[11px] font-semibold leading-none text-mint-200 shadow-card">
              {region.label}
            </span>
          </div>
        ))}
      </div>
      <figcaption className="mt-3 text-xs leading-5 text-slate-400">
        {annotated ? '案例截图内置于前端资产，ROI 与热点均为固定示例标注。' : '案例原图预览。生成报告后展示 ROI 与热点示例标注。'}
      </figcaption>
    </figure>
  )
}

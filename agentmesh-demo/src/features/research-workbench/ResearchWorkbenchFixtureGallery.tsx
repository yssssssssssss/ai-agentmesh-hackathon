import { adaptWorkbenchAggregate } from './adapter'
import { ResearchWorkbench } from './ResearchWorkbench'
import type { ResearchWorkbenchActions, WorkbenchAggregateV1 } from './types'

export interface ResearchWorkbenchFixture {
  id: string
  label: string
  aggregate: WorkbenchAggregateV1 | unknown
}

/**
 * Isolated visual harness for the canonical fixture matrix. It is deliberately not imported by
 * Workspace or the app router; callers supply fixture JSON so production bundles do not include it.
 */
export function ResearchWorkbenchFixtureGallery({
  fixtures,
  actions = {},
}: {
  fixtures: readonly ResearchWorkbenchFixture[]
  actions?: ResearchWorkbenchActions
}) {
  return (
    <main className="research-workbench-current rw-fixture-gallery" aria-label="Research workbench fixture gallery">
      {fixtures.map((fixture) => {
        const aggregate = adaptWorkbenchAggregate(fixture.aggregate)
        return (
          <section className="rw-fixture-frame" key={fixture.id} data-fixture-id={fixture.id}>
            <header><h1>{fixture.label}</h1><code>{fixture.id}</code></header>
            <ResearchWorkbench aggregate={aggregate} actions={actions} />
          </section>
        )
      })}
    </main>
  )
}

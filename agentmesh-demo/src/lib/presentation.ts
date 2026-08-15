export type DataSourceKind = 'M' | 'T'
export type PresentationState = 'available' | 'empty' | 'unsupported' | 'loading' | 'forbidden' | 'error'

export interface PresentedValue<T> {
  value: T
  source: DataSourceKind
  reason?: string
}

export interface PresentedModule<T> {
  data: T
  sources: DataSourceKind[]
  missingFields: string[]
  loading: boolean
  error: string | null
}

interface PresentedModuleOptions {
  missingFields?: string[]
  loading?: boolean
  error?: string | null
}

export function dataSourceKind(value: string): DataSourceKind {
  if (value === 'M' || value === 'T') return value
  throw new Error(`Unknown data source kind: ${value}`)
}

export function canUseMockFallback(state: PresentationState): boolean {
  return state === 'empty' || state === 'unsupported'
}

export function presentedValue<T>(
  value: T,
  source: DataSourceKind,
  reason?: string,
): PresentedValue<T> {
  return reason === undefined ? { value, source } : { value, source, reason }
}

export function moduleSources(values: readonly PresentedValue<unknown>[]): DataSourceKind[] {
  const sources: DataSourceKind[] = []
  for (const item of values) {
    if (!sources.includes(item.source)) sources.push(item.source)
  }
  return sources
}

export function presentedModule<T>(
  data: T,
  values: readonly PresentedValue<unknown>[],
  options: PresentedModuleOptions = {},
): PresentedModule<T> {
  return {
    data,
    sources: moduleSources(values),
    missingFields: options.missingFields ?? [],
    loading: options.loading ?? false,
    error: options.error ?? null,
  }
}

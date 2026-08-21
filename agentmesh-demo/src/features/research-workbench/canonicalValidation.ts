import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'

import canonicalWorkbenchSchema from './research-workbench-aggregate-v1.schema.json'

/** SHA-256 of the frozen backend schema copied beside this validator. */
export const CANONICAL_WORKBENCH_SCHEMA_SHA256 = 'fcbc2f0c73e4476dd08be9b058cde6d66f09d8751503209d2a35abc559e91f19'

const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats(ajv)
const validate = ajv.compile(canonicalWorkbenchSchema)

/** Runs the complete structural contract before semantic validation or render projection. */
export function validateCanonicalWorkbenchSchema(input: unknown): void {
  if (validate(input)) return
  const detail = validate.errors?.map((error) => `${error.instancePath || '/'} ${error.message ?? 'is invalid'}`).join('; ')
  throw new TypeError(`Invalid research-workbench-aggregate-v1: ${detail ?? 'schema validation failed'}`)
}

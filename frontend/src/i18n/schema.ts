import type es from './locales/es-ES'

/** Widens es-ES's literal string types to `string` so other locale files can assign their own
 * translated text, while TypeScript still enforces that every locale defines exactly the same
 * set of nested keys (missing/extra keys are compile errors via excess-property checks). */
type Widen<T> = T extends string ? string : { [K in keyof T]: Widen<T[K]> }

export type MessageSchema = Widen<typeof es>

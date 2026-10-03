// The three proposals the switcher offers. Each variant owns only its own folder.
import type { VariantDefinition } from '../shared/types'
import VariantA, { NAME as NAME_A } from './a'
import VariantB, { NAME as NAME_B } from './b'
import VariantC, { NAME as NAME_C } from './c'

export const VARIANTS: VariantDefinition[] = [
  { key: 'a', letter: 'A', name: NAME_A, component: VariantA },
  { key: 'b', letter: 'B', name: NAME_B, component: VariantB },
  { key: 'c', letter: 'C', name: NAME_C, component: VariantC },
]

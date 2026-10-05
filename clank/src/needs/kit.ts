// Everything a proposal needs, WITHOUT the shell: proposals import from '../kit' (not '../'), so n<k> -> index ->
// NeedsShell -> n<k> never forms an import cycle.
export * from './types'
export * from './api'
export * from './answers'
export * from './exportAnswers'
export type { NeedsProposalProps, NeedsProposalDefinition } from './proposal'
export { CopyOut } from './CopyOut'
export type { CopyOutProps } from './CopyOut'
export { EvidenceLink, evidenceHref } from './EvidenceLink'
export type { EvidenceLinkProps } from './EvidenceLink'
export { PlaceholderList } from './PlaceholderList'

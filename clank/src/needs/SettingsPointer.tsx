// The plain-text pointer a lane prints beside "N more are defaulting without you": the one place they can be added to
// the lane is the settings page. WHY a sentence with a link and never a "Review them too" button: including them
// changes what the queue shows, a view option, and view options live only on the settings page (Codex audit
// 2026-10-04, finding 13; docs/dashboard/VARIANTS.md "Settings").

/** The setting's title, verbatim from shared/settings.ts, so the pointer names exactly the row Zach will find. */
export const INCLUDE_DEFAULTING_TITLE = 'Include questions whose default is already in effect'

export function IncludeDefaultingPointer({ openSettings, testId }: { openSettings(): void; testId?: string }) {
  return (
    <>
      To queue them too, turn on “{INCLUDE_DEFAULTING_TITLE}” in{' '}
      <button type="button" className="vt-btn vt-needs-settings-link" onClick={openSettings} data-testid={testId ?? 'vt-needs-settings-link'}>
        Settings
      </button>
      .
    </>
  )
}

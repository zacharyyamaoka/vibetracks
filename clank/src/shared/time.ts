// One way to show a moment to Zach: local time with its zone name ("10-04 17:55 PDT"), the raw ISO kept for a title.
// WHY one shared formatter: four views each formatted ISO stamps their own way, so one page read "17:55 PDT" next to
// "since 10-05 00:55 UTC" (the same moment in two zones) and evidence rows dropped the zone entirely, reading UTC run
// times 7-8 h ahead. Every human-facing time goes through here; machine fields keep their ISO strings.

export interface LocalStampOptions {
  /** Include the year ("2026-10-04 17:55 PDT"); default false ("10-04 17:55 PDT"). */
  year?: boolean
  /** Date only ("10-04" / "2026-10-04"); no clock and no zone. */
  dateOnly?: boolean
}

const pad = (n: number) => String(n).padStart(2, '0')

function zoneName(date: Date): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' })
      .formatToParts(date)
      .find((p) => p.type === 'timeZoneName')
    return part?.value ?? ''
  } catch {
    return ''
  }
}

/** Format an ISO stamp in local time. Unparseable input comes back verbatim (never silently dropped). */
export function formatLocal(iso: string | null | undefined, options: LocalStampOptions = {}): string {
  if (!iso) return ''
  // A bare date ("2026-10-04") has no moment and no zone: show it as written.
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return options.year ? iso : iso.slice(5)
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const day = `${options.year ? `${date.getFullYear()}-` : ''}${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  if (options.dateOnly) return day
  const zone = zoneName(date)
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}${zone ? ` ${zone}` : ''}`
}

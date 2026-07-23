import { getAPIUrl } from '@services/config/config'

// Integrity (no-skip) course_uuid set — courses whose videos disable forward-seek
// past the watched point (cert/CEU integrity). Fetched once per page load and
// cached at module scope so every video reuses the same request. Fail-open: any
// error yields an empty set (normal seeking), never a broken player.
let _noSkipPromise: Promise<Set<string>> | null = null

export function getNoSkipCourses(): Promise<Set<string>> {
  if (!_noSkipPromise) {
    _noSkipPromise = fetch(`${getAPIUrl()}bbu/migrate/no-skip-courses`)
      .then((r) => (r.ok ? r.json() : { course_uuids: [] }))
      .then((d) => new Set<string>(d?.course_uuids || []))
      .catch(() => new Set<string>())
  }
  return _noSkipPromise
}

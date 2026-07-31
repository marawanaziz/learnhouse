type Activity = {
  id?: number | string
  activity_uuid?: string
}

type Course = {
  chapters?: Array<{ activities?: Activity[] }>
}

type TrailRun = {
  steps?: Array<{ activity_id?: number | string; complete?: boolean }>
}

/** Pick the first unfinished activity, or the final one after completion. */
export function getResumeActivity(course: Course, run?: TrailRun | null): Activity | null {
  const activities = (course.chapters ?? []).flatMap((chapter) => chapter.activities ?? [])
  if (!activities.length) return null

  const completed = new Set(
    (run?.steps ?? [])
      .filter((step) => step.complete !== false)
      .map((step) => String(step.activity_id))
  )
  return activities.find((activity) => !completed.has(String(activity.id))) ?? activities.at(-1) ?? null
}

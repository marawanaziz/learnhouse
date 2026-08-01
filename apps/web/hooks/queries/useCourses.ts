'use client'

import { useQuery } from '@tanstack/react-query'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { queryKeys } from '@lib/query/keys'
import { getOrgCourses, getCourseMetadata } from '@services/courses/courses'

export function useCourses(orgSlug: string) {
  const session = useLHSession() as any
  const accessToken = session?.data?.tokens?.access_token as string | undefined

  return useQuery({
    queryKey: queryKeys.courses.list(orgSlug),
    queryFn: () => getOrgCourses(orgSlug, {}, accessToken),
    enabled: !!orgSlug,
    staleTime: 60_000,
  })
}

export function useCourseMeta(courseUuid: string, options?: { requireAuth?: boolean }) {
  const session = useLHSession() as any
  const accessToken = session?.data?.tokens?.access_token as string | undefined
  const sessionReady = session?.status !== 'loading'
  const authReady = !options?.requireAuth || session?.status === 'authenticated'

  return useQuery({
    queryKey: queryKeys.courses.meta(courseUuid),
    queryFn: () => getCourseMetadata(courseUuid, {}, accessToken, { slim: true }),
    enabled: !!courseUuid && sessionReady && authReady,
    staleTime: 60_000,
  })
}

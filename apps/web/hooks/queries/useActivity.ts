'use client'

import { useQuery } from '@tanstack/react-query'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { queryKeys } from '@lib/query/keys'
import { getActivityWithAuthHeader } from '@services/courses/activities'

export function useActivity(activityUuid: string, options?: { requireAuth?: boolean; enabled?: boolean }) {
  const session = useLHSession() as any
  const accessToken = session?.data?.tokens?.access_token as string | undefined
  const sessionReady = session?.status !== 'loading'
  const authReady = !options?.requireAuth || session?.status === 'authenticated'

  return useQuery({
    queryKey: queryKeys.activity.detail(activityUuid),
    queryFn: () => getActivityWithAuthHeader(activityUuid, {}, accessToken),
    enabled: options?.enabled !== false && !!activityUuid && sessionReady && authReady,
    staleTime: 60_000,
  })
}

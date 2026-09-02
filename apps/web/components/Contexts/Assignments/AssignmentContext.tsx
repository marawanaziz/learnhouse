'use client'
import { getAPIUrl } from '@services/config/config'
import { apiFetch } from '@services/utils/ts/requests'
import React, { createContext, useContext, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '@/lib/query/keys'
import { useLHSession } from '@components/Contexts/LHSessionContext'

export const AssignmentContext = createContext({})

export function AssignmentProvider({ children, assignment_uuid }: { children: React.ReactNode, assignment_uuid: string }) {
    const session = useLHSession() as any
    const accessToken = session?.data?.tokens?.access_token

    const { data: assignment, error: assignmentError } = useQuery({
        queryKey: queryKeys.assignments.detail(assignment_uuid),
        queryFn: () => apiFetch(`${getAPIUrl()}assignments/${assignment_uuid}`, accessToken),
        enabled: !!(assignment_uuid && accessToken),
        staleTime: 60_000,
    })

    const { data: assignment_tasks, error: assignmentTasksError } = useQuery({
        queryKey: queryKeys.assignments.tasks(assignment_uuid),
        queryFn: () => apiFetch(`${getAPIUrl()}assignments/${assignment_uuid}/tasks`, accessToken),
        enabled: !!(assignment_uuid && accessToken),
        staleTime: 60_000,
    })

    // course_uuid/activity_uuid are now embedded in the assignment payload
    // (joined server-side) so we don't need separate /courses/id and
    // /activities/id round trips. We synthesize tiny shim objects to keep
    // existing consumers (which read .course_uuid / .activity_uuid) working
    // without changes. useMemo (vs useState+useEffect) means the provider
    // value is correct on the same render the SWR data lands, with no
    // wasted null-context render cycle.
    const assignmentsFull = useMemo(() => {
        if (!assignment || !assignment_tasks) return null
        return {
            assignment_object: assignment,
            assignment_tasks: assignment_tasks,
            course_object: assignment.course_uuid
                ? { course_uuid: assignment.course_uuid }
                : null,
            activity_object: assignment.activity_uuid
                ? { activity_uuid: assignment.activity_uuid }
                : null,
        }
    }, [assignment, assignment_tasks])

    if (assignmentError || assignmentTasksError) {
        return (
            <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-900">
                This quiz could not be loaded. Please try again or contact support if the problem continues.
            </div>
        )
    }

    if (!assignmentsFull) {
        return (
            <div className="flex h-40 items-center justify-center" aria-label="Loading quiz">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-700" />
            </div>
        )
    }

    return <AssignmentContext.Provider value={assignmentsFull}>{children}</AssignmentContext.Provider>
}

export function useAssignments() {
    return useContext(AssignmentContext)
}

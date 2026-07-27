import React, { useState, useEffect } from 'react'
import { Check, Square, ArrowRight, Folder, FileText, Video, Layers, BookOpenCheck } from 'lucide-react'
import { getUriWithOrg } from '@services/config/config'
import Link from 'next/link'
import Modal from '@components/Objects/StyledElements/Modal/Modal'

interface CourseProgressProps {
  course: any
  orgslug: string
  isOpen: boolean
  onClose: () => void
  trailData: any
}

const CourseProgress: React.FC<CourseProgressProps> = ({ course, orgslug, isOpen, onClose, trailData }) => {
  // The workbook lives on the cohort, not the course, so learners had no way to
  // reach it. Renders only when a URL is actually configured — no dead button.
  const [courseBook, setCourseBook] = React.useState<{ url: string; label: string } | null>(null)
  React.useEffect(() => {
    const uuid = (course as any)?.course_uuid
    if (!isOpen || !uuid) return
    fetch(`/api/v1/bbu/course-book?course_uuid=${encodeURIComponent(uuid)}`, {
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCourseBook(d && d.url ? d : null))
      .catch(() => setCourseBook(null))
  }, [isOpen, (course as any)?.course_uuid])

  const [completedActivities, setCompletedActivities] = useState(0)
  const [totalActivities, setTotalActivities] = useState(0)

  useEffect(() => {
    let total = 0
    let completed = 0

    ;(course.chapters ?? []).forEach((chapter: any) => {
      (chapter.activities ?? []).forEach((activity: any) => {
        total++
        if (isActivityDone(activity)) {
          completed++
        }
      })
    })

    setTotalActivities(total)
    setCompletedActivities(completed)
  }, [course])

  const isActivityDone = (activity: any) => {
    const cleanCourseUuid = course.course_uuid?.replace('course_', '');
    const run = trailData?.runs?.find(
      (run: any) => {
        const cleanRunCourseUuid = run.course?.course_uuid?.replace('course_', '');
        return cleanRunCourseUuid === cleanCourseUuid;
      }
    );
    if (run) {
      return run.steps.find((step: any) => step.activity_id === activity.id)
    }
    return false
  }

  const getActivityTypeIcon = (activityType: string) => {
    switch (activityType) {
      case 'TYPE_VIDEO':
        return <Video size={16} className="text-gray-400" />
      case 'TYPE_DOCUMENT':
        return <FileText size={16} className="text-gray-400" />
      case 'TYPE_DYNAMIC':
        return <Layers size={16} className="text-gray-400" />
      case 'TYPE_ASSIGNMENT':
        return <BookOpenCheck size={16} className="text-gray-400" />
      default:
        return <FileText size={16} className="text-gray-400" />
    }
  }

  const dialogContent = (
    <div className="space-y-4">
      {(course.chapters ?? []).map((chapter: any) => (
        <div key={chapter.chapter_uuid} className="bg-gray-50 rounded-lg overflow-hidden">
          <div className="px-4 py-3 bg-gray-100 font-semibold text-gray-700 flex items-center space-x-2">
            <Folder size={16} className="text-gray-400" />
            <span>{chapter.name}</span>
          </div>
          <div className="divide-y divide-gray-100">
            {(chapter.activities ?? []).map((activity: any) => {
              const activityId = activity.activity_uuid.replace('activity_', '')
              const courseId = course.course_uuid.replace('course_', '')
              return (
                <Link
                  key={activity.activity_uuid}
                  href={getUriWithOrg(orgslug, '') + `/course/${courseId}/activity/${activityId}`}
                >
                  <div className="px-4 py-3 hover:bg-gray-100 transition-colors flex items-center group">
                    <div className="flex items-center space-x-3 flex-1">
                      {isActivityDone(activity) ? (
                        <div className="relative">
                          <Square size={18} className="stroke-[2] text-teal-600" />
                          <Check size={18} className="stroke-[2.5] text-teal-600 absolute top-0 left-0" />
                        </div>
                      ) : (
                        <Square size={18} className="stroke-[2] text-gray-300" />
                      )}
                      <div className="flex items-center space-x-2">
                        {getActivityTypeIcon(activity.activity_type)}
                        <span className="text-gray-700 group-hover:text-gray-900">
                          {activity.name}
                        </span>
                      </div>
                    </div>
                    <ArrowRight size={16} className="text-gray-400 group-hover:text-gray-600" />
                  </div>
                </Link>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )

  const dialogWithBook = (
    <div>
      {courseBook?.url && (
        <a
          href={courseBook.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 mb-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm font-semibold text-gray-900 hover:bg-gray-100"
        >
          {courseBook.label || 'Download the course book'}
        </a>
      )}
      {dialogContent}
    </div>
  )

  return (
    <Modal
      isDialogOpen={isOpen}
      onOpenChange={onClose}
      dialogContent={dialogWithBook}
      dialogTitle="Course Progress"
      dialogDescription={`${completedActivities} of ${totalActivities} activities completed`}
      minWidth="md"
    />
  )
}

export default CourseProgress 
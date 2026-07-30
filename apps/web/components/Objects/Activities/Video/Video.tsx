import React from 'react'
import YouTube from 'react-youtube'
import { useOrg } from '@components/Contexts/OrgContext'
import { getNoSkipCourses } from '@services/media/noSkipCourses'
import {
  getVideoProgress,
  resolveResumePosition,
  saveVideoProgress,
  type VideoProgressIdentity,
} from '@services/media/videoProgress'
import LearnHousePlayer from './LearnHousePlayer'
import {
  isActivityHlsReady,
  resolveActivityVideoSource,
  resolveHlsThumbnails,
  resolveActivityCaptions,
} from './videoSource'

interface VideoDetails {
  startTime?: number
  endTime?: number | null
  autoplay?: boolean
  muted?: boolean
}

interface VideoActivityProps {
  activity: {
    activity_sub_type: string
    activity_uuid: string
    content: {
      filename?: string
      uri?: string
    }
    details?: VideoDetails
    extra_metadata?: {
      hls?: {
        status?: string
        thumbnails?: {
          url?: string
          interval?: number
          width?: number
          height?: number
          columns?: number
          rows?: number
        } | null
      }
      captions?: {
        enabled?: boolean
        languages?: { code?: string; label?: string; status?: string }[]
      } | null
    } | null
  }
  course: {
    course_uuid: string
  }
  orgUuid?: string
}

function PersistedYouTubePlayer({
  videoId,
  activityUuid,
  details,
}: {
  videoId: string
  activityUuid: string
  details?: VideoDetails
}) {
  const playerRef = React.useRef<any>(null)
  const checkpointReadyRef = React.useRef(false)
  const playbackEndedRef = React.useRef(false)
  const intervalRef = React.useRef<ReturnType<typeof setInterval> | null>(null)
  const identity = React.useMemo<VideoProgressIdentity>(
    () => ({
      activityUuid,
      videoKey: activityUuid,
      sourceId: `youtube:${videoId}`,
    }),
    [activityUuid, videoId]
  )

  const persist = React.useCallback(
    (resetToStart = false, keepalive = false) => {
      const player = playerRef.current
      if (!player || !checkpointReadyRef.current) return
      const position = resetToStart ? 0 : Number(player.getCurrentTime?.() ?? 0)
      const duration = Number(player.getDuration?.() ?? 0)
      void saveVideoProgress(
        identity,
        position,
        Number.isFinite(duration) && duration > 0 ? duration : null,
        { keepalive }
      )
    },
    [identity]
  )

  const stopInterval = React.useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  React.useEffect(() => {
    const onPageHide = () => persist(playbackEndedRef.current, true)
    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        persist(playbackEndedRef.current, true)
      }
    }
    window.addEventListener('pagehide', onPageHide)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      persist(playbackEndedRef.current, true)
      stopInterval()
      window.removeEventListener('pagehide', onPageHide)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [persist, stopInterval])

  return (
    <YouTube
      className="w-full h-full"
      opts={{
        width: '100%',
        height: '100%',
        playerVars: {
          autoplay: details?.autoplay ? 1 : 0,
          mute: details?.muted ? 1 : 0,
          start: details?.startTime || 0,
          end: details?.endTime || undefined,
          controls: 1,
          modestbranding: 1,
          rel: 0,
        },
      }}
      videoId={videoId}
      onReady={async (event) => {
        playerRef.current = event.target
        const saved = await getVideoProgress(identity)
        const duration = Number(event.target.getDuration?.() ?? 0)
        const resumeAt = resolveResumePosition({
          savedPosition: saved?.position_seconds ?? 0,
          duration,
          startTime: details?.startTime,
          endTime: details?.endTime,
        })
        if (resumeAt > 0) event.target.seekTo(resumeAt, true)
        checkpointReadyRef.current = true
      }}
      onStateChange={(event) => {
        // YouTube iframe API: ended=0, playing=1, paused=2.
        if (event.data === 1) {
          playbackEndedRef.current = false
          stopInterval()
          intervalRef.current = setInterval(() => persist(), 10_000)
        } else if (event.data === 2) {
          stopInterval()
          persist()
        } else if (event.data === 0) {
          playbackEndedRef.current = true
          stopInterval()
          persist(true)
        }
      }}
    />
  )
}

function VideoActivity({ activity, course, orgUuid }: VideoActivityProps) {
  const org = useOrg() as any
  const resolvedOrgUuid = orgUuid || org?.org_uuid
  const [videoId, setVideoId] = React.useState('')
  const [noSkip, setNoSkip] = React.useState(false)

  React.useEffect(() => {
    let alive = true
    if (course?.course_uuid) {
      getNoSkipCourses().then((set) => {
        if (alive) setNoSkip(set.has(course.course_uuid))
      })
    }
    return () => {
      alive = false
    }
  }, [course?.course_uuid])

  React.useEffect(() => {
    if (activity?.content?.uri) {
      var getYouTubeID = require('get-youtube-id')
      setVideoId(getYouTubeID(activity.content.uri))
    }
  }, [activity, org])

  // Prefer adaptive HLS once transcoding is ready; otherwise fall back to the
  // (optimized) progressive MP4 so playback always works.
  const hlsReady = isActivityHlsReady(activity)

  const getVideoSource = () =>
    resolveActivityVideoSource({
      hlsReady,
      orgUuid: resolvedOrgUuid,
      courseUuid: course?.course_uuid,
      activityUuid: activity.activity_uuid,
      filename: activity.content?.filename,
    })

  return (
    <div className="w-full max-w-full px-0 sm:px-4">
      {activity && (
        <>
          {activity.activity_sub_type === 'SUBTYPE_VIDEO_HOSTED' && (
            <div className="my-0 sm:my-3 md:my-5 w-full">
              <div className="relative w-full aspect-video sm:rounded-lg overflow-hidden ring-0 sm:ring-1 sm:ring-gray-200/10 sm:dark:ring-gray-700/20 shadow-none">
                {(() => {
                  const { src, isHls } = getVideoSource()
                  const thumbnails = isHls
                    ? resolveHlsThumbnails(activity, {
                        orgUuid: resolvedOrgUuid,
                        courseUuid: course?.course_uuid,
                        activityUuid: activity.activity_uuid,
                      })
                    : null
                  // Always compute the progressive MP4 URL so the player can fall
                  // back to it if the HLS source errors (partial/broken transcode).
                  const fallbackSrc = isHls
                    ? resolveActivityVideoSource({
                        hlsReady: false,
                        orgUuid: resolvedOrgUuid,
                        courseUuid: course?.course_uuid,
                        activityUuid: activity.activity_uuid,
                        filename: activity.content?.filename,
                      }).src
                    : undefined
                  // Ready AI caption tracks attach to either source (HLS or MP4).
                  const captions = resolveActivityCaptions(activity, {
                    orgUuid: resolvedOrgUuid,
                    courseUuid: course?.course_uuid,
                    activityUuid: activity.activity_uuid,
                  })
                  return src ? (
                    <LearnHousePlayer
                      key={src}
                      src={src}
                      isHls={isHls}
                      fallbackSrc={fallbackSrc}
                      details={activity.details}
                      thumbnails={thumbnails}
                      captions={captions}
                      noSkip={noSkip}
                      playbackProgress={
                        activity.content?.filename
                          ? {
                              activityUuid: activity.activity_uuid,
                              videoKey: activity.activity_uuid,
                              sourceId: activity.content.filename,
                            }
                          : undefined
                      }
                    />
                  ) : null
                })()}
              </div>
            </div>
          )}
          {activity.activity_sub_type === 'SUBTYPE_VIDEO_YOUTUBE' && (
            <div className="my-0 sm:my-3 md:my-5 w-full">
              <div className="relative w-full aspect-video sm:rounded-lg overflow-hidden ring-0 sm:ring-1 sm:ring-gray-200/10 sm:dark:ring-gray-700/20 shadow-none">
                <PersistedYouTubePlayer
                  videoId={videoId}
                  activityUuid={activity.activity_uuid}
                  details={activity.details}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default VideoActivity

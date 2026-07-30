import { getAPIUrl } from '@services/config/config'

export interface VideoProgressIdentity {
  activityUuid: string
  videoKey: string
  sourceId: string
}

export interface VideoProgressRecord {
  activity_uuid: string
  video_key: string
  source_id: string
  position_seconds: number
  duration_seconds: number | null
  update_date: string | null
}

export interface SaveVideoProgressOptions {
  keepalive?: boolean
}

const progressUrl = ({ activityUuid, videoKey, sourceId }: VideoProgressIdentity) => {
  const params = new URLSearchParams({
    video_key: videoKey,
    source_id: sourceId,
  })
  return `${getAPIUrl()}trail/video-progress/${encodeURIComponent(activityUuid)}?${params.toString()}`
}

export async function getVideoProgress(
  identity: VideoProgressIdentity
): Promise<VideoProgressRecord | null> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 2_000)
  try {
    const response = await fetch(progressUrl(identity), {
      method: 'GET',
      credentials: 'include',
      signal: controller.signal,
    })
    if (!response.ok) return null
    return (await response.json()) as VideoProgressRecord
  } catch {
    // Playback must remain available if progress persistence is unavailable.
    return null
  } finally {
    clearTimeout(timeout)
  }
}

export async function saveVideoProgress(
  identity: VideoProgressIdentity,
  positionSeconds: number,
  durationSeconds: number | null,
  options: SaveVideoProgressOptions = {}
): Promise<VideoProgressRecord | null> {
  if (!Number.isFinite(positionSeconds) || positionSeconds < 0) return null

  try {
    const response = await fetch(
      `${getAPIUrl()}trail/video-progress/${encodeURIComponent(identity.activityUuid)}`,
      {
        method: 'PUT',
        credentials: 'include',
        keepalive: options.keepalive,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_key: identity.videoKey,
          source_id: identity.sourceId,
          position_seconds: positionSeconds,
          duration_seconds:
            durationSeconds != null && Number.isFinite(durationSeconds)
              ? durationSeconds
              : null,
        }),
      }
    )
    if (!response.ok) return null
    return (await response.json()) as VideoProgressRecord
  } catch {
    // Checkpoints are fail-soft and must never interrupt the player.
    return null
  }
}

/**
 * Return the point a player should restore after metadata is available.
 * Videos that are effectively finished restart from the beginning on replay.
 */
export function resolveResumePosition({
  savedPosition,
  duration,
  startTime = 0,
  endTime,
}: {
  savedPosition: number
  duration: number
  startTime?: number
  endTime?: number | null
}): number {
  const lowerBound = Math.max(0, startTime)
  const upperBound =
    endTime != null && endTime > lowerBound
      ? Math.min(endTime, duration || endTime)
      : duration

  if (!Number.isFinite(savedPosition) || savedPosition < 3) return lowerBound
  if (!Number.isFinite(upperBound) || upperBound <= lowerBound) {
    return Math.max(lowerBound, savedPosition)
  }

  // Avoid reopening at the final frame and immediately ending again.
  if (upperBound - savedPosition <= 5 || savedPosition / upperBound >= 0.98) {
    return lowerBound
  }

  return Math.min(Math.max(savedPosition, lowerBound), upperBound)
}

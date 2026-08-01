'use client' // Error components must be Client Components

import * as Sentry from '@sentry/nextjs'
import { RotateCcw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function Error({
  error,
  reset,
}: {
  error: Error
  reset: () => void
}) {
  const router = useRouter()

  useEffect(() => {
    console.error(error)
    if (Sentry.isInitialized()) {
      Sentry.captureException(error, {
        tags: { area: 'protected_course_activity' },
      })
    }

    // Check if it's a Server Action version mismatch error
    if (error.message.includes('Failed to find Server Action') || 
        error.message.includes('older or newer deployment')) {
      window.location.reload()
      return
    }

    // Recover once automatically from a route/render race. A session-scoped
    // guard prevents a genuinely persistent code problem from reloading in a
    // loop while still keeping transient auth failures invisible to learners.
    const recoveryKey = `lh:activity-recovery:${window.location.pathname}`
    const previousAttempt = Number(sessionStorage.getItem(recoveryKey) || 0)
    if (Date.now() - previousAttempt > 30_000) {
      sessionStorage.setItem(recoveryKey, String(Date.now()))
      const timer = window.setTimeout(() => {
        reset()
        router.refresh()
      }, 300)
      return () => window.clearTimeout(timer)
    }
  }, [error, reset, router])

  return (
    <div className="max-w-xl mx-auto my-16 bg-white rounded-2xl border border-gray-200/80 shadow-sm p-8 text-center">
      <div className="mx-auto w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mb-4">
        <RotateCcw className="text-gray-600" size={22} />
      </div>
      <h1 className="text-xl font-semibold text-gray-900 mb-2">Reconnecting your course</h1>
      <p className="text-sm text-gray-500 mb-6">Your progress is safe. Continue to reload this lesson.</p>
      <button
        type="button"
        onClick={() => {
          sessionStorage.removeItem(`lh:activity-recovery:${window.location.pathname}`)
          reset()
          router.refresh()
        }}
        className="inline-flex items-center justify-center px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-semibold hover:bg-gray-800 transition-colors"
      >
        Continue
      </button>
    </div>
  )
}

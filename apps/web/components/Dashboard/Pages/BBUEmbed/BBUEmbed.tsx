'use client'
import React from 'react'
import { getAPIUrl } from '@services/config/config'

/**
 * Embeds an API-served BBU admin page (Operations Console, Cert Manager) inside
 * the dashboard shell as a same-origin iframe, so it renders as part of the app
 * instead of opening in a separate browser tab. Same-origin => the session
 * cookie flows automatically, so the page authenticates as the logged-in admin.
 */
export default function BBUEmbed({ path, title }: { path: string; title: string }) {
  const src = `${getAPIUrl()}${path}`
  return (
    <div className="w-full h-[calc(100vh-40px)] px-3 py-3">
      <iframe
        src={src}
        title={title}
        className="w-full h-full rounded-xl border border-neutral-200 bg-white shadow-sm"
        style={{ border: 0 }}
      />
    </div>
  )
}

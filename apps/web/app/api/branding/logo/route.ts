import { NextResponse } from 'next/server'
import { getBrandProfileForHostname } from '@services/branding/brandProfile'

export async function GET(request: Request) {
  const profile = getBrandProfileForHostname(request.headers.get('host') || new URL(request.url).hostname)
  if (profile.key !== 'bold') return new NextResponse(null, { status: 404 })

  // Serve the deterministic, alpha-masked circle-only derivative. Keeping the
  // existing endpoint preserves the host-aware branding contract for clients.
  const upstream = await fetch(new URL('/project-bold-emblem.png', request.url), { cache: 'force-cache' })
  if (!upstream.ok) return new NextResponse('Unable to load the official Project BOLD logo', { status: 502 })

  return new NextResponse(await upstream.arrayBuffer(), {
    headers: {
      'Content-Type': upstream.headers.get('content-type') || 'image/png',
      'Cache-Control': 'public, max-age=86400, s-maxage=86400',
    },
  })
}

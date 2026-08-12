import { NextResponse } from 'next/server'
import { getBrandProfileForHostname } from '@services/branding/brandProfile'

export function GET(request: Request) {
  const profile = getBrandProfileForHostname(request.headers.get('host') || new URL(request.url).hostname)
  return NextResponse.json({
    name: profile.displayName,
    short_name: profile.shortName,
    description: profile.description,
    start_url: '/',
    display: 'standalone',
    background_color: profile.colors.paper,
    theme_color: profile.colors.primary,
    icons: [
      { src: profile.faviconPath, sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' },
    ],
  }, {
    headers: { 'Cache-Control': 'public, max-age=300, s-maxage=300' },
  })
}

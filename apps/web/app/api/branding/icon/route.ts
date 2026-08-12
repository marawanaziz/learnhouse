import { NextResponse } from 'next/server'
import { getBrandProfileForHostname } from '@services/branding/brandProfile'

export function GET(request: Request) {
  const profile = getBrandProfileForHostname(request.headers.get('host') || new URL(request.url).hostname)
  const isBold = profile.key === 'bold'
  const background = isBold ? profile.colors.primary : profile.colors.primary
  const foreground = isBold ? profile.colors.paper : '#ffffff'
  const mark = isBold ? '&amp;' : 'BBU'
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="${profile.displayName}"><rect width="128" height="128" rx="24" fill="${background}"/><circle cx="64" cy="64" r="42" fill="none" stroke="${foreground}" stroke-width="5"/><text x="64" y="78" text-anchor="middle" font-family="Arial,sans-serif" font-size="${isBold ? 48 : 26}" font-weight="700" fill="${foreground}">${mark}</text></svg>`
  return new NextResponse(svg, {
    headers: {
      'Content-Type': 'image/svg+xml; charset=utf-8',
      'Cache-Control': 'public, max-age=300, s-maxage=300',
    },
  })
}

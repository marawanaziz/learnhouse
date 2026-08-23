import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { NextResponse } from 'next/server'
import { getBrandProfileForHostname } from '@services/branding/brandProfile'

export async function GET(request: Request) {
  const profile = getBrandProfileForHostname(request.headers.get('host') || new URL(request.url).hostname)
  if (profile.key !== 'bold') return new NextResponse(null, { status: 404 })

  // Serve the deterministic, alpha-masked circle-only derivative.
  let logo: Uint8Array
  try {
    logo = Uint8Array.from(await readFile(join(process.cwd(), 'public', 'project-bold-emblem.png')))
  } catch {
    return new NextResponse('Unable to load the official Project BOLD logo', { status: 502 })
  }
  const body = logo.buffer.slice(logo.byteOffset, logo.byteOffset + logo.byteLength) as ArrayBuffer

  return new NextResponse(body, {
    headers: {
      'Content-Type': 'image/png',
      'Cache-Control': 'public, max-age=86400, s-maxage=86400',
    },
  })
}

import { NextRequest, NextResponse } from 'next/server'
import { getBackendUrl } from '@services/config/config'
import {
  buildBackendMediaUrl,
  pickMediaRequestHeaders,
  pickMediaResponseHeaders,
} from '@lib/media/mediaProxy'

export const dynamic = 'force-dynamic'
export const fetchCache = 'force-no-store'

async function proxyContent(request: NextRequest): Promise<Response> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  try {
    const backendUrl = buildBackendMediaUrl(
      getBackendUrl(),
      request.nextUrl.pathname,
      request.nextUrl.search,
    )
    const headers = pickMediaRequestHeaders(request.headers)
    const controller = new AbortController()
    timeoutId = setTimeout(() => controller.abort(), 120_000)
    const backendResponse = await fetch(backendUrl, {
      method: request.method,
      headers,
      signal: controller.signal,
    })
    clearTimeout(timeoutId)

    // Node's fetch transparently decompresses responses. Do not leave a
    // compressed Content-Length attached to the decompressed stream.
    const responseHeaders = pickMediaResponseHeaders(
      backendResponse.headers,
      backendResponse.headers.has('content-encoding'),
    )

    return new Response(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: responseHeaders,
    })
  } catch (error: any) {
    if (timeoutId) clearTimeout(timeoutId)
    if (error?.name === 'AbortError') {
      return NextResponse.json({ error: 'Media request timeout' }, { status: 504 })
    }
    if (error instanceof Error && /Invalid media (path|query)/.test(error.message)) {
      return NextResponse.json({ error: 'Invalid media path' }, { status: 400 })
    }
    console.error(`Failed to proxy media request: ${error?.message || error}`)
    return NextResponse.json({ error: 'Media backend unavailable' }, { status: 502 })
  }
}

export async function GET(request: NextRequest) {
  return proxyContent(request)
}

export async function HEAD(request: NextRequest) {
  return proxyContent(request)
}

import { NextRequest, NextResponse } from 'next/server'
import { getBackendUrl } from '@services/config/config'
import { buildBackendMediaUrl } from '@lib/media/mediaProxy'

export const dynamic = 'force-dynamic'
export const fetchCache = 'force-no-store'

const SKIP_REQUEST_HEADERS = new Set(['host', 'connection', 'keep-alive', 'transfer-encoding'])
const SKIP_RESPONSE_HEADERS = new Set(['connection', 'keep-alive', 'transfer-encoding', 'content-encoding'])

async function proxyContent(request: NextRequest): Promise<Response> {
  const backendUrl = buildBackendMediaUrl(
    getBackendUrl(),
    request.nextUrl.pathname,
    request.nextUrl.search,
  )
  const headers = new Headers()

  // Forward cookies, Authorization, Range, conditional requests, and the
  // browser's Accept headers so authenticated lesson media behaves like the
  // existing /api/v1 same-origin proxy.
  request.headers.forEach((value, key) => {
    if (!SKIP_REQUEST_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value)
    }
  })

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 120_000)

  try {
    const backendResponse = await fetch(backendUrl, {
      method: request.method,
      headers,
      signal: controller.signal,
    })
    clearTimeout(timeoutId)

    const wasCompressed = backendResponse.headers.has('content-encoding')
    const responseHeaders = new Headers()
    backendResponse.headers.forEach((value, key) => {
      const lowerKey = key.toLowerCase()
      if (SKIP_RESPONSE_HEADERS.has(lowerKey)) {
        return
      }
      // Node's fetch transparently decompresses responses. Do not leave a
      // compressed Content-Length attached to the decompressed stream.
      if (lowerKey === 'content-length' && wasCompressed) {
        return
      }
      responseHeaders.append(key, value)
    })

    return new Response(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: responseHeaders,
    })
  } catch (error: any) {
    clearTimeout(timeoutId)
    if (error?.name === 'AbortError') {
      return NextResponse.json({ error: 'Media request timeout' }, { status: 504 })
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

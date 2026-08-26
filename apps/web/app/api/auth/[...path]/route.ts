import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createHash } from 'node:crypto'
import * as Sentry from '@sentry/nextjs'
import { getServerAPIUrl } from '@services/config/config'
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  ACCESS_TOKEN_MAX_AGE,
  REFRESH_TOKEN_MAX_AGE,
  clearLegacyAuthCookies,
  getCookieOptions,
} from '@services/auth/cookies'

const REFRESH_COALESCE_WINDOW_MS = 5_000

type ResponseSnapshot = {
  body: ArrayBuffer
  headers: [string, string][]
  status: number
  statusText: string
}

const inFlightRefreshes = new Map<
  string,
  { promise: Promise<ResponseSnapshot>; expiresAt: number }
>()

function getBackendApiUrl(): string {
  return getServerAPIUrl().replace(/\/+$/, '')
}

async function snapshotResponse(response: Response): Promise<ResponseSnapshot> {
  return {
    body: await response.arrayBuffer(),
    headers: Array.from(response.headers.entries()),
    status: response.status,
    statusText: response.statusText,
  }
}

function restoreResponse(snapshot: ResponseSnapshot): Response {
  return new Response(snapshot.body.slice(0), {
    headers: snapshot.headers,
    status: snapshot.status,
    statusText: snapshot.statusText,
  })
}

async function coalescedRefresh(
  refreshToken: string,
  request: () => Promise<Response>,
): Promise<Response> {
  const key = createHash('sha256').update(refreshToken).digest('hex')
  const existing = inFlightRefreshes.get(key)
  if (existing && existing.expiresAt > Date.now()) {
    return restoreResponse(await existing.promise)
  }

  const promise = request().then(snapshotResponse)
  const entry = {
    promise,
    expiresAt: Date.now() + REFRESH_COALESCE_WINDOW_MS,
  }
  inFlightRefreshes.set(key, entry)
  setTimeout(() => {
    if (inFlightRefreshes.get(key) === entry) {
      inFlightRefreshes.delete(key)
    }
  }, REFRESH_COALESCE_WINDOW_MS)

  return restoreResponse(await promise)
}

function reportRefreshFailure(
  request: NextRequest,
  status: number,
  phase: 'validation' | 'rotation',
  error?: unknown,
) {
  const level = status >= 500 || status === 404 || status === 0 ? 'error' : 'warning'
  const details = {
    event: 'auth_refresh_failure',
    phase,
    status,
    host: request.headers.get('host') || 'unknown',
    requestId: request.headers.get('x-railway-request-id') || undefined,
  }

  // Railway parses this as a structured error/warning that can be filtered by
  // `@event:auth_refresh_failure`; Sentry receives the same signal when its DSN
  // is enabled. Never include cookies or tokens in either channel.
  console.error(JSON.stringify({
    level,
    message: 'Authentication session refresh failed',
    ...details,
  }))

  if (Sentry.isInitialized()) {
    Sentry.captureMessage('Authentication session refresh failed', {
      level,
      tags: {
        event: details.event,
        phase,
        status: String(status),
      },
      extra: {
        host: details.host,
        requestId: details.requestId,
        error: error instanceof Error ? error.message : undefined,
      },
    })
  }
}

// Paths that return tokens in response body (relative to /api/v1/auth/)
// `verify-email` auto-signs-in the user on successful email verification, so
// it returns tokens just like login/signup and its cookies must be mirrored.
const TOKEN_RESPONSE_PATHS = ['login', 'refresh', 'oauth', 'signup', 'verify-email']

function shouldExtractTokens(path: string): boolean {
  return TOKEN_RESPONSE_PATHS.some(p => path.startsWith(p))
}

// Decode a JWT payload without verifying the signature. Used purely to read
// the `exp` claim so we can skip a slow backend refresh when the access token
// is still valid. If the backend later rejects the token (revoked, etc.), the
// next API call will 401 and the client will trigger a real refresh.
function decodeJwtExpiryMs(token: string): number | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    // JWT base64url -> base64
    const padded = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padding = padded.length % 4 === 0 ? '' : '='.repeat(4 - (padded.length % 4))
    const json = Buffer.from(padded + padding, 'base64').toString('utf-8')
    const payload = JSON.parse(json)
    if (typeof payload.exp !== 'number') return null
    return payload.exp * 1000
  } catch {
    return null
  }
}

// Skip the backend refresh roundtrip when the cookie token still has plenty
// of life left. Two minutes of headroom keeps us safe against clock skew.
const REFRESH_FAST_PATH_HEADROOM_MS = 2 * 60 * 1000

function clearAuthCookies(response: NextResponse, request: NextRequest) {
  const isSecure = request.nextUrl.protocol === 'https:'
  const securePart = isSecure ? '; Secure' : ''

  clearLegacyAuthCookies(response, request)

  response.headers.append('Set-Cookie', `${ACCESS_TOKEN_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax${securePart}`)
  response.headers.append('Set-Cookie', `${REFRESH_TOKEN_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax${securePart}`)
  response.headers.append('Set-Cookie', `LH_session=; Path=/; Max-Age=0; SameSite=Lax${securePart}`)
}

async function proxyRequest(
  request: NextRequest,
  method: string
): Promise<NextResponse> {
  // Extract the path after /api/auth/
  const pathSegments = request.nextUrl.pathname.replace('/api/auth/', '')
  const search = request.nextUrl.search

  // Map to backend URL: /api/auth/login -> /api/v1/auth/login
  const backendUrl = `${getBackendApiUrl()}/auth/${pathSegments}${search}`

  // Build headers
  const headers: HeadersInit = {}
  const cookieStore = await cookies()

  // Auth requests are proxied to the backend service, whose Host is internal.
  // Carry the actual public white-label host for host-specific access rules.
  headers['X-LearnHouse-Public-Host'] = request.headers.get('host') || ''

  // Forward content-type
  const contentType = request.headers.get('content-type')
  if (contentType) {
    headers['Content-Type'] = contentType
  }

  // Forward authorization header if present
  const authHeader = request.headers.get('authorization')
  if (authHeader) {
    headers['Authorization'] = authHeader
  }

  // Forward cookies to backend
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)

  // Short-circuit: no refresh token cookie means nothing to refresh
  if (pathSegments === 'refresh' && !refreshToken?.value) {
    return NextResponse.json({ error: 'No refresh token' }, { status: 401 })
  }

  // Fast-path: reuse an access token only after the backend validates it.
  // Decoding `exp` alone is unsafe because password changes and logout revoke
  // otherwise unexpired JWTs; trusting `exp` caused the production login loop.
  if (
    pathSegments === 'refresh'
    && method === 'GET'
    && accessToken?.value
  ) {
    const expiryMs = decodeJwtExpiryMs(accessToken.value)
    if (expiryMs && expiryMs - Date.now() > REFRESH_FAST_PATH_HEADROOM_MS) {
      try {
        const validationResponse = await fetch(`${getBackendApiUrl()}/users/session`, {
          method: 'GET',
          headers: { Authorization: `Bearer ${accessToken.value}` },
          cache: 'no-store',
        })
        if (validationResponse.ok) {
          const response = NextResponse.json({
            access_token: accessToken.value,
            expiry: expiryMs,
          })
          response.cookies.set('LH_session', '1', {
            ...getCookieOptions(request),
            httpOnly: false,
            maxAge: REFRESH_TOKEN_MAX_AGE,
          })
          // Append legacy-domain expirations after setting the canonical
          // host-only marker; NextResponse's cookie manager otherwise
          // replaces raw Set-Cookie entries with the same names.
          clearLegacyAuthCookies(response, request)
          return response
        }

        if (validationResponse.status >= 500) {
          reportRefreshFailure(request, validationResponse.status, 'validation')
          return NextResponse.json(
            { error: 'Session validation is temporarily unavailable' },
            { status: 503 },
          )
        }
        // A revoked access token can still have a valid refresh token. Fall
        // through to rotation, which validates that refresh token.
      } catch (error) {
        reportRefreshFailure(request, 0, 'validation', error)
        return NextResponse.json(
          { error: 'Session validation is temporarily unavailable' },
          { status: 503 },
        )
      }
    }
  }

  // Handle logout locally — clear cookies and return 200
  // Try backend invalidation but don't fail if it errors
  if (pathSegments === 'logout' || pathSegments.endsWith('/logout')) {
    // Best-effort backend token invalidation
    try {
      const logoutHeaders: HeadersInit = {}
      if (refreshToken?.value) {
        logoutHeaders['Cookie'] = `${REFRESH_TOKEN_COOKIE}=${refreshToken.value}`
      }
      await fetch(`${getBackendApiUrl()}/auth/logout`, {
        method: 'POST',
        headers: logoutHeaders,
        signal: AbortSignal.timeout(3000),
      }).catch(() => {})
    } catch {
      // Backend logout failed — that's fine, cookies are cleared below
    }

    const response = NextResponse.json({ ok: true })
    clearAuthCookies(response, request)
    return response
  }

  const cookieParts: string[] = []
  if (accessToken?.value) {
    cookieParts.push(`${ACCESS_TOKEN_COOKIE}=${accessToken.value}`)
  }
  if (refreshToken?.value) {
    cookieParts.push(`${REFRESH_TOKEN_COOKIE}=${refreshToken.value}`)
  }
  if (cookieParts.length > 0) {
    headers['Cookie'] = cookieParts.join('; ')
  }

  // Get request body for non-GET requests
  let body: BodyInit | undefined
  if (method !== 'GET' && method !== 'HEAD') {
    if (contentType?.includes('application/json')) {
      body = JSON.stringify(await request.json())
    } else if (contentType?.includes('application/x-www-form-urlencoded')) {
      const formData = await request.formData()
      const params = new URLSearchParams()
      formData.forEach((value, key) => {
        params.append(key, value.toString())
      })
      body = params.toString()
    } else if (contentType?.includes('multipart/form-data')) {
      delete headers['Content-Type']
      body = await request.formData()
    } else {
      body = await request.text()
    }
  }

  // Coalesce near-simultaneous refreshes from multiple tabs/components. The
  // backend uses one-time refresh tokens, so sending the same token twice can
  // otherwise be mistaken for replay and revoke every session for the user.
  let backendResponse: Response
  try {
    const makeRequest = () => fetch(backendUrl, {
      method,
      headers,
      body,
      cache: 'no-store',
    })
    backendResponse = pathSegments === 'refresh' && refreshToken?.value
      ? await coalescedRefresh(refreshToken.value, makeRequest)
      : await makeRequest()
  } catch (error) {
    if (pathSegments === 'refresh') {
      reportRefreshFailure(request, 0, 'rotation', error)
    }
    return NextResponse.json(
      { error: 'Authentication service is temporarily unavailable' },
      { status: 503 },
    )
  }

  if (pathSegments === 'refresh' && !backendResponse.ok) {
    reportRefreshFailure(request, backendResponse.status, 'rotation')
  }

  // Get response data
  const responseContentType = backendResponse.headers.get('content-type')
  let responseData: any
  let responseBody: BodyInit

  if (responseContentType?.includes('application/json')) {
    responseData = await backendResponse.json()
    responseBody = JSON.stringify(responseData)
  } else {
    responseBody = await backendResponse.text()
  }

  // Create response
  const response = new NextResponse(responseBody, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
  })

  if (pathSegments === 'refresh' && backendResponse.status === 401) {
    clearAuthCookies(response, request)
  }

  // Copy relevant headers
  if (responseContentType) {
    response.headers.set('content-type', responseContentType)
  }

  // Extract and set auth cookies if this is a token-returning endpoint
  if (backendResponse.ok && shouldExtractTokens(pathSegments) && responseData) {
    const cookieOptions = getCookieOptions(request)

    // Handle different response structures
    const tokens = responseData.tokens || responseData

    if (tokens.access_token) {
      response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, {
        ...cookieOptions,
        maxAge: ACCESS_TOKEN_MAX_AGE,
      })
    }

    if (tokens.refresh_token) {
      response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, {
        ...cookieOptions,
        maxAge: REFRESH_TOKEN_MAX_AGE,
      })
    }

    // Set a non-httpOnly marker so the client knows a session exists
    // without making a network request (the actual tokens stay httpOnly)
    if (tokens.access_token || tokens.refresh_token) {
      response.cookies.set('LH_session', '1', {
        ...cookieOptions,
        httpOnly: false,
        maxAge: REFRESH_TOKEN_MAX_AGE,
      })
    }

    // Remove former parent-domain sessions after setting canonical host-only
    // cookies. Appending last preserves both domain-scoped expirations and the
    // new cookies in NextResponse's final Set-Cookie header.
    clearLegacyAuthCookies(response, request)
  }

  return response
}

export async function GET(request: NextRequest) {
  return proxyRequest(request, 'GET')
}

export async function POST(request: NextRequest) {
  return proxyRequest(request, 'POST')
}

export async function PUT(request: NextRequest) {
  return proxyRequest(request, 'PUT')
}

export async function PATCH(request: NextRequest) {
  return proxyRequest(request, 'PATCH')
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request, 'DELETE')
}

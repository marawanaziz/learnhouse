import { cookies } from 'next/headers'
import { getServerAPIUrl } from '@services/config/config'

// Cookie names (must match the API routes)
const ACCESS_TOKEN_COOKIE = 'LH_access'

// Types matching the client-side session structure
export interface Session {
  user: any | undefined
  roles?: string[] | undefined
  tokens?: {
    access_token?: string | undefined
    refresh_token?: string | undefined
    expiry?: number | undefined
  } | undefined
}

/**
 * Get server-side session by reading tokens from cookies.
 *
 * Since cookies are now set by Next.js API routes (same origin), they are
 * reliably readable by the Next.js server.
 *
 * IMPORTANT: Server Components cannot persist a rotated refresh cookie onto
 * the browser response. Refreshing here would consume the backend's one-time
 * refresh token while leaving the browser with the old token, which turns the
 * next refresh into a replay. Only `/api/auth/refresh` may rotate tokens.
 */
export async function getServerSession(): Promise<Session | null> {
  try {
    const cookieStore = await cookies()

    // Try to get access token directly
    const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)

    if (accessToken?.value) {
      // Verify the token is valid by fetching session from backend
      const sessionResponse = await fetch(`${getServerAPIUrl()}users/session`, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${accessToken.value}`,
        },
        cache: 'no-store',
      })

      if (sessionResponse.ok) {
        const sessionData = await sessionResponse.json()
        return {
          user: sessionData.user,
          roles: sessionData.roles,
          tokens: {
            access_token: accessToken.value,
          },
        }
      }

      // The client-side session provider will refresh through the same-origin
      // route and mirror both rotated cookies. Metadata must fail soft until
      // that completes instead of consuming the refresh token here.
      return null
    }

    return null
  } catch (error) {
    console.error('[SERVER_SESSION] Error:', error)
    return null
  }
}

/**
 * Get access token from cookies for server-side API calls.
 * This is a lightweight alternative when you only need the token.
 */
export async function getServerAccessToken(): Promise<string | null> {
  try {
    const cookieStore = await cookies()

    // Try access token first
    const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)
    if (accessToken?.value) {
      return accessToken.value
    }

    // Refresh-token rotation must stay in the cookie-setting route handler.
    return null
  } catch (error) {
    console.error('[SERVER_SESSION] Error getting access token:', error)
    return null
  }
}

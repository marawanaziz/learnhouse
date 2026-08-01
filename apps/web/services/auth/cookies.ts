import { NextRequest, NextResponse } from 'next/server'
import { isSubdomainOf, isSameHost, isLocalhost, stripPort } from '@services/utils/ts/hostUtils'
import { getConfig } from '@services/config/config'

export const ACCESS_TOKEN_COOKIE = 'LH_access'
export const REFRESH_TOKEN_COOKIE = 'LH_refresh'
export const ACCESS_TOKEN_MAX_AGE = 8 * 60 * 60 // 8 hours
export const REFRESH_TOKEN_MAX_AGE = 30 * 24 * 60 * 60 // 30 days

export function getDomainFromRequest(request: NextRequest): { domain: string; topDomain: string } {
  const envDomain = getConfig('NEXT_PUBLIC_LEARNHOUSE_DOMAIN')
  const envTopDomain = getConfig('NEXT_PUBLIC_LEARNHOUSE_TOP_DOMAIN')
  if (envDomain) {
    return {
      domain: envDomain,
      topDomain: stripPort(envTopDomain || envDomain),
    }
  }

  const cookieDomain = request.cookies.get('LH_frontend_domain')?.value
  const cookieTopDomain = request.cookies.get('LH_top_domain')?.value
  if (cookieDomain) {
    return {
      domain: cookieDomain,
      topDomain: stripPort(cookieTopDomain || cookieDomain),
    }
  }

  return { domain: 'localhost', topDomain: 'localhost' }
}

export function getCookieDomain(request: NextRequest): string | undefined {
  // Tenancy is the source of truth: in single mode cookies are always
  // host-only on whatever Host the request arrived with, regardless of
  // whether that's localhost or a self-hosted VPS hostname. In multi mode
  // we use the configured top domain so subdomains share the session.
  const tenancy = request.cookies.get('LH_tenancy')?.value || 'single'
  if (tenancy === 'single') return undefined

  const host = request.headers.get('host')
  const { domain, topDomain } = getDomainFromRequest(request)

  if (isLocalhost(host)) return undefined
  if (topDomain === 'localhost') return undefined
  if (isSubdomainOf(host, domain) || isSameHost(host, domain)) {
    return `.${topDomain}`
  }
  // Custom (per-org) domain in multi mode → host-only.
  return undefined
}

export function getCookieOptions(request: NextRequest) {
  const isSecure = request.nextUrl.protocol === 'https:'
  const domain = getCookieDomain(request)
  return {
    httpOnly: true,
    secure: isSecure,
    sameSite: 'lax' as const,
    path: '/',
    ...(domain ? { domain } : {}),
  }
}

export function getLegacyCookieDomains(request: NextRequest): string[] {
  const host = (request.headers.get('host') || '').split(':')[0].toLowerCase()
  const configuredDomain = getCookieDomain(request)?.replace(/^\./, '')
  const { domain, topDomain } = getDomainFromRequest(request)
  const candidates = new Set<string>([
    configuredDomain || '',
    domain,
    topDomain,
  ])

  // Domain cutovers can leave a parent-domain cookie beside a newer host-only
  // cookie with the same name. Derive that valid parent scope so both can be
  // expired without hard-coding a tenant hostname.
  const hostParts = host.split('.').filter(Boolean)
  if (hostParts.length >= 3) {
    candidates.add(hostParts.slice(1).join('.'))
  }

  return Array.from(candidates).filter(candidate => (
    candidate
    && candidate !== 'localhost'
    && (host === candidate || host.endsWith(`.${candidate}`))
  ))
}

export function clearLegacyAuthCookies(response: NextResponse, request: NextRequest) {
  const isSecure = request.nextUrl.protocol === 'https:'
  const securePart = isSecure ? '; Secure' : ''

  for (const domain of getLegacyCookieDomains(request)) {
    response.headers.append('Set-Cookie', `${ACCESS_TOKEN_COOKIE}=; Path=/; Domain=.${domain}; Max-Age=0; HttpOnly; SameSite=Lax${securePart}`)
    response.headers.append('Set-Cookie', `${REFRESH_TOKEN_COOKIE}=; Path=/; Domain=.${domain}; Max-Age=0; HttpOnly; SameSite=Lax${securePart}`)
    response.headers.append('Set-Cookie', `LH_session=; Path=/; Domain=.${domain}; Max-Age=0; SameSite=Lax${securePart}`)
  }
}

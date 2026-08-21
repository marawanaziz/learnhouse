export const MEDIA_ROUTE_PREFIX = '/content'

/**
 * Content files are addressed by their stored path under /content. The path
 * is intentionally same-origin in the browser; this predicate keeps the
 * Next middleware from treating it as a tenant page.
 */
export function isMediaRoute(pathname: string): boolean {
  return pathname === MEDIA_ROUTE_PREFIX || pathname.startsWith(`${MEDIA_ROUTE_PREFIX}/`)
}

export function buildBackendMediaUrl(
  backendUrl: string,
  pathname: string,
  search = '',
): string {
  if (!isMediaRoute(pathname)) {
    throw new Error(`Not a media route: ${pathname}`)
  }

  return `${backendUrl.replace(/\/+$/, '')}${pathname}${search}`
}

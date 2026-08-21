export const MEDIA_ROUTE_PREFIX = '/content'

const MAX_PATH_DECODE_PASSES = 8

// These are the only request headers needed to authorize, range, validate,
// and negotiate a media response. In particular, do not forward browser
// routing/proxy headers to the configured backend origin.
export const MEDIA_REQUEST_HEADERS = [
  'accept',
  'authorization',
  'cookie',
  'if-match',
  'if-none-match',
  'if-modified-since',
  'if-unmodified-since',
  'if-range',
  'range',
] as const

export const MEDIA_RESPONSE_HEADERS = [
  'accept-ranges',
  'cache-control',
  'content-disposition',
  'content-length',
  'content-range',
  'content-type',
  'etag',
  'last-modified',
] as const

const ENCODED_SEPARATOR = /%2f|%5c/i
const URI_SCHEME = /^[a-z][a-z\d+.-]*:/i

function hasControlCharacters(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code <= 0x1f || code === 0x7f) return true
  }
  return false
}

/**
 * Content files are addressed by their stored path under /content. The path
 * is intentionally same-origin in the browser; this predicate keeps the
 * Next middleware from treating it as a tenant page.
 */
export function isMediaRoute(pathname: string): boolean {
  return pathname === MEDIA_ROUTE_PREFIX || pathname.startsWith(`${MEDIA_ROUTE_PREFIX}/`)
}

function decodeMediaPath(pathname: string): string {
  let decoded = pathname

  for (let pass = 0; pass < MAX_PATH_DECODE_PASSES; pass += 1) {
    if (ENCODED_SEPARATOR.test(decoded)) {
      throw new Error('Invalid media path')
    }

    let next: string
    try {
      next = decodeURIComponent(decoded)
    } catch {
      throw new Error('Invalid media path')
    }

    if (next === decoded) return decoded
    decoded = next
  }

  // A path that still changes after the bounded decode loop is deliberately
  // rejected rather than partially normalized.
  try {
    if (decodeURIComponent(decoded) !== decoded) {
      throw new Error('Path encoding too deep')
    }
  } catch {
    throw new Error('Invalid media path')
  }
  return decoded
}

/**
 * Validate and repeatedly decode a browser media path before proxying it.
 * The returned value is a normalized, absolute /content path and never an
 * absolute URL or a path outside the media namespace.
 */
export function validateMediaPath(pathname: string): string {
  if (typeof pathname !== 'string' || !isMediaRoute(pathname) || pathname === MEDIA_ROUTE_PREFIX) {
    throw new Error('Invalid media path')
  }
  if (pathname.includes('\\') || hasControlCharacters(pathname)) {
    throw new Error('Invalid media path')
  }

  const decoded = decodeMediaPath(pathname)
  if (
    !isMediaRoute(decoded)
    || decoded === MEDIA_ROUTE_PREFIX
    || decoded.startsWith('//')
    || URI_SCHEME.test(decoded)
    || decoded.includes('\\')
    || hasControlCharacters(decoded)
  ) {
    throw new Error('Invalid media path')
  }

  const segments = decoded.slice(`${MEDIA_ROUTE_PREFIX}/`.length).split('/')
  if (
    segments.length === 0
    || segments.some((segment) => (
      !segment
      || segment === '.'
      || segment === '..'
      || URI_SCHEME.test(segment)
    ))
  ) {
    throw new Error('Invalid media path')
  }
  return decoded
}

export function pickMediaRequestHeaders(source: Headers): Headers {
  const headers = new Headers()
  for (const name of MEDIA_REQUEST_HEADERS) {
    const value = source.get(name)
    if (value !== null) headers.set(name, value)
  }
  return headers
}

export function pickMediaResponseHeaders(source: Headers, wasCompressed = false): Headers {
  const headers = new Headers()
  for (const name of MEDIA_RESPONSE_HEADERS) {
    const value = source.get(name)
    if (value === null) continue
    if (name === 'content-length' && (wasCompressed || !/^\d+$/.test(value))) continue
    headers.set(name, value)
  }
  return headers
}

export function buildBackendMediaUrl(
  backendUrl: string,
  pathname: string,
  search = '',
): string {
  const validatedPath = validateMediaPath(pathname)
  if (typeof search !== 'string' || hasControlCharacters(search)) {
    throw new Error('Invalid media query')
  }

  let backendOrigin: URL
  try {
    backendOrigin = new URL(backendUrl)
  } catch {
    throw new Error('Invalid media backend origin')
  }
  if (
    !['http:', 'https:'].includes(backendOrigin.protocol)
    || !backendOrigin.hostname
    || backendOrigin.username
    || backendOrigin.password
  ) {
    throw new Error('Invalid media backend origin')
  }

  // Build from the fixed configured origin, never by interpreting request
  // input as a base URL. Configured backend path/query values are discarded.
  const target = new URL(validatedPath, backendOrigin.origin)
  if (search) target.search = search.startsWith('?') ? search : `?${search}`
  return target.toString()
}

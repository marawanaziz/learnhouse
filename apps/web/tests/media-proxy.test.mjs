import { describe, expect, test } from 'bun:test'

import {
  buildBackendMediaUrl,
  isMediaRoute,
  MEDIA_REQUEST_HEADERS,
  MEDIA_RESPONSE_HEADERS,
  pickMediaRequestHeaders,
  pickMediaResponseHeaders,
  validateMediaPath,
} from '../lib/media/mediaProxy.ts'

const assetPath = '/content/orgs/org_bbu/logos/logo.png'

describe('same-origin media delivery', () => {
  test('keeps the stored media path on the active BOLD host', () => {
    const browserUrl = new URL(assetPath, 'https://learn.boldmovement.org')

    expect(browserUrl.origin).toBe('https://learn.boldmovement.org')
    expect(browserUrl.pathname).toBe(assetPath)
    expect(isMediaRoute(browserUrl.pathname)).toBe(true)
  })

  test('preserves the same media path on the BBU host', () => {
    const browserUrl = new URL(assetPath, 'https://learn.birthandbabyuniversity.com')

    expect(browserUrl.origin).toBe('https://learn.birthandbabyuniversity.com')
    expect(browserUrl.pathname).toBe(assetPath)
    expect(isMediaRoute(browserUrl.pathname)).toBe(true)
  })

  test('proxies the exact content URL class against the fixed backend origin', () => {
    expect(buildBackendMediaUrl(
      'https://learn.birthandbabyuniversity.com/api/v1/',
      assetPath,
      '?download=0',
    )).toBe('https://learn.birthandbabyuniversity.com/content/orgs/org_bbu/logos/logo.png?download=0')
    expect(isMediaRoute('/orgs/bbu/content')).toBe(false)
    expect(() => buildBackendMediaUrl('https://backend.example', 'https://evil.example/x')).toThrow()
  })
})

describe('media proxy request and response headers', () => {
  test('forwards only media authorization, conditional, range, and Accept headers', () => {
    const source = new Headers({
      Accept: 'image/avif,image/webp,image/*',
      Authorization: 'Bearer test',
      Cookie: 'LH_access=token',
      Range: 'bytes=0-31',
      'If-Match': '"a"',
      'If-None-Match': '"b"',
      'If-Modified-Since': 'Wed, 21 Oct 2015 07:28:00 GMT',
      'If-Unmodified-Since': 'Wed, 21 Oct 2015 07:28:00 GMT',
      'If-Range': '"c"',
      Origin: 'https://evil.example',
      Referer: 'https://evil.example/page',
      'Proxy-Connection': 'keep-alive',
      TE: 'trailers',
      Trailer: 'X-Evil',
      Upgrade: 'websocket',
      Host: 'evil.example',
    })
    const forwarded = pickMediaRequestHeaders(source)

    expect([...forwarded.keys()].sort()).toEqual([...MEDIA_REQUEST_HEADERS].sort())
    expect(forwarded.get('range')).toBe('bytes=0-31')
    expect(forwarded.get('authorization')).toBe('Bearer test')
    for (const name of ['origin', 'referer', 'proxy-connection', 'te', 'trailer', 'upgrade', 'host']) {
      expect(forwarded.has(name)).toBe(false)
    }
  })

  test('returns only safe media response headers and validates Content-Length', () => {
    const source = new Headers({
      'Content-Type': 'image/png',
      'Content-Length': '32',
      'Content-Range': 'bytes 0-31/581162',
      'Accept-Ranges': 'bytes',
      ETag: '"asset"',
      'Last-Modified': 'Wed, 21 Oct 2015 07:28:00 GMT',
      'Cache-Control': 'public, max-age=86400',
      'Content-Disposition': 'inline',
      'Set-Cookie': 'secret=1',
      'Access-Control-Allow-Origin': '*',
      Server: 'backend',
      Connection: 'keep-alive',
      'X-Backend': 'secret',
    })
    const forwarded = pickMediaResponseHeaders(source)

    expect([...forwarded.keys()].sort()).toEqual([...MEDIA_RESPONSE_HEADERS].sort())
    for (const name of ['set-cookie', 'access-control-allow-origin', 'server', 'connection', 'x-backend']) {
      expect(forwarded.has(name)).toBe(false)
    }
    expect(pickMediaResponseHeaders(source, true).has('content-length')).toBe(false)
    expect(pickMediaResponseHeaders(new Headers({ 'Content-Length': 'bad' })).has('content-length')).toBe(false)
  })
})

describe('media path validation', () => {
  test('accepts normal, query-bearing, range/conditional URL inputs', () => {
    expect(validateMediaPath(assetPath)).toBe(assetPath)
    expect(buildBackendMediaUrl('https://backend.example', assetPath, '?v=1')).toContain('?v=1')
  })

  test('rejects traversal, repeated encoding, separators, controls, and absolute forms', () => {
    const invalidPaths = [
      '/content/../secret.png',
      '/content/orgs/../secret.png',
      '/content/%2e%2e/secret.png',
      '/content/%252e%252e/secret.png',
      '/content/%252525252525252e%252525252525252e/secret.png',
      '/content/orgs%2Fsecret/logo.png',
      '/content/orgs%5Csecret/logo.png',
      '/content/orgs\\secret/logo.png',
      '/content/orgs/%00logo.png',
      '/content/orgs/%0d%0alogo.png',
      '/content//logo.png',
      '/content/',
      '/content/https:evil.png',
      '//evil.example/content/logo.png',
      'https://evil.example/content/logo.png',
    ]
    for (const path of invalidPaths) {
      expect(() => validateMediaPath(path), path).toThrow()
      expect(() => buildBackendMediaUrl('https://backend.example', path), path).toThrow()
    }
  })
})

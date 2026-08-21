import { describe, expect, test } from 'bun:test'

import {
  buildBackendMediaUrl,
  isMediaRoute,
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

  test('proxies the exact content URL class without rewriting the stored path', () => {
    expect(buildBackendMediaUrl(
      'https://learn.birthandbabyuniversity.com/',
      assetPath,
      '?download=0',
    )).toBe('https://learn.birthandbabyuniversity.com/content/orgs/org_bbu/logos/logo.png?download=0')
    expect(isMediaRoute('/orgs/bbu/content')).toBe(false)
  })
})

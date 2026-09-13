import { test, expect } from 'bun:test'

import { getVideoBlockStreamUrl } from '../services/media/media.ts'

test('BOLD video uses the signed-in learner host', () => {
  const original = globalThis.window
  globalThis.window = {
    location: { hostname: 'learn.boldmovement.org' },
    __RUNTIME_CONFIG__: {
      NEXT_PUBLIC_LEARNHOUSE_DOMAIN: 'learn.birthandbabyuniversity.com',
      NEXT_PUBLIC_LEARNHOUSE_BACKEND_URL: 'https://learn.birthandbabyuniversity.com/',
    },
  }
  try {
    expect(getVideoBlockStreamUrl('o', 'c', 'a', 'b', 'file.mp4'))
      .toBe('/api/v1/stream/block/o/c/a/b/file.mp4')
    globalThis.window.location.hostname = 'learn.birthandbabyuniversity.com'
    expect(getVideoBlockStreamUrl('o', 'c', 'a', 'b', 'file.mp4'))
      .toBe('https://learn.birthandbabyuniversity.com/api/v1/stream/block/o/c/a/b/file.mp4')
  } finally {
    globalThis.window = original
  }
})

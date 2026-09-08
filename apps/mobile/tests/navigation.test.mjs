import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyNavigation, isMainDocumentFailure, SITE_URL } from '../src/navigation.ts';

test('existing website destinations and login remain inside the wrapper', () => {
  for (const path of ['/', '/courses', '/library', '/communities', '/store', '/login?next=%2Fcourses', '/course/example/activity/video#lesson']) {
    assert.equal(classifyNavigation(new URL(path, SITE_URL).href), 'internal');
  }
});
test('external HTTPS, phone, and email have explicit handlers', () => {
  assert.equal(classifyNavigation('https://birthandbabyuniversity.com/'), 'browser');
  assert.equal(classifyNavigation('https://checkout.stripe.com/c/pay/example'), 'browser');
  assert.equal(classifyNavigation('mailto:hello@birthandbabyuniversity.com'), 'device');
  assert.equal(classifyNavigation('tel:+15555555555'), 'device');
});
test('deceptive hosts never become trusted app pages', () => {
  for (const url of ['https://learn.birthandbabyuniversity.com.evil.test/', 'https://evil.test/?next=https://learn.birthandbabyuniversity.com', 'https://learn.birthandbabyuniversity.com:444/']) {
    assert.equal(classifyNavigation(url), 'browser');
  }
  assert.equal(classifyNavigation('https://user:password@learn.birthandbabyuniversity.com'), 'block');
});
test('unsafe and unknown schemes cannot escape into another app or local files', () => {
  for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,test', 'intent://example', 'http://learn.birthandbabyuniversity.com', 'not a url', 'about:blank']) {
    assert.equal(classifyNavigation(url), 'block');
  }
});
test('video iframe navigation stays embedded and cannot launch native apps', () => {
  assert.equal(classifyNavigation('https://www.youtube.com/embed/example', false), 'frame');
  assert.equal(classifyNavigation('https://player.vimeo.com/video/1', false), 'frame');
  assert.equal(classifyNavigation('about:blank', false), 'frame');
  assert.equal(classifyNavigation('tel:+15555555555', false), 'block');
  assert.equal(classifyNavigation('http://example.test', false), 'block');
});
test('only main-document server errors replace the learning screen', () => {
  assert.equal(isMainDocumentFailure(SITE_URL, SITE_URL + '#courses', 503), true);
  assert.equal(isMainDocumentFailure(SITE_URL + 'video.mp4', SITE_URL, 503), false);
  for (const status of [200, 401, 403, 404]) assert.equal(isMainDocumentFailure(SITE_URL, SITE_URL, status), false);
  assert.equal(isMainDocumentFailure('invalid', SITE_URL, 503), false);
});

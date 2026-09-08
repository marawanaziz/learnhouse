export const SITE_URL = 'https://learn.birthandbabyuniversity.com/';
const SITE_ORIGIN = new URL(SITE_URL).origin;

export type NavigationAction = 'internal' | 'frame' | 'browser' | 'device' | 'block';

/** Only the university's exact HTTPS origin may replace the app's main document. */
export function classifyNavigation(value: string, isTopFrame = true): NavigationAction {
  try {
    const url = new URL(value);
    if (url.username || url.password) return 'block';
    if (!isTopFrame) {
      // iOS identifies third-party video iframe navigation; Android lacks this frame metadata.
      return url.protocol === 'https:' || value === 'about:blank' ? 'frame' : 'block';
    }
    if (url.protocol === 'https:') return url.origin === SITE_ORIGIN ? 'internal' : 'browser';
    if (url.protocol === 'mailto:' || url.protocol === 'tel:') return 'device';
    return 'block';
  } catch {
    return 'block';
  }
}

export function isMainDocumentFailure(url: string, currentUrl: string, status: number): boolean {
  // WebView reports failed images/media too. Let the website handle 401/403/404 screens.
  if (status < 500 || status > 599) return false;
  try {
    const failed = new URL(url);
    const current = new URL(currentUrl);
    failed.hash = '';
    current.hash = '';
    return failed.href === current.href;
  } catch {
    return false;
  }
}

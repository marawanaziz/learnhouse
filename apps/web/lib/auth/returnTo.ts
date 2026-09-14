/** Keep invitation/lesson destinations on this origin across authentication. */
export function safeReturnTo(value: string | null | undefined): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return null
  if (Array.from(value).some(char => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127 || char === '\\')) return null
  return value
}

export function readReturnTo(params: { get(_name: string): string | null }): string | null {
  // Accept existing checkout links while all auth screens use returnTo.
  return safeReturnTo(params.get('returnTo') ?? params.get('redirect'))
}

export function authPath(path: string, returnTo?: string | null): string {
  const destination = safeReturnTo(returnTo)
  return destination ? `${path}?returnTo=${encodeURIComponent(destination)}` : path
}

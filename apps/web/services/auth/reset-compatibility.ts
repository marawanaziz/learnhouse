const RESET_QUERY_KEYS = ['email', 'resetCode'] as const

export function buildResetCompatibilityPath(
  searchParams: Record<string, string | string[] | undefined>,
): string {
  const query = new URLSearchParams()

  for (const key of RESET_QUERY_KEYS) {
    const value = searchParams[key]
    const firstValue = Array.isArray(value) ? value[0] : value
    if (firstValue) query.set(key, firstValue)
  }

  const serialized = query.toString()
  return serialized ? `/reset?${serialized}` : '/reset'
}

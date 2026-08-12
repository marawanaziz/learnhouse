import { headers } from 'next/headers'
import { getBrandProfileForHostname, type BrandProfile } from './brandProfile'

/** Resolve branding from the actual request Host header, never a forwarded host. */
export async function getRequestBrandProfile(): Promise<BrandProfile> {
  const requestHeaders = await headers()
  return getBrandProfileForHostname(requestHeaders.get('host'))
}

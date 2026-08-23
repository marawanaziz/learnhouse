export const BRAND_HOSTS = {
  bbu: 'learn.birthandbabyuniversity.com',
  bold: 'learn.boldmovement.org',
} as const

export const BOLD_ASSET_SOURCES = {
  fonts: 'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap',
} as const

export type BrandKey = keyof typeof BRAND_HOSTS

export interface BrandProfile {
  key: BrandKey
  hostname: string
  displayName: string
  shortName: string
  tagline: string
  description: string
  partnershipLine: string
  colors: {
    ink: string
    primary: string
    accent: string
    coral: string
    paper: string
    surface: string
  }
  fonts: {
    body: string
    heading: string
  }
  logoPath: string
  fullLogoPath: string
  logoAlt: string
  faviconPath: string
  manifestPath: string
}

const BBU_PROFILE: BrandProfile = {
  key: 'bbu',
  hostname: BRAND_HOSTS.bbu,
  displayName: 'Birth & Baby University',
  shortName: 'BBU',
  tagline: 'Birth & Baby University',
  description: 'Birth & Baby University learning portal.',
  partnershipLine: '',
  colors: {
    ink: '#153d5d',
    primary: '#113d5d',
    accent: '#2f6f9f',
    coral: '#d66b55',
    paper: '#f7fafc',
    surface: '#ffffff',
  },
  fonts: {
    body: 'Wix Madefor Text',
    heading: 'Wix Madefor Text',
  },
  logoPath: '/favicon.ico',
  fullLogoPath: '/favicon.ico',
  logoAlt: 'Birth & Baby University',
  faviconPath: '/favicon.ico',
  manifestPath: '/manifest.webmanifest',
}

const BOLD_PROFILE: BrandProfile = {
  key: 'bold',
  hostname: BRAND_HOSTS.bold,
  displayName: 'Project BOLD',
  shortName: 'BOLD',
  tagline: 'Birth Outcomes through Learning & Development',
  description: 'Project BOLD learning portal for families and perinatal professionals.',
  partnershipLine: 'Project BOLD partners with Birth & Baby University to bring trainings and courses.',
  colors: {
    ink: '#16324C',
    primary: '#0E335D',
    accent: '#CD2E3A',
    coral: '#E8897F',
    paper: '#FAF6EE',
    surface: '#FFFDF8',
  },
  fonts: {
    body: 'Inter',
    heading: 'Fraunces',
  },
  // The compact emblem and full vertical lockup are deterministic transparent
  // derivatives of the owner-supplied Project BOLD source image.
  logoPath: '/api/branding/logo',
  fullLogoPath: '/api/branding/full-logo',
  logoAlt: 'Project BOLD emblem',
  faviconPath: '/api/branding/icon',
  manifestPath: '/api/branding/manifest',
}

const PROFILES: Record<BrandKey, BrandProfile> = {
  bbu: BBU_PROFILE,
  bold: BOLD_PROFILE,
}

function stripHostnamePort(hostname: string): string {
  if (hostname.startsWith('[')) {
    const closeBracket = hostname.indexOf(']')
    return closeBracket === -1 ? hostname : hostname.slice(1, closeBracket)
  }
  const colonIndex = hostname.lastIndexOf(':')
  const port = hostname.slice(colonIndex + 1)
  return colonIndex !== -1 && /^\d+$/.test(port) ? hostname.slice(0, colonIndex) : hostname
}

/**
 * Normalize a browser/server hostname for exact allowlist comparison.
 * This intentionally accepts a port but never parses forwarded-host values.
 */
export function normalizeHostname(hostname: string | null | undefined): string {
  const value = (hostname || '').trim().toLowerCase()
  if (!value || value.includes(',') || /[^a-z0-9.:[\]-]/.test(value)) return ''
  return stripHostnamePort(value).replace(/\.$/, '')
}

/**
 * BOLD is selected only by its one exact hostname. Every other host is BBU.
 */
export function brandKeyFromHostname(hostname: string | null | undefined): BrandKey {
  return normalizeHostname(hostname) === BRAND_HOSTS.bold ? 'bold' : 'bbu'
}

export function brandKeyFromProxyHostname(hostname: string | null | undefined): BrandKey {
  return brandKeyFromHostname(hostname)
}

export function getBrandProfile(key: string | null | undefined): BrandProfile {
  return PROFILES[key === 'bold' ? 'bold' : 'bbu']
}

export function getBrandProfileForHostname(hostname: string | null | undefined): BrandProfile {
  return getBrandProfile(brandKeyFromHostname(hostname))
}

export const BRAND_PROFILES = PROFILES

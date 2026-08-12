import '../styles/globals.css'
import React from 'react'
import Providers from '@components/Providers'
import { Wix_Madefor_Text } from 'next/font/google'
import { getRequestBrandProfile } from '@services/branding/brandProfile.server'
import { type BrandKey } from '@services/branding/brandProfile'
import { Metadata } from 'next'

const wixMadeforText = Wix_Madefor_Text({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-default',
})

export async function generateMetadata(): Promise<Metadata> {
  const brand = await getRequestBrandProfile()
  return {
    title: {
      default: brand.displayName,
      template: `%s — ${brand.displayName}`,
    },
    description: brand.description,
    applicationName: brand.shortName,
    icons: {
      icon: brand.faviconPath,
      apple: brand.faviconPath,
    },
    openGraph: {
      title: brand.displayName,
      description: brand.description,
      type: 'website',
    },
  }
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const brand = await getRequestBrandProfile()
  const brandKey: BrandKey = brand.key
  const brandStyle = {
    '--lh-brand-ink': brand.colors.ink,
    '--lh-brand-primary': brand.colors.primary,
    '--lh-brand-accent': brand.colors.accent,
    '--lh-brand-coral': brand.colors.coral,
    '--lh-brand-paper': brand.colors.paper,
    '--lh-brand-surface': brand.colors.surface,
    '--lh-brand-body-font': brand.fonts.body,
    '--lh-brand-heading-font': brand.fonts.heading,
    ...(brand.key === 'bold' ? { '--font-default': 'Inter' } : {}),
  } as React.CSSProperties

  return (
    <html className={wixMadeforText.variable} lang="en" suppressHydrationWarning data-lh-brand={brand.key}>
      <head>
        {/* Synchronous script — blocks parsing to guarantee window.__RUNTIME_CONFIG__ exists before any JS runs.
            Next.js <Script strategy="beforeInteractive"> is not truly blocking in all browsers (Safari). */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/runtime-config.js" />
        {/* Prevent white flash on embed routes: set html+body bg before body is painted.
            Reads the optional ?bgcolor param (hex-validated) or defaults to dark. */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/embed-bg.js" />

        {/* Installable app (PWA): manifest, iOS home-screen icon + standalone hints,
            brand theme color. Makes learn.birthandbabyuniversity.com installable on
            phones without an App Store build. */}
        <link rel="manifest" href={brand.manifestPath} />
        <link rel="icon" href={brand.faviconPath} sizes="any" />
        {brand.key === 'bbu' && <>
          <link rel="icon" type="image/png" sizes="192x192" href="/bbu-icon-192.png" />
          <link rel="icon" type="image/png" sizes="512x512" href="/bbu-icon-512.png" />
          <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        </>}
        {brand.key === 'bold' && <>
          <link rel="preconnect" href="https://fonts.googleapis.com" />
          <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
          <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" />
        </>}
        <meta name="theme-color" content={brand.colors.primary} />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content={brand.shortName} />
        {/* Register the service worker (installability + offline shell). */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})})}",
          }}
        />
      </head>
      <body suppressHydrationWarning style={brandStyle}>
        <Providers brandKey={brandKey}>
          <main className="animate-fade-in">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  )
}

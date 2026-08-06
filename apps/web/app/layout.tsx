import '../styles/globals.css'
import '../styles/mobile/mobile.css'
import React from 'react'
import Providers from '@components/Providers'
import MobileChrome from '@components/Mobile/MobileChrome'
import { Wix_Madefor_Text } from 'next/font/google'

const wixMadeforText = Wix_Madefor_Text({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-default',
})

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html className={wixMadeforText.variable} lang="en" suppressHydrationWarning>
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
        <link rel="manifest" href="/manifest.webmanifest" />
        {/* BBU browser-tab favicon (overrides the default LearnHouse favicon.ico) */}
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" type="image/png" sizes="192x192" href="/bbu-icon-192.png" />
        <link rel="icon" type="image/png" sizes="512x512" href="/bbu-icon-512.png" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <meta name="theme-color" content="#113d5d" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="BBU" />

        {/* Capacitor mobile shell overrides. Only takes effect when wrapped in the
            native app — in a regular browser these are no-ops. */}
        <meta name="bbu-shell-version" content="0.1.0" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=5" />

        {/* Register the service worker (installability + offline shell). */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){})})}",
          }}
        />
      </head>
      <body suppressHydrationWarning>
        <Providers>
          <main className="animate-fade-in">
            <MobileChrome>{children}</MobileChrome>
          </main>
        </Providers>
      </body>
    </html>
  )
}

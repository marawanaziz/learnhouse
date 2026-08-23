'use client'
import React from 'react'
import Image from 'next/image'
import Link from 'next/link'
import learnhouseIcon from 'public/learnhouse_bigicon_1.png'
import { getOrgLogoMediaDirectory, getOrgAuthBackgroundMediaDirectory } from '@services/media/media'
import { getUriWithOrg } from '@services/config/config'
import { cn } from '@/lib/utils'
import { useBrand } from '@components/Contexts/BrandContext'
import BrandLogo from '@components/Brand/BrandLogo'

interface AuthBrandingPanelProps {
  org: any
  welcomeText?: string
}

export default function AuthBrandingPanel({ org, welcomeText }: AuthBrandingPanelProps) {
  const brand = useBrand()
  const authBranding = org?.config?.config?.customization?.auth_branding || org?.config?.config?.general?.auth_branding || {}
  const {
    welcome_message = '',
    background_type = 'gradient',
    background_image = '',
    text_color = 'light',
    unsplash_photographer_name = '',
    unsplash_photographer_url = '',
    unsplash_photo_url = '',
  } = authBranding
  const UNSPLASH_UTM = '?utm_source=LearnHouse&utm_medium=referral'
  const withUtm = (url: string) => (url ? `${url}${UNSPLASH_UTM}` : '')

  const getBackgroundStyle = (): React.CSSProperties => {
    if (brand.key === 'bold') {
      return {
        background: `linear-gradient(145deg, ${brand.colors.paper} 0%, ${brand.colors.surface} 72%, #f0e2d8 150%)`,
      }
    }
    if (background_type === 'gradient' || !background_image) {
      // Keep the original black gradient
      return {
        background: 'linear-gradient(157deg, #0d3350 0%, #164e77 46%, #3f7cb4 82%, #79b4e6 130%)',
      }
    }
    if (background_type === 'custom' && background_image) {
      return {
        backgroundImage: `url(${getOrgAuthBackgroundMediaDirectory(org?.org_uuid, background_image)})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }
    }
    if (background_type === 'unsplash' && background_image) {
      return {
        backgroundImage: `url(${background_image})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }
    }
    return {
      background: 'linear-gradient(041.61deg, #202020 7.15%, #000000 90.96%)',
    }
  }

  const displayMessage = brand.key === 'bold'
    ? brand.partnershipLine
    : welcome_message || welcomeText || ''
  const effectiveTextColor = brand.key === 'bold' ? 'dark' : text_color
  const hasCustomBackground = brand.key !== 'bold' && background_type !== 'gradient' && background_image

  return (
    <div
      className="relative flex flex-col h-full w-full"
      style={getBackgroundStyle()}
    >
      {/* Overlay for custom backgrounds only */}
      {hasCustomBackground && (
        <div className="absolute inset-0 bg-black/30" />
      )}

      {/* Content */}
      <div className="relative z-10 flex flex-col h-full p-10">
        {/* BBU is white-labelled — no LearnHouse logo/link on auth pages. */}

        {/* Content - vertically and horizontally centered */}
        <div className="flex-1 flex items-center justify-center">
          <div className={cn(
            "flex flex-col items-center text-center gap-6",
            effectiveTextColor === 'light' ? "text-white" : "text-gray-900"
          )}>
            {/* Organization logo */}
            <Link prefetch href={getUriWithOrg(org?.slug, '/')}>
              <div className={cn(
                "w-72 h-72 rounded-3xl ring-1 ring-inset ring-white/10 bg-white flex items-center justify-center overflow-hidden",
                brand.key === 'bold' && 'lh-brand-auth-mark'
              )}>
                {brand.key === 'bold' ? (
                  <BrandLogo className="w-full h-full p-5" />
                ) : org?.logo_image ? (
                  <img
                    src={getOrgLogoMediaDirectory(org.org_uuid, org.logo_image)}
                    alt={org.name}
                    className="w-full h-full object-contain p-5"
                  />
                ) : (
                  <Image
                    quality={100}
                    width={96}
                    height={96}
                    src={learnhouseIcon}
                    alt="LearnHouse"
                    className="object-contain"
                  />
                )}
              </div>
            </Link>

            {/* Text content */}
            <div className="space-y-1">
              <h1 className="font-bold text-3xl tracking-tight">{brand.key === 'bold' ? brand.displayName : org?.name}</h1>
              {displayMessage && (
                <p className={cn(
                  "text-lg max-w-sm leading-relaxed",
                  effectiveTextColor === 'light' ? "text-white/70" : "text-gray-600"
                )}>
                  {displayMessage}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Bottom spacer for visual balance */}
        <div className="h-10" />

        {/* Unsplash attribution (required by Unsplash API guidelines) */}
        {background_type === 'unsplash' && background_image && unsplash_photographer_name && (
          <div className={cn(
            "absolute bottom-3 left-4 right-4 z-10 text-[11px] leading-tight",
            text_color === 'light' ? "text-white/70" : "text-gray-700"
          )}>
            Photo by{' '}
            <a
              href={withUtm(unsplash_photographer_url) || withUtm(unsplash_photo_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:opacity-100 opacity-90"
            >
              {unsplash_photographer_name}
            </a>
            {' '}on{' '}
            <a
              href={`https://unsplash.com/${UNSPLASH_UTM}`}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:opacity-100 opacity-90"
            >
              Unsplash
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

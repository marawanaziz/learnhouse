'use client'

import React from 'react'
import { useBrand } from '@components/Contexts/BrandContext'
import { cn } from '@/lib/utils'

export default function BrandLogo({ compact = false, inverse = false, className }: {
  compact?: boolean
  inverse?: boolean
  className?: string
}) {
  const brand = useBrand()

  if (brand.key === 'bold') {
    const logoPath = compact ? brand.logoPath : brand.fullLogoPath
    return (
      <span className={cn('lh-brand-lockup', compact && 'lh-brand-lockup--compact', inverse && 'lh-brand-lockup--inverse', className)}>
        <img src={logoPath} alt={brand.logoAlt} className={cn('lh-brand-logo', !compact && 'lh-brand-logo--full')} />
      </span>
    )
  }

  return (
    <span className={cn('lh-brand-bbu-wordmark', inverse && 'lh-brand-bbu-wordmark--inverse', className)}>
      {compact ? brand.shortName : brand.displayName}
    </span>
  )
}

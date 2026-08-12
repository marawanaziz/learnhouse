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
    return (
      <span className={cn('lh-brand-lockup', inverse && 'lh-brand-lockup--inverse', className)} aria-label={brand.displayName}>
        <span className="lh-brand-emblem" aria-hidden="true">&amp;</span>
        {!compact && <span className="lh-brand-wordmark">Project BOLD</span>}
      </span>
    )
  }

  return (
    <span className={cn('lh-brand-bbu-wordmark', inverse && 'lh-brand-bbu-wordmark--inverse', className)}>
      {compact ? brand.shortName : brand.displayName}
    </span>
  )
}

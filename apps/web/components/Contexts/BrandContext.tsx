'use client'

import React, { createContext, useContext, useMemo } from 'react'
import { getBrandProfile, type BrandKey, type BrandProfile } from '@services/branding/brandProfile'

const BrandContext = createContext<BrandProfile>(getBrandProfile('bbu'))

export function BrandProvider({ brandKey, children }: { brandKey: BrandKey; children: React.ReactNode }) {
  const profile = useMemo(() => getBrandProfile(brandKey), [brandKey])
  return <BrandContext.Provider value={profile}>{children}</BrandContext.Provider>
}

export function useBrand(): BrandProfile {
  return useContext(BrandContext)
}

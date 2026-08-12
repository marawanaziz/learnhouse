import { Metadata } from 'next'
import React from 'react'
import { OrgProvider } from '@components/Contexts/OrgContext'
import OrgLanguageSync from '@components/Contexts/OrgLanguageSync'
import NextTopLoader from 'nextjs-toploader'
import Toast from '@components/Objects/StyledElements/Toast/Toast'
import '@styles/globals.css'
import Footer from '@components/Footer/Footer'
import { getOrganizationContextInfo } from '@services/organizations/orgs'
import { getOrgFaviconMediaDirectory } from '@services/media/media'
import { getRequestBrandProfile } from '@services/branding/brandProfile.server'

export async function generateMetadata({
  params,
}: {
  params: Promise<{ orgslug: string }>
}): Promise<Metadata> {
  const brand = await getRequestBrandProfile()
  if (brand.key === 'bold') {
    return {
      icons: { icon: brand.faviconPath, apple: brand.faviconPath },
    }
  }
  const { orgslug } = await params
  try {
    const org = await getOrganizationContextInfo(orgslug, {
      revalidate: 86400,
      tags: ['organizations'],
    })
    const faviconImage = org?.config?.config?.customization?.general?.favicon_image || org?.config?.config?.general?.favicon_image
    if (faviconImage) {
      return {
        icons: { icon: getOrgFaviconMediaDirectory(org.org_uuid, faviconImage) },
      }
    }
  } catch {
    // Use the host-level favicon fallback below.
  }
  return {}
}

export default async function RootLayout(props: {
  children: React.ReactNode
  params: Promise<{ orgslug: string }>
}) {
  const params = await props.params

  return (
    <div>
      <OrgProvider orgslug={params.orgslug}>
        <OrgLanguageSync />
        <NextTopLoader color="#2e2e2e" initialPosition={0.3} height={4} easing={'ease'} speed={500} showSpinner={false} />
        <Toast />
        {props.children}
        <Footer />
      </OrgProvider>
    </div>
  )
}

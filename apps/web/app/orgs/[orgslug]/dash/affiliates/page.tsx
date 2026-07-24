import { getOrganizationContextInfo } from '@services/organizations/orgs'
import { Metadata } from 'next'
import React from 'react'
import BBUEmbed from '@components/Dashboard/Pages/BBUEmbed/BBUEmbed'

type MetadataProps = {
  params: Promise<{ orgslug: string }>
}

export async function generateMetadata(props: MetadataProps): Promise<Metadata> {
  const params = await props.params
  const org = await getOrganizationContextInfo(params.orgslug, {
    revalidate: 120,
    tags: ['organizations'],
  })
  return {
    title: 'Affiliates — ' + org.name,
    description: `Affiliate program: partners, referrals, commissions & payouts for ${org.name}`,
    robots: { index: false, follow: false },
  }
}

async function AffiliatesDashPage() {
  return <BBUEmbed path="bbu/affiliate/admin" title="Affiliate Program" />
}

export default AffiliatesDashPage

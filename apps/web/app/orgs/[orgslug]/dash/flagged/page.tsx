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
    title: 'Flagged posts — ' + org.name,
    description: `Community reports awaiting review for ${org.name}`,
    robots: { index: false, follow: false },
  }
}

async function FlaggedPostsDashPage() {
  return <BBUEmbed path="bbu/community/admin" title="Flagged Posts" />
}

export default FlaggedPostsDashPage

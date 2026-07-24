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
    title: 'Certificates — ' + org.name,
    description: `Certificate & credential management for ${org.name}`,
    robots: { index: false, follow: false },
  }
}

async function CertificatesDashPage() {
  return <BBUEmbed path="bbu/cert-admin/" title="Certificate Manager" />
}

export default CertificatesDashPage

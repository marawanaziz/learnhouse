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
    title: 'Operations — ' + org.name,
    description: `Store, cohorts, coupons, credentials & seat codes for ${org.name}`,
    robots: { index: false, follow: false },
  }
}

async function OperationsDashPage(props: {
  searchParams: Promise<{ credential_application?: string }>
}) {
  const searchParams = await props.searchParams
  const applicationId = String(searchParams.credential_application || '').replace(/\D/g, '')
  const query = applicationId ? `?credential_application=${applicationId}` : ''
  return <BBUEmbed path={`bbu/admin/${query}`} title="Operations Console" />
}

export default OperationsDashPage

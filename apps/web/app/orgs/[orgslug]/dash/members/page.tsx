import { getOrganizationContextInfo } from '@services/organizations/orgs'
import { Metadata } from 'next'
import React from 'react'
import MembersManager from '@components/Dashboard/Pages/Members/MembersManager'

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
    title: 'Members — ' + org.name,
    description: `Manage members and groups for ${org.name}`,
    robots: { index: false, follow: false },
  }
}

async function MembersDashPage() {
  return <MembersManager />
}

export default MembersDashPage

import { Metadata } from 'next'
import { getOrganizationContextInfo } from '@services/organizations/orgs'
import { getOrgSlug } from '@services/org/orgResolution'
import SignUpClient from './signup'
import { Suspense } from 'react'
import PageLoading from '@components/Objects/Loaders/PageLoading'
import OrgNotFound from '@components/Objects/StyledElements/Error/OrgNotFound'
import { getRequestBrandProfile } from '@services/branding/brandProfile.server'

export async function generateMetadata(): Promise<Metadata> {
  const brand = await getRequestBrandProfile()
  const orgslug = await getOrgSlug()

  if (!orgslug) {
    return { title: `Sign up — ${brand.displayName}` }
  }

  let org: any = null
  try {
    org = await getOrganizationContextInfo(orgslug, null)
  } catch {
    // Stale cookie or unknown org — fall back to generic title
  }

  return {
    title: 'Sign up' + ` — ${brand.key === 'bold' ? brand.displayName : org?.name || brand.displayName}`,
    robots: { index: false, follow: false },
  }
}

const SignUp = async () => {
  const orgslug = await getOrgSlug()

  if (!orgslug) {
    return <OrgNotFound />
  }

  let org: any = null
  try {
    org = await getOrganizationContextInfo(orgslug, null)
  } catch {
    return <OrgNotFound />
  }

  if (!org) {
    return <OrgNotFound />
  }

  return (
    <>
      <Suspense fallback={<PageLoading />}>
        <SignUpClient org={org} />
      </Suspense>
    </>
  )
}

export default SignUp

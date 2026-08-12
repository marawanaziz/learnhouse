import { getOrganizationContextInfo } from '@services/organizations/orgs'
import { getOrgSlug } from '@services/org/orgResolution'
import LoginClient from './login'
import { Metadata } from 'next'
import OrgNotFound from '@components/Objects/StyledElements/Error/OrgNotFound'
import { getRequestBrandProfile } from '@services/branding/brandProfile.server'

export async function generateMetadata(): Promise<Metadata> {
  const brand = await getRequestBrandProfile()
  const orgslug = await getOrgSlug()

  if (!orgslug) {
    return { title: `Login — ${brand.displayName}` }
  }

  let org: any = null
  try {
    org = await getOrganizationContextInfo(orgslug, {
      revalidate: 60,
      tags: ['organizations'],
    })
  } catch {
    // Stale cookie or unknown org — fall back to generic title
  }

  return {
    title: 'Login' + ` — ${brand.key === 'bold' ? brand.displayName : org?.name || brand.displayName}`,
    robots: { index: false, follow: false },
  }
}

const Login = async () => {
  const orgslug = await getOrgSlug()

  if (!orgslug) {
    return <OrgNotFound />
  }

  let org: any = null
  try {
    org = await getOrganizationContextInfo(orgslug, {
      revalidate: 60,
      tags: ['organizations'],
    })
  } catch {
    return <OrgNotFound />
  }

  if (!org) {
    return <OrgNotFound />
  }

  return (
    <div>
      <LoginClient org={org}></LoginClient>
    </div>
  )
}

export default Login

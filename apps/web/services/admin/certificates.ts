import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader, errorHandling } from '@services/utils/ts/requests'

/** Delete one issued certificate through the organization-scoped admin API. */
export async function deleteUserCertificate(
  orgSlug: string,
  userId: number,
  userCertificationUuid: string,
  accessToken?: string,
) {
  const response = await fetch(
    `${getAPIUrl()}admin/${encodeURIComponent(orgSlug)}/certifications/${userId}/${encodeURIComponent(userCertificationUuid)}`,
    RequestBodyWithAuthHeader('DELETE', null, null, accessToken),
  )
  return errorHandling(response)
}

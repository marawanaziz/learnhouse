export function buildOrgResetRequest(apiBaseUrl: string, email: string, orgId: number) {
  return {
    url: `${apiBaseUrl}users/reset_password/send_reset_code`,
    body: { email, org_id: orgId },
  }
}

import { redirect } from 'next/navigation'
import { buildResetCompatibilityPath } from '@services/auth/reset-compatibility'

type ResetPasswordCompatibilityProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}

/** Backward-compatible alias for older reset emails; never logs or renders secrets. */
export default async function ResetPasswordCompatibilityPage({
  searchParams,
}: ResetPasswordCompatibilityProps) {
  redirect(buildResetCompatibilityPath(await searchParams))
}

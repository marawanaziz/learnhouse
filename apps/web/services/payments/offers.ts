'use server';
import { cookies } from 'next/headers';
import { getAPIUrl } from '@services/config/config';
import { RequestBodyWithAuthHeader, getResponseMetadata, secureFetch } from '@services/utils/ts/requests';

// Referral cookie set by the affiliate entry point (`/api/v1/bbu/r/{code}`).
const REFERRAL_COOKIE = 'bbu_ref';

export async function getOffers(orgId: number, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function createOffer(orgId: number, data: any, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers`,
    RequestBodyWithAuthHeader('POST', data, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function updateOffer(orgId: number, offerId: string, data: any, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/${encodeURIComponent(offerId)}`,
    RequestBodyWithAuthHeader('PUT', data, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function archiveOffer(orgId: number, offerId: string, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/${encodeURIComponent(offerId)}`,
    RequestBodyWithAuthHeader('DELETE', null, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function getOfferDetails(orgId: number, offerId: string, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/${encodeURIComponent(offerId)}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function getPublicOffer(orgId: number, offerId: string, access_token = '') {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/${encodeURIComponent(offerId)}/public`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function getPublicOffers(orgId: number, access_token = '', audience = '') {
  const params = new URLSearchParams()
  if (audience) params.set('audience', audience)
  const query = params.toString()
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/public-listing${query ? `?${query}` : ''}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function getStorefrontOffers(
  orgId: number,
  access_token = '',
  audience = ''
) {
  const params = new URLSearchParams()
  if (audience) params.set('audience', audience)
  const query = params.toString()
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/storefront${query ? `?${query}` : ''}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return getResponseMetadata(result)
}

export async function getOffersByResource(orgId: number, resourceUuid: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/by-resource?resource_uuid=${encodeURIComponent(resourceUuid)}`,
    RequestBodyWithAuthHeader('GET', null, null, '')
  );
  return getResponseMetadata(result);
}

// Provider-agnostic: the backend selects the correct payment provider
// based on the org's active PaymentsConfig.
export async function getOfferCheckoutSession(
  orgId: number,
  offerUuid: string,
  redirect_uri: string,
  access_token: string,
  bumps: string[] = []
) {
  // This runs as a server action, so the browser's cookie jar is not attached
  // to the outbound fetch: `credentials: 'include'` is inert here and the call
  // goes straight to the API rather than through the Next /api/v1 proxy. Read
  // the incoming referral cookie explicitly and forward it with the explicit
  // ref, so the backend can stamp attribution onto the Stripe session and the
  // order exactly as the native buy path does.
  const cookieStore = await cookies();
  const ref = cookieStore.get(REFERRAL_COOKIE)?.value?.trim() || '';
  const base = RequestBodyWithAuthHeader('POST', { bumps, ref }, null, access_token);
  const init: RequestInit = ref
    ? { ...base, headers: { ...Object.fromEntries(new Headers(base.headers as HeadersInit)), Cookie: `${REFERRAL_COOKIE}=${ref}` } }
    : base;

  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/offers/${encodeURIComponent(offerUuid)}/checkout?redirect_uri=${encodeURIComponent(redirect_uri)}`,
    init
  );
  return getResponseMetadata(result);
}

export async function getBillingPortalSession(orgId: number, return_url: string, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/billing/portal?return_url=${encodeURIComponent(return_url)}`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  );
  return getResponseMetadata(result);
}

export async function getUserEnrollments(orgId: number, access_token: string) {
  const result = await secureFetch(
    `${getAPIUrl()}payments/${encodeURIComponent(String(orgId))}/enrollments/mine`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  );
  const metadata = await getResponseMetadata(result);
  if (!metadata.success) throw new Error(metadata.HTTPmessage || 'Failed to fetch enrollments')
  return metadata;
}

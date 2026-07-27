'use client'

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import GeneralWrapperStyled from '@components/Objects/StyledElements/Wrappers/GeneralWrapper'
import TypeOfContentTitle from '@components/Objects/StyledElements/Titles/TypeOfContentTitle'
import FeatureGate from '@components/Dashboard/Shared/FeatureGate/FeatureGate'
import { useOrg } from '@components/Contexts/OrgContext'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { queryKeys } from '@/lib/query/keys'
import { getOrgFolders, getOrgRootItems } from '@services/folders/folders'
import { FolderSimple } from '@phosphor-icons/react'
import { FolderCard, LibraryItemCard } from './library-cards'
import { useTrackView, AnalyticsEvent } from '@services/analytics'

function LibraryClient({ orgslug }: { orgslug: string }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const access_token = session?.data?.tokens?.access_token

  // E-books are products with a token-gated PDF, separate from the folder tree —
  // so a buyer had nowhere to re-download them after the original receipt.
  const { data: myEbooks } = useQuery({
    queryKey: ['bbu', 'my-ebooks'],
    queryFn: async () => {
      const r = await fetch('/api/v1/bbu/my-ebooks', { credentials: 'include' })
      return r.ok ? r.json() : []
    },
  })

  const { data, isLoading, isError } = useQuery({
    queryKey: org?.id ? queryKeys.folders.list(org.id) : ['folders', 'pending'],
    queryFn: () => getOrgFolders(org.id, access_token),
    enabled: !!org?.id,
  })

  const { data: rootItemsData } = useQuery({
    queryKey: org?.id ? ['library-root-items', org.id] : ['library-root-items', 'pending'],
    queryFn: () => getOrgRootItems(org.id, access_token),
    enabled: !!org?.id,
  })

  // Folders are a transparent, optional layer: a fetch failure must degrade to
  // an empty state rather than blanking the page or blocking course discovery.
  const folders = Array.isArray(data) ? data : []
  const rootItems = Array.isArray(rootItemsData) ? rootItemsData : []

  useTrackView(
    AnalyticsEvent.LibraryViewed,
    { folder_count: folders.length, is_empty: folders.length === 0 && rootItems.length === 0 },
    !isLoading,
    'learner',
  )

  if (isLoading && !data) {
    return (
      <div className="w-full animate-pulse">
        <GeneralWrapperStyled>
          <div className="h-7 bg-gray-200 rounded w-28 mb-4" />
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="bg-white rounded-xl nice-shadow p-3 h-16" />
            ))}
          </div>
        </GeneralWrapperStyled>
      </div>
    )
  }

  return (
    <FeatureGate feature="folders" orgslug={orgslug} context="public">
      <div className="w-full">
        <GeneralWrapperStyled>
          <div className="flex flex-col space-y-2 mb-2">
            <div className="flex items-center justify-between">
              <TypeOfContentTitle title={t('library.library')} type="cou" />
            </div>

            <div className="flex flex-col gap-7">
              {Array.isArray(myEbooks) && myEbooks.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500 mb-3">
                    E-books
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                    {myEbooks.map((b: any) => (
                      <div key={b.id} className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col gap-2">
                        <div className="font-semibold text-gray-900">{b.name}</div>
                        {b.description && (
                          <div className="text-sm text-gray-500 line-clamp-2">{b.description}</div>
                        )}
                        {b.owned && b.download_url ? (
                          <a
                            href={b.download_url}
                            className="mt-auto inline-block text-center rounded-lg bg-gray-900 text-white text-sm font-semibold px-4 py-2 hover:bg-gray-700"
                          >
                            Download PDF
                          </a>
                        ) : b.owned ? (
                          <span className="mt-auto text-xs text-gray-400">
                            Download link unavailable — contact support
                          </span>
                        ) : (
                          <a
                            href={b.buy_url}
                            className="mt-auto inline-block text-center rounded-lg border border-gray-300 text-gray-900 text-sm font-semibold px-4 py-2 hover:bg-gray-50"
                          >
                            Get it{b.price ? ` — $${b.price}` : ''}
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {folders.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {folders.map((folder: any) => (
                    <FolderCard key={folder.folder_uuid} folder={folder} orgslug={orgslug} />
                  ))}
                </div>
              )}

              {rootItems.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 items-start">
                  {rootItems.map((item: any) => (
                    <LibraryItemCard key={item.resource_uuid} item={item} orgslug={orgslug} />
                  ))}
                </div>
              )}

              {folders.length === 0 && rootItems.length === 0 && (
                <div className="col-span-full flex flex-col justify-center items-center py-12 px-4 border-2 border-dashed border-gray-100 rounded-2xl bg-gray-50/30">
                  <div className="p-4 bg-white rounded-full nice-shadow mb-4">
                    <FolderSimple className="w-8 h-8 text-gray-300" weight="duotone" />
                  </div>
                  <h3 className="text-lg font-bold text-gray-600 mb-1">
                    {isError ? t('library.error_loading') : t('library.empty_folder')}
                  </h3>
                </div>
              )}
            </div>
          </div>
        </GeneralWrapperStyled>
      </div>
    </FeatureGate>
  )
}

export default LibraryClient

'use client'
import React from 'react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import { Award, BadgeDollarSign, User, Lock, ShoppingBag, Settings } from 'lucide-react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import UserAvatar from '@components/Objects/UserAvatar'
import { getUriWithOrg } from '@services/config/config'
import { useBrand } from '@components/Contexts/BrandContext'

interface AccountSidebarProps {
  orgslug: string
  currentSubpage: string
}

const NAV_ITEMS = [
  { id: 'general', icon: Settings, labelKey: 'account.general', label: '' },
  { id: 'profile', icon: User, labelKey: 'account.profile', label: '' },
  { id: 'security', icon: Lock, labelKey: 'account.security', label: '' },
  { id: 'purchases', icon: ShoppingBag, labelKey: 'account.purchases', label: '' },
  { id: 'credentials', icon: Award, labelKey: '', label: 'Credentials' },
  { id: 'affiliate', icon: BadgeDollarSign, labelKey: '', label: 'Affiliate Dashboard' },
]

export function AccountSidebar({ orgslug, currentSubpage }: AccountSidebarProps) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const user = session?.data?.user
  const brand = useBrand()

  return (
    <div className="lh-account-sidebar space-y-4" data-brand={brand.key}>
      {/* User Info Card */}
      <div className="bg-white nice-shadow rounded-lg overflow-hidden">
        {/* User Profile Header */}
        <div className="p-4 border-b border-gray-100">
          <div className="flex flex-col items-center text-center">
            <UserAvatar
              border="border-4"
              rounded="rounded-full"
              width={80}
            />
            <div className="mt-3">
              <h2 className="font-semibold text-gray-900">
                {user?.first_name} {user?.last_name}
              </h2>
              <p className="text-sm text-gray-500">@{user?.username}</p>
            </div>
          </div>
        </div>

        {/* User Bio (truncated) */}
        {user?.bio && (
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm text-gray-600 leading-relaxed line-clamp-3">
              {user.bio}
            </p>
          </div>
        )}

        {/* Navigation */}
        <div className="p-2">
          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon
              const isActive = currentSubpage === item.id
              return (
                <Link
                  key={item.id}
                  href={getUriWithOrg(orgslug, `/account/${item.id}`)}
                  className={`lh-account-nav-item flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                    isActive ? 'lh-account-nav-item--active' : 'lh-account-nav-item--inactive'
                  }`}
                >
                  <Icon
                    size={18}
                    className={isActive ? 'lh-account-sidebar-icon--active' : 'lh-account-sidebar-icon--inactive'}
                  />
                  <span className="text-sm font-medium">{item.label || t(item.labelKey)}</span>
                </Link>
              )
            })}
          </nav>
        </div>
      </div>
    </div>
  )
}

export default AccountSidebar

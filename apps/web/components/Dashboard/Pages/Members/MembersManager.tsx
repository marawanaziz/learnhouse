'use client'
import React, { useMemo, useState } from 'react'
import { useOrg } from '@components/Contexts/OrgContext'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getAPIUrl } from '@services/config/config'
import { apiFetch } from '@services/utils/ts/requests'
import { getUserAvatarMediaDirectory } from '@services/media/media'
import MemberProfile from './MemberProfile'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createUserGroup, deleteUserGroup,
  linkUsersToUserGroup, unlinkUsersFromUserGroup,
  getUserGroupResources, linkResourcesToUserGroup, unLinkResourcesToUserGroup,
} from '@services/usergroups/usergroups'
import {
  Users, UsersThree, Plus, Trash, MagnifyingGlass, CaretLeft, CaretRight,
  BookOpen, X, Check, GraduationCap,
} from '@phosphor-icons/react'
import toast from 'react-hot-toast'

const PAGE = 12

type Group = { id: number; name: string; description?: string; usergroup_uuid?: string }

function MembersManager() {
  const org = useOrg() as any
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const qc = useQueryClient()

  const [selectedGroup, setSelectedGroup] = useState<Group | null>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [newGroup, setNewGroup] = useState('')
  const [creating, setCreating] = useState(false)
  // The per-course purchase-access groups (auto-created, named "… · Access") clutter
  // the list; hide them by default so human cohorts/tiers stand out.
  const [showAccess, setShowAccess] = useState(false)
  const [courseModal, setCourseModal] = useState(false)
  const [profileUserId, setProfileUserId] = useState<number | null>(null)

  const orgId = org?.id
  const enabled = !!orgId && !!token

  // ---- groups ----
  const { data: groupsRes } = useQuery({
    queryKey: ['members', 'groups', orgId],
    queryFn: () => apiFetch(`${getAPIUrl()}usergroups/org/${orgId}?org_id=${orgId}`, token),
    enabled,
  })
  const groups: Group[] = Array.isArray(groupsRes) ? groupsRes : (groupsRes?.data || groupsRes?.items || [])

  // ---- roster ----
  const rosterQuery = () => {
    const p = new URLSearchParams({ page: String(page), limit: String(PAGE), sort_order: 'asc' })
    if (search) p.append('search', search)
    if (selectedGroup) { p.append('usergroup_id', String(selectedGroup.id)); p.append('usergroup_filter', 'in_group') }
    return p.toString()
  }
  // "All members" (no group selected) is powered by the reliable /bbu/people
  // roster with progress/cert/spend rollups; group views keep the native roster.
  const usingPeople = !selectedGroup
  const { data: roster, isFetching } = useQuery({
    queryKey: ['members', 'roster', orgId, page, search, selectedGroup?.id],
    queryFn: () => apiFetch(`${getAPIUrl()}orgs/${orgId}/users?${rosterQuery()}`, token),
    enabled: enabled && !usingPeople,
    placeholderData: (p) => p,
  })
  const { data: peopleData, isFetching: peopleFetching } = useQuery({
    queryKey: ['bbu-people', page, search],
    queryFn: () => apiFetch(`${getAPIUrl()}bbu/people?q=${encodeURIComponent(search)}&limit=${PAGE}&offset=${(page - 1) * PAGE}`, token),
    enabled: enabled && usingPeople,
    placeholderData: (p: any) => p,
  })
  const people: any[] = peopleData?.people || []
  const rows: any[] = roster?.items || []
  const total: number = usingPeople ? (peopleData?.total || 0) : (roster?.total || 0)
  const pages = Math.max(1, Math.ceil(total / PAGE))

  // ---- group's linked courses ----
  const { data: groupResources } = useQuery({
    queryKey: ['members', 'group-resources', selectedGroup?.id],
    queryFn: () => getUserGroupResources(selectedGroup!.id, orgId, token),
    enabled: enabled && !!selectedGroup,
  })
  const linkedCourseUuids: string[] = ((groupResources?.data || []) as string[]).filter((r) => r.startsWith('course_'))

  // ---- all courses (for the picker) ----
  const { data: allCourses } = useQuery({
    queryKey: ['members', 'all-courses', org?.slug],
    queryFn: () => apiFetch(`${getAPIUrl()}courses/org_slug/${org.slug}/page/1/limit/100`, token),
    enabled: enabled && !!org?.slug,
  })
  const courses: any[] = Array.isArray(allCourses) ? allCourses : (allCourses?.items || [])
  const courseName = (uuid: string) => courses.find((c) => c.course_uuid === uuid)?.name || uuid

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['members'] })
  }

  // ---- mutations ----
  const doCreateGroup = async () => {
    const name = newGroup.trim()
    if (!name) return
    setCreating(true)
    try {
      await createUserGroup({ name, description: '', org_id: orgId }, token)
      setNewGroup('')
      toast.success(`Group "${name}" created`)
      invalidate()
    } catch { toast.error('Could not create group') } finally { setCreating(false) }
  }
  const doDeleteGroup = async (g: Group) => {
    if (!confirm(`Delete the group "${g.name}"? Members stay, but this grouping is removed.`)) return
    try {
      await deleteUserGroup(g.id, orgId, token)
      if (selectedGroup?.id === g.id) setSelectedGroup(null)
      toast.success('Group deleted'); invalidate()
    } catch { toast.error('Could not delete group') }
  }
  const addPickedTo = async (g: Group) => {
    if (!picked.size) return
    try {
      await linkUsersToUserGroup(g.id, [...picked], orgId, token)
      toast.success(`Added ${picked.size} to "${g.name}"`); setPicked(new Set()); invalidate()
    } catch { toast.error('Could not add members') }
  }
  const removePickedFrom = async (g: Group) => {
    if (!picked.size) return
    try {
      await unlinkUsersFromUserGroup(g.id, [...picked], orgId, token)
      toast.success(`Removed ${picked.size} from "${g.name}"`); setPicked(new Set()); invalidate()
    } catch { toast.error('Could not remove members') }
  }
  const toggleCourse = async (uuid: string, linked: boolean) => {
    if (!selectedGroup) return
    try {
      if (linked) await unLinkResourcesToUserGroup(selectedGroup.id, uuid, orgId, token)
      else await linkResourcesToUserGroup(selectedGroup.id, uuid, orgId, token)
      invalidate()
    } catch { toast.error('Could not update course access') }
  }

  const allChecked = rows.length > 0 && rows.every((r) => picked.has(r.user.id))
  const toggleAll = () => {
    const next = new Set(picked)
    if (allChecked) rows.forEach((r) => next.delete(r.user.id))
    else rows.forEach((r) => next.add(r.user.id))
    setPicked(next)
  }

  return (
    <div className="mx-4 sm:mx-10 my-6">
      <div className="mb-5">
        <h1 className="text-2xl font-black text-gray-900 tracking-tight flex items-center gap-2">
          <UsersThree size={24} weight="fill" className="text-gray-700" /> Members
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Manage your students and organize them into groups &amp; cohorts. Group membership controls course access.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Groups panel */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-xl shadow-xs border border-gray-100 p-3 sticky top-4">
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-xs font-bold uppercase tracking-wide text-gray-500">Groups &amp; Cohorts</span>
            </div>
            <button
              onClick={() => setSelectedGroup(null)}
              className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${!selectedGroup ? 'bg-gray-900 text-white' : 'hover:bg-gray-50 text-gray-700'}`}
            >
              <Users size={16} weight="fill" /> All members
            </button>
            {(() => {
              const accessCount = groups.filter((g) => / · Access$/.test(g.name)).length
              return accessCount > 0 ? (
                <label className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 cursor-pointer select-none">
                  <input type="checkbox" checked={showAccess} onChange={(e) => setShowAccess(e.target.checked)} />
                  Show {accessCount} per-course access groups
                </label>
              ) : null
            })()}
            <div className="mt-1 space-y-0.5 max-h-[420px] overflow-y-auto">
              {groups.filter((g) => showAccess || !/ · Access$/.test(g.name)).map((g) => (
                <div key={g.id} className={`group flex items-center rounded-lg ${selectedGroup?.id === g.id ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}>
                  <button
                    onClick={() => { setSelectedGroup(g); setPage(1); setPicked(new Set()) }}
                    className={`flex-1 text-left px-3 py-2 text-sm truncate ${selectedGroup?.id === g.id ? 'text-indigo-800 font-semibold' : 'text-gray-700'}`}
                  >
                    {g.name}
                  </button>
                  <button onClick={() => doDeleteGroup(g)} className="opacity-0 group-hover:opacity-100 px-2 text-gray-300 hover:text-red-500 transition">
                    <Trash size={14} />
                  </button>
                </div>
              ))}
              {groups.length === 0 && <p className="px-3 py-4 text-xs text-gray-400">No groups yet. Create one below.</p>}
            </div>
            {/* create */}
            <div className="mt-2 pt-2 border-t border-gray-100 flex gap-1.5">
              <input
                value={newGroup} onChange={(e) => setNewGroup(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && doCreateGroup()}
                placeholder="New group / cohort…"
                className="flex-1 min-w-0 px-2.5 py-1.5 text-sm border border-gray-200 rounded-lg"
              />
              <button onClick={doCreateGroup} disabled={creating || !newGroup.trim()}
                className="shrink-0 px-2.5 py-1.5 rounded-lg bg-gray-900 text-white disabled:opacity-40">
                <Plus size={16} />
              </button>
            </div>
          </div>
        </div>

        {/* Roster + group detail */}
        <div className="lg:col-span-3 space-y-4">
          {/* selected-group course access */}
          {selectedGroup && (
            <div className="bg-white rounded-xl shadow-xs border border-gray-100 p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <p className="text-xs font-bold uppercase tracking-wide text-indigo-500">Course access · {selectedGroup.name}</p>
                  <p className="text-xs text-gray-400">Only members of this group can access the courses linked here.</p>
                </div>
                <button onClick={() => setCourseModal(true)} className="text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 px-3 py-1.5 rounded-lg flex items-center gap-1.5">
                  <BookOpen size={13} /> Manage courses
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {linkedCourseUuids.length === 0 && <span className="text-xs text-gray-400">No courses linked — this group doesn’t gate any course yet.</span>}
                {linkedCourseUuids.map((u) => (
                  <span key={u} className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-700 rounded-full pl-2.5 pr-1 py-1">
                    <GraduationCap size={12} /> {courseName(u)}
                    <button onClick={() => toggleCourse(u, true)} className="ml-0.5 text-gray-400 hover:text-red-500"><X size={12} /></button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* toolbar */}
          <div className="bg-white rounded-xl shadow-xs border border-gray-100">
            <div className="flex items-center gap-3 p-3 border-b border-gray-100">
              <div className="relative flex-1 max-w-sm">
                <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                  placeholder="Search members by name or email…"
                  className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg"
                />
              </div>
              <span className="text-xs text-gray-400">{total} {selectedGroup ? 'in group' : 'members'}</span>
            </div>

            {/* bulk bar */}
            {picked.size > 0 && (
              <div className="flex items-center gap-2 px-3 py-2 bg-indigo-50 border-b border-indigo-100 text-sm">
                <span className="font-semibold text-indigo-800">{picked.size} selected</span>
                {selectedGroup ? (
                  <button onClick={() => removePickedFrom(selectedGroup)} className="ml-auto px-3 py-1.5 rounded-lg bg-white border border-gray-200 text-gray-700 text-xs font-semibold hover:bg-gray-50">
                    Remove from “{selectedGroup.name}”
                  </button>
                ) : <span className="ml-auto" />}
                <div className="relative">
                  <select
                    onChange={(e) => { const g = groups.find((x) => String(x.id) === e.target.value); if (g) addPickedTo(g); e.target.value = '' }}
                    defaultValue=""
                    className="px-3 py-1.5 rounded-lg bg-gray-900 text-white text-xs font-semibold cursor-pointer"
                  >
                    <option value="" disabled>Add to group…</option>
                    {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                </div>
              </div>
            )}

            {/* table */}
            {usingPeople ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-100">
                  <th className="px-3 py-2">Member</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2 text-center">Completed</th>
                  <th className="px-3 py-2 text-center">Certs</th>
                  <th className="px-3 py-2 text-right">Spend</th>
                </tr>
              </thead>
              <tbody>
                {people.map((p: any) => (
                  <tr key={p.user_id} className="border-b border-gray-50 hover:bg-gray-50/60">
                    <td className="px-3 py-2">
                      <button onClick={() => setProfileUserId(p.user_id)} className="font-medium text-gray-800 hover:text-indigo-600 hover:underline text-left">{p.name || p.email}</button>
                    </td>
                    <td className="px-3 py-2 text-gray-500">{p.email}</td>
                    <td className="px-3 py-2 text-center text-gray-600">{p.completed}/{p.enrolled}</td>
                    <td className="px-3 py-2 text-center text-gray-600">{p.certificates}</td>
                    <td className="px-3 py-2 text-right text-gray-600">${p.spend}</td>
                  </tr>
                ))}
                {people.length === 0 && !peopleFetching && (
                  <tr><td colSpan={5} className="px-3 py-10 text-center text-gray-400 text-sm">No people found</td></tr>
                )}
              </tbody>
            </table>
            ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-100">
                  <th className="px-3 py-2 w-8"><input type="checkbox" checked={allChecked} onChange={toggleAll} /></th>
                  <th className="px-3 py-2">Member</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Groups</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const u = r.user
                  const avatar = u.avatar_image ? getUserAvatarMediaDirectory(u.user_uuid, u.avatar_image) : null
                  return (
                    <tr key={u.id} className="border-b border-gray-50 hover:bg-gray-50/60">
                      <td className="px-3 py-2"><input type="checkbox" checked={picked.has(u.id)} onChange={() => {
                        const n = new Set(picked); n.has(u.id) ? n.delete(u.id) : n.add(u.id); setPicked(n)
                      }} /></td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-full bg-gray-200 overflow-hidden shrink-0 flex items-center justify-center text-[10px] text-gray-500">
                            {avatar ? <img src={avatar} alt="" className="w-full h-full object-cover" /> : (u.first_name?.[0] || u.username?.[0] || '?')}
                          </div>
                          <button onClick={() => setProfileUserId(u.id)} className="font-medium text-gray-800 hover:text-indigo-600 hover:underline text-left">
                            {[u.first_name, u.last_name].filter(Boolean).join(' ') || u.username}
                          </button>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-gray-500">{u.email}</td>
                      <td className="px-3 py-2 text-gray-500 capitalize">{r.role?.name || '—'}</td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {(r.usergroups || []).map((g: any) => (
                            <span key={g.id} className="text-[11px] bg-indigo-50 text-indigo-700 rounded-full px-2 py-0.5">{g.name}</span>
                          ))}
                          {(!r.usergroups || r.usergroups.length === 0) && <span className="text-xs text-gray-300">—</span>}
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {rows.length === 0 && !isFetching && (
                  <tr><td colSpan={5} className="px-3 py-10 text-center text-gray-400 text-sm">No members found</td></tr>
                )}
              </tbody>
            </table>
            )}

            {/* pagination */}
            <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100">
              <span className="text-xs text-gray-400">Page {page} of {pages}</span>
              <div className="flex gap-1">
                <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="p-1.5 rounded-lg border border-gray-200 disabled:opacity-30"><CaretLeft size={14} /></button>
                <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="p-1.5 rounded-lg border border-gray-200 disabled:opacity-30"><CaretRight size={14} /></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Course picker modal */}
      {courseModal && selectedGroup && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setCourseModal(false)}>
          <div className="bg-white rounded-2xl w-full max-w-lg max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="p-4 border-b border-gray-100 flex items-center justify-between">
              <div>
                <h3 className="font-bold text-gray-900">Courses for “{selectedGroup.name}”</h3>
                <p className="text-xs text-gray-400">Checked courses are gated to this group’s members.</p>
              </div>
              <button onClick={() => setCourseModal(false)} className="text-gray-400 hover:text-gray-700"><X size={18} /></button>
            </div>
            <div className="p-2 overflow-y-auto">
              {courses.map((c) => {
                const linked = linkedCourseUuids.includes(c.course_uuid)
                return (
                  <button key={c.course_uuid} onClick={() => toggleCourse(c.course_uuid, linked)}
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-50 text-left">
                    <span className={`w-5 h-5 rounded border flex items-center justify-center ${linked ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-gray-300'}`}>
                      {linked && <Check size={12} weight="bold" />}
                    </span>
                    <span className="text-sm text-gray-800">{c.name}</span>
                  </button>
                )
              })}
              {courses.length === 0 && <p className="p-4 text-sm text-gray-400 text-center">No courses found</p>}
            </div>
          </div>
        </div>
      )}

      {profileUserId && (
        <MemberProfile userId={profileUserId} onClose={() => setProfileUserId(null)} />
      )}
    </div>
  )
}

export default MembersManager

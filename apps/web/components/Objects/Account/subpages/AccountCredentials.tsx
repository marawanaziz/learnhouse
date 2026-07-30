'use client'

import React from 'react'
import {
  BadgeCheck,
  CheckCircle2,
  Download,
  ExternalLink,
  FileCheck2,
  FileText,
  GraduationCap,
  Loader2,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getAPIUrl, getUriWithOrg } from '@services/config/config'

type CredentialType = 'birth' | 'postpartum'

type Issuance = {
  id: number
  credential_type: CredentialType
  credential_level: 'one_year_provisional' | 'three_year_full'
  term_years: number
  status: string
  effective_at: string
  expires_at: string
  public_credential_id: string
  verification_token: string
  source: string
}

type ApplicationItem = {
  id: number
  training_title: string
  provider: string
  completion_date: string
  claimed_ceu: number
  approved_ceu?: number | null
  admin_note?: string
  documents: Array<{
    id: number
    filename: string
    content_type: string
    byte_size: number
  }>
}

type CredentialApplication = {
  id: number
  public_uuid: string
  credential_type: CredentialType
  status: 'draft' | 'submitted' | 'approved' | 'declined'
  claimed_ceu_total: number
  approved_ceu_total: number
  submitted_at: string
  reviewed_at: string
  decline_reason: string
  approved_issuance_id?: number | null
  created_at: string
  items: ApplicationItem[]
}

type Hub = {
  member: { id: number; name: string; email: string }
  training_certificates: Array<{
    id: number
    uuid: string
    course: string
    issued_at: string
    credential_type: CredentialType | ''
    is_cross_cert: boolean
    verify_url: string
  }>
  issuances: Issuance[]
  eligibility: Record<
    CredentialType,
    { eligible: boolean; current?: Issuance | null }
  >
  applications: CredentialApplication[]
  ceu_total: number
  ceu_threshold: number
}

const credentialLabel = (value: CredentialType) =>
  value === 'birth' ? 'Birth Doula' : 'Postpartum Doula'

const levelLabel = (value: Issuance['credential_level']) =>
  value === 'one_year_provisional'
    ? 'One-year provisional'
    : 'Three-year full'

const formatDate = (value?: string) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

const statusClasses = (status: string) => {
  if (['approved', 'full', 'provisional'].includes(status)) {
    return 'bg-emerald-50 text-emerald-700 ring-emerald-600/15'
  }
  if (['submitted', 'draft'].includes(status)) {
    return 'bg-amber-50 text-amber-700 ring-amber-600/15'
  }
  return 'bg-rose-50 text-rose-700 ring-rose-600/15'
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${statusClasses(status)}`}
    >
      {status.replaceAll('_', ' ')}
    </span>
  )
}

function Section({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: React.ReactNode
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="mb-5 flex items-start gap-3">
        <span className="rounded-xl bg-[#ebf7ff] p-2.5 text-[#113d5d]">
          {icon}
        </span>
        <div>
          <h2 className="text-lg font-bold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

export default function AccountCredentials({
  orgslug,
}: {
  orgslug: string
}) {
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const base = `${getAPIUrl()}bbu/credentials`
  const [hub, setHub] = React.useState<Hub | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [busy, setBusy] = React.useState('')
  const [selectedIssuance, setSelectedIssuance] =
    React.useState<Issuance | null>(null)
  const [activeDraftUuid, setActiveDraftUuid] = React.useState('')
  const [editingItem, setEditingItem] =
    React.useState<ApplicationItem | null>(null)
  const [training, setTraining] = React.useState({
    training_title: '',
    provider: '',
    completion_date: '',
    claimed_ceu: '',
  })

  const api = React.useCallback(
    async (path: string, init: RequestInit = {}) => {
      const headers = new Headers(init.headers || {})
      if (!(init.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json')
      }
      if (token) headers.set('Authorization', `Bearer ${token}`)
      const response = await fetch(`${base}${path}`, {
        ...init,
        headers,
        credentials: 'include',
      })
      const contentType = response.headers.get('content-type') || ''
      const data = contentType.includes('application/json')
        ? await response.json()
        : null
      if (!response.ok) {
        throw new Error(data?.detail || 'Something went wrong. Please try again.')
      }
      return data
    },
    [base, token]
  )

  const load = React.useCallback(async () => {
    if (!token) return
    try {
      setLoading(true)
      setHub(await api('/me'))
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setLoading(false)
    }
  }, [api, token])

  React.useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const draftApplications =
    hub?.applications.filter((application) => application.status === 'draft') ||
    []
  const openDraft =
    draftApplications.find(
      (application) => application.public_uuid === activeDraftUuid
    ) || draftApplications[0]

  const startApplication = async (credentialType: CredentialType) => {
    try {
      setBusy(`start-${credentialType}`)
      const application = (await api('/applications', {
        method: 'POST',
        body: JSON.stringify({ credential_type: credentialType }),
      })) as CredentialApplication
      setActiveDraftUuid(application.public_uuid)
      await load()
      toast.success('Application draft created')
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setBusy('')
    }
  }

  const resetTraining = () => {
    setEditingItem(null)
    setTraining({
      training_title: '',
      provider: '',
      completion_date: '',
      claimed_ceu: '',
    })
  }

  const saveTraining = async () => {
    if (!openDraft || openDraft.status !== 'draft') return
    try {
      setBusy('save-item')
      const payload = {
        ...training,
        claimed_ceu: Number(training.claimed_ceu),
      }
      if (editingItem) {
        await api(
          `/applications/${openDraft.public_uuid}/items/${editingItem.id}`,
          { method: 'PUT', body: JSON.stringify(payload) }
        )
      } else {
        await api(`/applications/${openDraft.public_uuid}/items`, {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      }
      resetTraining()
      await load()
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setBusy('')
    }
  }

  const editTraining = (item: ApplicationItem) => {
    setEditingItem(item)
    setTraining({
      training_title: item.training_title,
      provider: item.provider,
      completion_date: item.completion_date,
      claimed_ceu: String(item.claimed_ceu),
    })
  }

  const deleteTraining = async (itemId: number) => {
    if (!openDraft || !confirm('Remove this CEU training and its documents?')) {
      return
    }
    try {
      setBusy(`delete-${itemId}`)
      await api(`/applications/${openDraft.public_uuid}/items/${itemId}`, {
        method: 'DELETE',
      })
      if (editingItem?.id === itemId) resetTraining()
      await load()
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setBusy('')
    }
  }

  const uploadDocument = async (itemId: number, file?: File) => {
    if (!openDraft || !file) return
    const form = new FormData()
    form.append('file', file)
    try {
      setBusy(`upload-${itemId}`)
      await api(
        `/applications/${openDraft.public_uuid}/items/${itemId}/documents`,
        { method: 'POST', body: form }
      )
      await load()
      toast.success('Document uploaded')
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setBusy('')
    }
  }

  const deleteDocument = async (documentId: number) => {
    if (!openDraft || !confirm('Remove this supporting document?')) return
    try {
      setBusy(`document-${documentId}`)
      await api(
        `/applications/${openDraft.public_uuid}/documents/${documentId}`,
        { method: 'DELETE' }
      )
      await load()
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setBusy('')
    }
  }

  const submitApplication = async () => {
    if (
      !openDraft ||
      !confirm(
        'Submit this application for review? You will not be able to edit it after submission.'
      )
    ) {
      return
    }
    try {
      setBusy('submit')
      await api(`/applications/${openDraft.public_uuid}/submit`, {
        method: 'POST',
      })
      await load()
      toast.success('Application submitted')
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setBusy('')
    }
  }

  const openCertificatePreview = (issuance: Issuance) => {
    setSelectedIssuance(issuance)
  }

  if (loading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center rounded-2xl bg-white shadow-sm">
        <Loader2 className="animate-spin text-[#113d5d]" size={30} />
      </div>
    )
  }

  if (!hub) {
    return (
      <div className="rounded-2xl bg-white p-8 text-center text-slate-500 shadow-sm">
        Your credential record could not be loaded.
      </div>
    )
  }

  const claimedTotal =
    openDraft?.items.reduce((sum, item) => sum + item.claimed_ceu, 0) || 0
  const everyItemDocumented = Boolean(
    openDraft?.items.length &&
      openDraft.items.every((item) => item.documents.length > 0)
  )

  return (
    <div className="space-y-5">
      <div className="overflow-hidden rounded-2xl bg-[#113d5d] px-6 py-7 text-white shadow-sm sm:px-8">
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-center">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#b9d5e7]">
              Professional credentials
            </p>
            <h1 className="mt-2 font-serif text-3xl font-bold">
              Your BBU credential record
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#dcecf5]">
              Training certificates, one-year credentials, three-year
              credentials, and CEU applications live together here.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 text-center">
            <div className="rounded-xl bg-white/10 px-5 py-3">
              <div className="text-2xl font-black">{hub.issuances.length}</div>
              <div className="text-xs text-[#dcecf5]">credential history</div>
            </div>
            <div className="rounded-xl bg-white/10 px-5 py-3">
              <div className="text-2xl font-black">{hub.ceu_total}</div>
              <div className="text-xs text-[#dcecf5]">approved CEUs</div>
            </div>
          </div>
        </div>
      </div>

      <Section
        icon={<ShieldCheck size={20} />}
        title="Professional credential history"
        subtitle="Every issuance remains available, including replaced or expired credentials."
      >
        {hub.issuances.length ? (
          <div className="grid gap-3">
            {hub.issuances.map((issuance) => (
              <div
                key={issuance.id}
                className="flex flex-col gap-4 rounded-xl border border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex gap-3">
                  <span className="mt-0.5 rounded-full bg-[#ebf7ff] p-2 text-[#113d5d]">
                    <BadgeCheck size={20} />
                  </span>
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-slate-900">
                        {credentialLabel(issuance.credential_type)}
                      </h3>
                      {hub.issuances.find(
                        (candidate) =>
                          candidate.credential_type === issuance.credential_type
                      )?.id === issuance.id && (
                        <span className="rounded-full bg-[#113d5d] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                          Latest
                        </span>
                      )}
                      <StatusPill status={issuance.status} />
                    </div>
                    <p className="mt-1 text-sm font-medium text-slate-600">
                      {levelLabel(issuance.credential_level)}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {issuance.public_credential_id} ·{' '}
                      {formatDate(issuance.effective_at)} –{' '}
                      {formatDate(issuance.expires_at)}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <a
                    href={`${base}/verify/${issuance.verification_token}/page`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    Verify <ExternalLink size={14} />
                  </a>
                  <button
                    onClick={() => openCertificatePreview(issuance)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#113d5d] px-3 py-2 text-sm font-semibold text-white hover:bg-[#0d304a]"
                  >
                    <Download size={15} /> Certificate
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
            No professional credential issuances have been recorded yet.
          </p>
        )}
      </Section>

      <Section
        icon={<FileCheck2 size={20} />}
        title="CEU credential applications"
        subtitle="Applicants must already have qualifying BBU training or credential history."
      >
        <div className="mb-5 grid gap-3 sm:grid-cols-2">
          {(['birth', 'postpartum'] as CredentialType[]).map((type) => {
            const eligibility = hub.eligibility[type]
            const existing = hub.applications.find(
              (application) =>
                application.credential_type === type &&
                ['draft', 'submitted'].includes(application.status)
            )
            return (
              <div
                key={type}
                className="rounded-xl border border-slate-200 p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-bold text-slate-900">
                      {credentialLabel(type)}
                    </h3>
                    <p className="mt-1 text-xs text-slate-500">
                      {eligibility?.eligible
                        ? 'Prior BBU history confirmed'
                        : 'Prior BBU training or certification required'}
                    </p>
                  </div>
                  {eligibility?.eligible ? (
                    existing?.status === 'draft' ? (
                      <button
                        onClick={() => setActiveDraftUuid(existing.public_uuid)}
                        className="rounded-lg border border-[#b9d5e7] px-3 py-2 text-sm font-semibold text-[#113d5d] hover:bg-[#f7fbfe]"
                      >
                        Continue draft
                      </button>
                    ) : existing ? (
                      <StatusPill status={existing.status} />
                    ) : (
                      <button
                        onClick={() => void startApplication(type)}
                        disabled={Boolean(busy)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-[#113d5d] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                      >
                        {busy === `start-${type}` ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Plus size={14} />
                        )}
                        Apply through CEUs
                      </button>
                    )
                  ) : (
                    <span className="text-xs font-semibold text-slate-400">
                      Not eligible
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {openDraft?.status === 'draft' && (
          <div className="rounded-2xl border border-[#b9d5e7] bg-[#f7fbfe] p-4 sm:p-5">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <div>
                <h3 className="font-bold text-slate-900">
                  {credentialLabel(openDraft.credential_type)} application draft
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  Add every outside training separately and attach its proof.
                </p>
              </div>
              <div className="rounded-xl bg-white px-4 py-2 text-center ring-1 ring-slate-200">
                <span className="text-xl font-black text-[#113d5d]">
                  {claimedTotal}
                </span>
                <span className="ml-1 text-sm text-slate-500">
                  / {hub.ceu_threshold} CEUs
                </span>
              </div>
            </div>

            <div className="mt-5 grid gap-3 rounded-xl bg-white p-4 ring-1 ring-slate-200 sm:grid-cols-2">
              <input
                value={training.training_title}
                onChange={(event) =>
                  setTraining((value) => ({
                    ...value,
                    training_title: event.target.value,
                  }))
                }
                placeholder="Training title"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              />
              <input
                value={training.provider}
                onChange={(event) =>
                  setTraining((value) => ({
                    ...value,
                    provider: event.target.value,
                  }))
                }
                placeholder="Training provider"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              />
              <label className="text-xs font-semibold text-slate-500">
                Completion date
                <input
                  type="date"
                  value={training.completion_date}
                  onChange={(event) =>
                    setTraining((value) => ({
                      ...value,
                      completion_date: event.target.value,
                    }))
                  }
                  className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-900"
                />
              </label>
              <label className="text-xs font-semibold text-slate-500">
                CEUs claimed
                <input
                  type="number"
                  min="1"
                  value={training.claimed_ceu}
                  onChange={(event) =>
                    setTraining((value) => ({
                      ...value,
                      claimed_ceu: event.target.value,
                    }))
                  }
                  className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-900"
                />
              </label>
              <div className="flex gap-2 sm:col-span-2">
                <button
                  onClick={() => void saveTraining()}
                  disabled={
                    busy === 'save-item' ||
                    !training.training_title ||
                    !training.provider ||
                    !training.completion_date ||
                    Number(training.claimed_ceu) <= 0
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#113d5d] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
                >
                  {busy === 'save-item' && (
                    <Loader2 size={14} className="animate-spin" />
                  )}
                  {editingItem ? 'Save training' : 'Add training'}
                </button>
                {editingItem && (
                  <button
                    onClick={resetTraining}
                    className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {openDraft.items.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl bg-white p-4 ring-1 ring-slate-200"
                >
                  <div className="flex flex-col justify-between gap-3 sm:flex-row">
                    <div>
                      <h4 className="font-bold text-slate-900">
                        {item.training_title}
                      </h4>
                      <p className="mt-1 text-xs text-slate-500">
                        {item.provider} · {formatDate(item.completion_date)} ·{' '}
                        {item.claimed_ceu} CEUs
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => editTraining(item)}
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => void deleteTraining(item.id)}
                        className="rounded-lg border border-rose-200 p-2 text-rose-600"
                        aria-label="Delete training"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {item.documents.map((document) => (
                      <span
                        key={document.id}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs text-slate-700"
                      >
                        <FileText size={13} />
                        <a
                          href={`${base}/applications/${openDraft.public_uuid}/documents/${document.id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold hover:underline"
                        >
                          {document.filename}
                        </a>
                        <button
                          onClick={() => void deleteDocument(document.id)}
                          className="text-slate-400 hover:text-rose-600"
                          aria-label="Remove document"
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))}
                    <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-dashed border-[#6da0db] px-3 py-1.5 text-xs font-semibold text-[#113d5d]">
                      {busy === `upload-${item.id}` ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Upload size={13} />
                      )}
                      Upload proof
                      <input
                        type="file"
                        className="hidden"
                        accept=".pdf,.jpg,.jpeg,.png"
                        onChange={(event) => {
                          void uploadDocument(item.id, event.target.files?.[0])
                          event.target.value = ''
                        }}
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-5 flex flex-col justify-between gap-3 rounded-xl bg-white p-4 ring-1 ring-slate-200 sm:flex-row sm:items-center">
              <div className="text-sm text-slate-600">
                {claimedTotal < hub.ceu_threshold ? (
                  <span>
                    Add {hub.ceu_threshold - claimedTotal} more claimed CEUs.
                  </span>
                ) : !everyItemDocumented ? (
                  <span>Attach proof to every training before submitting.</span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-700">
                    <CheckCircle2 size={16} /> Ready to submit
                  </span>
                )}
              </div>
              <button
                onClick={() => void submitApplication()}
                disabled={
                  busy === 'submit' ||
                  claimedTotal < hub.ceu_threshold ||
                  !everyItemDocumented
                }
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[#113d5d] px-5 py-2.5 text-sm font-bold text-white disabled:opacity-40"
              >
                {busy === 'submit' && (
                  <Loader2 size={15} className="animate-spin" />
                )}
                Submit for review
              </button>
            </div>
          </div>
        )}

        <div className="mt-5 space-y-3">
          {hub.applications
            .filter((application) => application.status !== 'draft')
            .map((application) => (
              <div
                key={application.id}
                className="rounded-xl border border-slate-200 p-4"
              >
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-bold text-slate-900">
                        {credentialLabel(application.credential_type)}
                      </h3>
                      <StatusPill status={application.status} />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      Submitted {formatDate(application.submitted_at)} ·{' '}
                      {application.claimed_ceu_total} claimed CEUs
                      {application.status === 'approved' &&
                        ` · ${application.approved_ceu_total} approved`}
                    </p>
                  </div>
                </div>
                {application.status === 'declined' &&
                  application.decline_reason && (
                    <div className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
                      <strong>Review reason:</strong>{' '}
                      {application.decline_reason}
                    </div>
                  )}
              </div>
            ))}
        </div>
      </Section>

      <Section
        icon={<GraduationCap size={20} />}
        title="Training certificates"
        subtitle="Course-completion certificates are evidence of training; professional credentials are listed above."
      >
        {hub.training_certificates.length ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {hub.training_certificates.map((certificate) => (
              <div
                key={certificate.id}
                className="rounded-xl border border-slate-200 p-4"
              >
                <h3 className="font-bold text-slate-900">
                  {certificate.course}
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  {certificate.is_cross_cert
                    ? 'Cross-certification training'
                    : 'Course certificate'}{' '}
                  · {formatDate(certificate.issued_at)}
                </p>
                <a
                  href={getUriWithOrg(orgslug, certificate.verify_url)}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-[#113d5d] hover:underline"
                >
                  Open training certificate <ExternalLink size={13} />
                </a>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
            No training certificates have been recorded yet.
          </p>
        )}
      </Section>

      {selectedIssuance && (
        <div className="fixed inset-0 z-modal flex items-center justify-center bg-slate-950/60 p-3 backdrop-blur-sm">
          <div className="w-full max-w-5xl overflow-auto rounded-2xl bg-white p-3 shadow-2xl">
            <div className="mb-3 flex items-center justify-between px-2">
              <div>
                <h2 className="font-bold text-slate-900">
                  {selectedIssuance.public_credential_id}
                </h2>
                <p className="text-xs text-slate-500">
                  Preview of the downloadable certificate
                </p>
              </div>
              <button
                onClick={() => setSelectedIssuance(null)}
                className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
                aria-label="Close certificate preview"
              >
                <X size={19} />
              </button>
            </div>
            <div
              id="bbu-professional-certificate"
              className="relative mx-auto aspect-[11/8.5] min-w-[820px] overflow-hidden border-[12px] border-[#113d5d] bg-white p-10 text-center"
              style={{
                backgroundImage:
                  'radial-gradient(circle at 15% 15%, #ebf7ff 0, transparent 25%), radial-gradient(circle at 85% 85%, #dcecf5 0, transparent 28%)',
              }}
            >
              <div className="flex h-full flex-col items-center justify-between border-2 border-[#6da0db] px-12 py-8">
                <div>
                  <div className="text-sm font-black uppercase tracking-[0.28em] text-[#6da0db]">
                    Birth &amp; Baby University
                  </div>
                  <h2 className="mt-3 font-serif text-4xl font-bold text-[#113d5d]">
                    Certificate of Professional Credential
                  </h2>
                </div>
                <div>
                  <p className="text-base text-slate-500">This certifies that</p>
                  <div className="mt-2 border-b-2 border-[#6da0db] px-12 pb-2 font-serif text-4xl font-bold text-slate-900">
                    {hub.member.name}
                  </div>
                  <p className="mt-5 text-lg text-slate-600">
                    holds the Birth &amp; Baby University credential
                  </p>
                  <h3 className="mt-2 font-serif text-3xl font-bold text-[#113d5d]">
                    Certified {credentialLabel(selectedIssuance.credential_type)}
                  </h3>
                  <p className="mt-2 text-sm font-semibold uppercase tracking-wide text-[#6da0db]">
                    {levelLabel(selectedIssuance.credential_level)}
                  </p>
                </div>
                <div className="grid w-full grid-cols-[1fr_auto_1fr] items-end gap-8">
                  <div className="text-left text-sm text-slate-600">
                    <div>
                      <strong>Effective:</strong>{' '}
                      {formatDate(selectedIssuance.effective_at)}
                    </div>
                    <div className="mt-1">
                      <strong>Valid through:</strong>{' '}
                      {formatDate(selectedIssuance.expires_at)}
                    </div>
                    <div className="mt-1">
                      <strong>Credential ID:</strong>{' '}
                      {selectedIssuance.public_credential_id}
                    </div>
                  </div>
                  <img
                    src={`${base}/verify/${selectedIssuance.verification_token}/qr`}
                    alt="Credential verification QR code"
                    crossOrigin="anonymous"
                    className="h-24 w-24"
                  />
                  <div className="text-right">
                    <div className="font-serif text-xl font-bold text-[#113d5d]">
                      Anna Rodney
                    </div>
                    <div className="mt-1 border-t border-slate-400 pt-1 text-xs text-slate-500">
                      Birth &amp; Baby University
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="mt-3 flex justify-end px-2">
              <a
                href={`${base}/verify/${selectedIssuance.verification_token}/certificate.pdf`}
                download={`${selectedIssuance.public_credential_id}.pdf`}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#113d5d] px-4 py-2.5 text-sm font-bold text-white"
              >
                <Download size={15} /> Download PDF
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

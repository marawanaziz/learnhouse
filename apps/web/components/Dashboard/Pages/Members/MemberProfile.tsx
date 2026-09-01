'use client'
import React from 'react'
import { getAPIUrl } from '@services/config/config'
import { deleteUserCertificate, deleteUserCredentialIssuance } from '@services/admin/certificates'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { X, GraduationCap, ClipboardCheck, Award, BadgeCheck, Users, CreditCard, ChevronDown, ExternalLink, Download } from 'lucide-react'

const NAVY = '#113d5d'
const professionalCredentialLabel = (type: string) => type === 'birth' ? 'Birth Doula' : 'Postpartum Doula'
const professionalCredentialLevel = (level: string) => level === 'one_year_provisional' ? 'One-year provisional' : 'Three-year full'

function Bar({ pct }: { pct: number }) {
  return (
    <div className="w-full h-2 rounded-full bg-slate-100 overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, background: NAVY }} />
    </div>
  )
}

function Card({ icon, title, count, children }: any) {
  return (
    <div className="bg-white rounded-2xl ring-1 ring-slate-900/[0.06] shadow-sm p-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[#113d5d]">{icon}</span>
        <h3 className="font-semibold text-slate-800">{title}</h3>
        {count != null && <span className="text-xs font-semibold text-slate-400">{count}</span>}
      </div>
      {children}
    </div>
  )
}

export default function MemberProfile({ userId, orgSlug, onClose }: { userId: number; orgSlug: string; onClose: () => void }) {
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const [d, setD] = React.useState<any>(null)
  const [loading, setLoading] = React.useState(true)
  const [openQuiz, setOpenQuiz] = React.useState<number | null>(null)
  const [certificatePendingDelete, setCertificatePendingDelete] = React.useState<any>(null)
  const [deletingCertificateUuid, setDeletingCertificateUuid] = React.useState<string | null>(null)
  const [credentialPendingDelete, setCredentialPendingDelete] = React.useState<any>(null)
  const [deletingCredentialId, setDeletingCredentialId] = React.useState<number | null>(null)
  const [certificateError, setCertificateError] = React.useState<string | null>(null)

  const loadProfile = React.useCallback(async () => {
    const response = await fetch(`${getAPIUrl()}bbu/people/${userId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: 'include',
      cache: 'no-store',
    })
    if (!response.ok) throw new Error('Could not refresh this member profile.')
    return response.json()
  }, [userId, token])

  React.useEffect(() => {
    let alive = true
    setLoading(true)
    loadProfile().then(j => { if (alive) { setD(j); setLoading(false) } })
      .catch(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [loadProfile])

  const requestCertificateDelete = (certificate: any) => {
    setCertificateError(null)
    setCertificatePendingDelete(certificate)
  }

  const requestCredentialDelete = (credential: any) => {
    if (!credential?.id) return
    setCertificateError(null)
    setCredentialPendingDelete(credential)
  }

  const confirmCertificateDelete = async () => {
    const certificate = certificatePendingDelete
    if (!certificate || deletingCertificateUuid) return
    const uuid = certificate.uuid
    setDeletingCertificateUuid(uuid)
    setCertificateError(null)
    try {
      await deleteUserCertificate(orgSlug, userId, uuid, token)
      // The server has succeeded, so remove this exact row before the fresh readback.
      setD((previous: any) => previous ? {
        ...previous,
        certificates: (previous.certificates || []).filter((item: any) => item.uuid !== uuid),
      } : previous)
      setCertificatePendingDelete(null)
      try {
        setD(await loadProfile())
      } catch {
        setCertificateError('Certificate deleted, but the list could not be refreshed. Please reload the profile.')
      }
    } catch (error: any) {
      setCertificateError(error?.message || 'Could not delete the certificate. No changes were made.')
    } finally {
      setDeletingCertificateUuid(null)
    }
  }

  const confirmCredentialDelete = async () => {
    const credential = credentialPendingDelete
    if (!credential || deletingCredentialId) return
    const issuanceId = Number(credential.id)
    setDeletingCredentialId(issuanceId)
    setCertificateError(null)
    try {
      await deleteUserCredentialIssuance(orgSlug, userId, issuanceId, token)
      setCredentialPendingDelete(null)
      try {
        setD(await loadProfile())
      } catch {
        setCertificateError('Credential revoked, but the list could not be refreshed. Please reload the profile.')
      }
    } catch (error: any) {
      setCertificateError(error?.message || 'Could not revoke the credential. No changes were made.')
    } finally {
      setDeletingCredentialId(null)
    }
  }

  const credentialIssuances = d?.credential_issuances || []

  return (
    <div className="fixed inset-0 z-modal bg-slate-900/40 backdrop-blur-sm flex justify-end" onClick={onClose}>
      <div className="w-full max-w-3xl min-w-0 h-full bg-slate-50 shadow-2xl overflow-x-hidden overflow-y-auto" onClick={e => e.stopPropagation()}>
        {/* header */}
        <div className="sticky top-0 z-10 bg-white border-b border-slate-100 px-6 py-4 flex items-center justify-between">
          <div>
            <div className="text-[1.35rem] font-semibold text-slate-900 leading-tight">{d?.name || 'Member'}</div>
            <div className="text-sm text-slate-500">{d?.email}</div>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex gap-2">
              <span className="px-3 py-1 rounded-full bg-[#ebf7ff] text-[#113d5d] text-xs font-semibold">${d?.lifetime_spend ?? 0} lifetime</span>
              <span className="px-3 py-1 rounded-full bg-[#ebf7ff] text-[#113d5d] text-xs font-semibold">{d?.ceu_total ?? 0} CEU</span>
            </div>
            <button onClick={onClose} className="p-2 rounded-lg hover:bg-slate-100 text-slate-500"><X size={20} /></button>
          </div>
        </div>

        {loading ? (
          <div className="p-10 text-center text-slate-400">Loading profile…</div>
        ) : !d || d.detail ? (
          <div className="p-10 text-center text-slate-400">Couldn't load this profile.</div>
        ) : (
          <div className="min-w-0 p-6 space-y-5">
            {certificateError && (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                {certificateError}
              </div>
            )}
            {/* Enrollments & progress */}
            <Card icon={<GraduationCap size={18} />} title="Courses & progress" count={d.enrollments?.length}>
              {d.enrollments?.length ? (
                <div className="space-y-3">
                  {d.enrollments.map((e: any, i: number) => (
                    <div key={i}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="font-medium text-slate-700">{e.course}{e.has_certificate && <BadgeCheck size={14} className="inline ml-1 text-emerald-500" />}</span>
                        <span className="text-slate-400 text-xs">{e.completed_steps}/{e.total_steps} · {e.progress}% · {e.status}</span>
                      </div>
                      <Bar pct={e.progress} />
                    </div>
                  ))}
                </div>
              ) : <p className="text-sm text-slate-400">No enrollments.</p>}
            </Card>

            {/* Quiz results with answers */}
            <Card icon={<ClipboardCheck size={18} />} title="Quiz results" count={d.quizzes?.length}>
              {d.quizzes?.length ? (
                <div className="divide-y divide-slate-100">
                  {d.quizzes.map((q: any, i: number) => (
                    <div key={i} className="py-2">
                      <button className="w-full flex items-center justify-between text-left" onClick={() => setOpenQuiz(openQuiz === i ? null : i)}>
                        <span className="text-sm font-medium text-slate-700">{q.activity}</span>
                        <span className="flex items-center gap-2 text-xs">
                          <span className={`px-2 py-0.5 rounded-full font-semibold ${q.passed ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>{q.score}% {q.passed ? 'pass' : 'fail'}</span>
                          <span className="text-slate-400">{q.correct}/{q.total} · try {q.attempts} · {q.date}</span>
                          <ChevronDown size={14} className={`text-slate-400 transition ${openQuiz === i ? 'rotate-180' : ''}`} />
                        </span>
                      </button>
                      {openQuiz === i && (
                        <div className="mt-2 space-y-2 pl-1">
                          {(q.answers || []).map((a: any, j: number) => (
                            <div key={j} className={`text-xs rounded-lg px-3 py-2 ${a.is_correct ? 'bg-emerald-50/60' : 'bg-red-50/60'}`}>
                              <div className="font-medium text-slate-700">{j + 1}. {a.question}</div>
                              <div className="text-slate-600 mt-0.5">Their answer: <b>{(a.your_answers || []).join(', ') || '—'}</b></div>
                              {!a.is_correct && <div className="text-emerald-700 mt-0.5">Correct: <b>{(a.correct_answers || []).join(', ')}</b></div>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : <p className="text-sm text-slate-400">No quiz submissions recorded yet.</p>}
            </Card>

            <div className="grid sm:grid-cols-2 gap-5 min-w-0">
              {/* Credentials */}
              <Card icon={<Award size={18} />} title="Credentials" count={credentialIssuances.length || d.credentials?.length}>
                {credentialIssuances.length ? credentialIssuances.map((c: any) => (
                  <div key={c.id} className="border-b border-slate-100 py-3 last:border-0">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold capitalize text-slate-700">{professionalCredentialLabel(c.credential_type)}</span>
                          {c.is_current && <span className="rounded-full bg-[#113d5d] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">Latest</span>}
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold capitalize text-slate-600">{c.status}</span>
                        </div>
                        <div className="mt-1 text-xs text-slate-400">
                          {professionalCredentialLevel(c.credential_level)} · {c.public_credential_id} · {String(c.effective_at || '').slice(0, 10)} – {String(c.expires_at || '').slice(0, 10)}
                        </div>
                      </div>
                      {c.status !== 'revoked' && c.stored_status !== 'revoked' && (
                        <button
                          type="button"
                          onClick={() => requestCredentialDelete(c)}
                          disabled={deletingCredentialId === c.id}
                          className="shrink-0 rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-wait disabled:opacity-50"
                          aria-label={`Delete professional credential ${professionalCredentialLabel(c.credential_type)}`}
                        >
                          {deletingCredentialId === c.id ? 'Deleting…' : 'Delete'}
                        </button>
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <a href={`${getAPIUrl()}bbu/credentials/verify/${encodeURIComponent(c.verification_token)}/page`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 font-semibold text-slate-600 hover:bg-slate-50">Verify <ExternalLink size={12} /></a>
                      <a href={`${getAPIUrl()}bbu/credentials/verify/${encodeURIComponent(c.verification_token)}/certificate.pdf`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 font-semibold text-slate-600 hover:bg-slate-50">Download PDF <Download size={12} /></a>
                    </div>
                  </div>
                )) : d.credentials?.length ? d.credentials.map((c: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1">
                    <span className="capitalize text-slate-700">{c.type} doula</span>
                    <span className="text-xs"><span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold capitalize">{c.status}</span> <span className="text-slate-400">exp {c.expires || '—'}</span></span>
                  </div>
                )) : <p className="text-sm text-slate-400">None.</p>}
              </Card>

              {/* Certificates */}
              <Card icon={<BadgeCheck size={18} />} title="Certificates" count={d.certificates?.length}>
                {d.certificates?.length ? d.certificates.map((c: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1">
                    <div className="min-w-0 flex items-center gap-2">
                      {c.verify_url ? (
                        <a href={c.verify_url} target="_blank" rel="noopener noreferrer"
                          className="text-slate-700 truncate pr-2 hover:text-sky-700 hover:underline">
                          {c.course}
                        </a>
                      ) : (
                        <span className="text-slate-700 truncate pr-2">{c.course}</span>
                      )}
                      <span className="text-xs text-slate-400 shrink-0">{c.issued}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => requestCertificateDelete(c)}
                      disabled={deletingCertificateUuid === c.uuid}
                      className="ml-2 shrink-0 rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-wait disabled:opacity-50"
                      aria-label={`Delete certificate ${c.course || c.uuid}`}
                    >
                      {deletingCertificateUuid === c.uuid ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                )) : <p className="text-sm text-slate-400">None.</p>}
              </Card>

              {/* Cohorts */}
              <Card icon={<Users size={18} />} title="Cohorts" count={d.cohorts?.length}>
                {d.cohorts?.length ? d.cohorts.map((c: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1">
                    <span className="text-slate-700 truncate pr-2">{c.cohort}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold capitalize shrink-0">{c.status}</span>
                  </div>
                )) : <p className="text-sm text-slate-400">None.</p>}
              </Card>

              {/* Purchases */}
              <Card icon={<CreditCard size={18} />} title="Purchases" count={d.purchases?.length}>
                {d.purchases?.length ? d.purchases.map((p: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1">
                    <span className="text-slate-700">${p.amount}</span>
                    <span className="text-xs"><span className={`px-2 py-0.5 rounded-full font-semibold capitalize ${p.status === 'paid' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{p.status}</span> <span className="text-slate-400">{p.date}</span></span>
                  </div>
                )) : <p className="text-sm text-slate-400">None.</p>}
              </Card>
            </div>
          </div>
        )}
      </div>
      {certificatePendingDelete && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4" onClick={() => !deletingCertificateUuid && setCertificatePendingDelete(null)}>
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-certificate-title"
            aria-describedby="delete-certificate-description"
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={event => event.stopPropagation()}
          >
            <h2 id="delete-certificate-title" className="text-lg font-semibold text-slate-900">Delete issued certificate?</h2>
            <p id="delete-certificate-description" className="mt-3 text-sm leading-6 text-slate-600">
              This removes the issued certificate for <strong>{d?.name || d?.email || 'this member'}</strong>.
              The certificate is <strong>{certificatePendingDelete.course || 'Certificate'}</strong> and its ID is <code className="break-all">{certificatePendingDelete.uuid}</code>.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                autoFocus
                onClick={() => setCertificatePendingDelete(null)}
                disabled={!!deletingCertificateUuid}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmCertificateDelete}
                disabled={!!deletingCertificateUuid}
                className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800 disabled:cursor-wait disabled:opacity-50"
              >
                {deletingCertificateUuid ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
      {credentialPendingDelete && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4" onClick={() => !deletingCredentialId && setCredentialPendingDelete(null)}>
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-professional-credential-title"
            aria-describedby="delete-professional-credential-description"
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={event => event.stopPropagation()}
          >
            <h2 id="delete-professional-credential-title" className="text-lg font-semibold text-slate-900">Delete professional credential?</h2>
            <p id="delete-professional-credential-description" className="mt-3 text-sm leading-6 text-slate-600">
              This revokes the issued certificate for <strong>{d?.name || d?.email || 'this member'}</strong>.
              The credential is <strong>{professionalCredentialLabel(credentialPendingDelete.credential_type)}</strong> ({professionalCredentialLevel(credentialPendingDelete.credential_level)}) with ID <code className="break-all">{credentialPendingDelete.public_credential_id}</code>.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                autoFocus
                onClick={() => setCredentialPendingDelete(null)}
                disabled={!!deletingCredentialId}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmCredentialDelete}
                disabled={!!deletingCredentialId}
                className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800 disabled:cursor-wait disabled:opacity-50"
              >
                {deletingCredentialId ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

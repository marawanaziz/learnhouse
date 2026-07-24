'use client'
import React from 'react'
import { getAPIUrl } from '@services/config/config'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { X, GraduationCap, ClipboardCheck, Award, BadgeCheck, Users, CreditCard, ChevronDown } from 'lucide-react'

const NAVY = '#113d5d'

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

export default function MemberProfile({ userId, onClose }: { userId: number; onClose: () => void }) {
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const [d, setD] = React.useState<any>(null)
  const [loading, setLoading] = React.useState(true)
  const [openQuiz, setOpenQuiz] = React.useState<number | null>(null)

  React.useEffect(() => {
    let alive = true
    setLoading(true)
    fetch(`${getAPIUrl()}bbu/people/${userId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: 'include',
    }).then(r => r.json()).then(j => { if (alive) { setD(j); setLoading(false) } })
      .catch(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [userId, token])

  return (
    <div className="fixed inset-0 z-modal bg-slate-900/40 backdrop-blur-sm flex justify-end" onClick={onClose}>
      <div className="w-full max-w-3xl h-full bg-slate-50 shadow-2xl overflow-y-auto" onClick={e => e.stopPropagation()}>
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
          <div className="p-6 space-y-5">
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

            <div className="grid sm:grid-cols-2 gap-5">
              {/* Credentials */}
              <Card icon={<Award size={18} />} title="Credentials" count={d.credentials?.length}>
                {d.credentials?.length ? d.credentials.map((c: any, i: number) => (
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
                    <span className="text-slate-700 truncate pr-2">{c.course}</span>
                    <span className="text-xs text-slate-400 shrink-0">{c.issued}</span>
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
    </div>
  )
}

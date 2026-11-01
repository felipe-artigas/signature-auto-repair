import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { api, errorMessage, setCsrfToken } from '../lib/api'
import { Logo } from '../components/Logo'
import { Services, SettingsPanel, Vehicles } from './AdminExtra'

type Admin = { id: number; email: string; full_name: string; csrf_token: string }
type Tab = 'dashboard' | 'requests' | 'customers' | 'vehicles' | 'agenda' | 'radar' | 'services' | 'settings'

const STATUSES = ['nueva', 'en_revision', 'esperando_informacion', 'contactado', 'presupuesto_pendiente', 'aprobado', 'rechazado', 'finalizado']
const STATUS_LABEL: Record<string, string> = {
  nueva: 'Nueva', en_revision: 'En revisión', esperando_informacion: 'Esperando información', contactado: 'Contactado',
  presupuesto_pendiente: 'Presupuesto pendiente', aprobado: 'Aprobado', rechazado: 'Rechazado', finalizado: 'Finalizado',
}
const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' }) : '—')
const input = 'min-h-11 w-full border border-line bg-graphite px-3 text-sm text-ivory focus:border-gold focus:outline-none'

function useLoad<T>(path: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const reload = useCallback(() => {
    api<T>(path).then(setData).catch((e) => setError(errorMessage(e)))
  }, [path])
  useEffect(reload, [reload])
  return { data, error, reload }
}

function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="border border-line bg-anthracite/40 p-5">
      {title && <h2 className="mb-4 font-display text-2xl text-ivory">{title}</h2>}
      {children}
    </section>
  )
}

function AuthScreen({ onAuth }: { onAuth: (a: Admin) => void }) {
  const [setup, setSetup] = useState<{ setup_required: boolean } | null>(null)
  const [form, setForm] = useState({ email: '', password: '', full_name: '', setup_token: '' })
  const [error, setError] = useState('')
  useEffect(() => {
    api<{ setup_required: boolean }>('/api/admin/auth/status').then(setSetup).catch(() => setSetup({ setup_required: false }))
  }, [])
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const path = setup?.setup_required ? '/api/admin/auth/setup' : '/api/admin/auth/login'
      const body = setup?.setup_required ? form : { email: form.email, password: form.password }
      onAuth(await api<Admin>(path, { method: 'POST', body }))
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })
  return (
    <main className="flex min-h-screen items-center justify-center bg-deep p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 border border-line bg-graphite p-8">
        <Logo tone="light" />
        <h1 className="pt-4 font-display text-3xl text-ivory">{setup?.setup_required ? 'Configuración inicial' : 'Acceso propietario'}</h1>
        {setup?.setup_required && (
          <>
            <label className="block text-xs text-silver">Token de configuración<input className={input} value={form.setup_token} onChange={set('setup_token')} required /></label>
            <label className="block text-xs text-silver">Nombre completo<input className={input} value={form.full_name} onChange={set('full_name')} required /></label>
          </>
        )}
        <label className="block text-xs text-silver">Correo electrónico<input type="email" autoComplete="username" className={input} value={form.email} onChange={set('email')} required /></label>
        <label className="block text-xs text-silver">Contraseña<input type="password" autoComplete={setup?.setup_required ? 'new-password' : 'current-password'} className={input} value={form.password} onChange={set('password')} required /></label>
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
        <button className="btn-gold w-full">{setup?.setup_required ? 'Crear cuenta' : 'Ingresar'}</button>
        <Link to="/" className="block text-center text-xs text-silver hover:text-ivory">Volver al sitio</Link>
      </form>
    </main>
  )
}

function Dashboard() {
  const { data } = useLoad<any>('/api/admin/dashboard')
  if (!data) return <p className="text-silver">Cargando...</p>
  const m = data.metrics
  const tiles = [
    ['Consultas recibidas', m.conversations_total], ['Solicitudes totales', m.requests_total], ['Nuevas', m.requests_new],
    ['Pendientes', m.requests_pending], ['Turnos solicitados', m.appointments_requested], ['Turnos confirmados', m.appointments_confirmed],
    ['Presupuestos pendientes', m.quotes_pending], ['Clientes', m.customers_total], ['Oportunidades sin seguimiento', m.opportunities_unattended],
  ]
  const max = Math.max(1, ...data.requests_daily.map((d: any) => d.count))
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-px bg-line md:grid-cols-3">
        {tiles.map(([label, value]) => (
          <div key={label} className="bg-graphite p-5">
            <p className="text-[0.65rem] uppercase tracking-[0.2em] text-silver">{label}</p>
            <p className="mt-2 font-display text-4xl text-ivory">{value}</p>
          </div>
        ))}
      </div>
      <Card title="Solicitudes de los últimos 14 días">
        <div className="flex h-32 items-end gap-1" role="img" aria-label="Gráfico de solicitudes diarias">
          {data.requests_daily.map((d: any) => (
            <div key={d.date} title={`${d.date}: ${d.count}`} className="flex-1 bg-gold/70" style={{ height: `${(d.count / max) * 100}%`, minHeight: 2 }} />
          ))}
        </div>
      </Card>
      <p className="text-xs text-silver">IA: {data.ai.mode === 'openai' ? `OpenAI (${data.ai.model})` : 'modo de prueba'} · solicitudes hoy {data.ai.requests_today} · tokens hoy {data.ai.tokens_today}</p>
    </div>
  )
}

function RequestDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const { data, reload } = useLoad<any>(`/api/admin/requests/${id}`)
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState('')
  if (!data) return <p className="text-silver">Cargando...</p>
  const act = async (fn: () => Promise<unknown>) => {
    setMsg('')
    try { await fn(); reload() } catch (e) { setMsg(errorMessage(e)) }
  }
  const v = data.vehicle
  return (
    <div className="space-y-5">
      <button onClick={onBack} className="text-sm text-gold-soft">Volver al listado</button>
      <Card title={`${data.code} · ${data.customer.full_name}`}>
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <p><span className="text-silver">Fecha: </span>{fmt(data.created_at)}</p>
          <p><span className="text-silver">Teléfono: </span>{data.customer.phone ?? '—'}</p>
          <p><span className="text-silver">Correo: </span>{data.customer.email ?? '—'}</p>
          <p><span className="text-silver">Vehículo: </span>{v ? `${v.make} ${v.model} ${v.year ?? ''} · ${v.mileage_km ?? '—'} km` : '—'}</p>
          <p><span className="text-silver">Servicio: </span>{data.requested_service ?? '—'}</p>
          <p><span className="text-silver">Frecuencia: </span>{data.frequency ?? '—'} · <span className="text-silver">Inicio: </span>{data.onset ?? '—'}</p>
          <p className="sm:col-span-2"><span className="text-silver">Problema: </span>{data.problem_description ?? '—'}</p>
          <p className="sm:col-span-2"><span className="text-silver">Disponibilidad: </span>{data.customer_availability ?? '—'}</p>
        </div>
        <label className="mt-5 block text-xs text-silver">Estado
          <select className={input} value={data.status} onChange={(e) => act(() => api(`/api/admin/requests/${id}`, { method: 'PATCH', body: { status: e.target.value } }))}>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </label>
      </Card>
      <Card title="Resumen inteligente">
        <p className="whitespace-pre-line text-sm text-ivory/90">{data.ai_summary ?? '—'}</p>
        <button className="btn-outline mt-4" onClick={() => act(() => api(`/api/admin/requests/${id}/summary`, { method: 'POST' }))}>Regenerar resumen</button>
      </Card>
      <Card title="Notas internas">
        <ul className="space-y-2 text-sm">{data.notes.map((n: any) => <li key={n.id} className="border-l border-gold pl-3">{n.body} <span className="text-xs text-silver">{fmt(n.created_at)}</span></li>)}</ul>
        <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); act(async () => { await api(`/api/admin/requests/${id}/notes`, { method: 'POST', body: { body: note } }); setNote('') }) }}>
          <input className={input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Agregar nota" required />
          <button className="btn-gold">Guardar</button>
        </form>
      </Card>
      {data.conversation && (
        <Card title="Conversación con el asistente">
          <div className="max-h-96 space-y-2 overflow-y-auto text-sm">
            {data.conversation.messages.filter((m: any) => m.role === 'user' || m.role === 'assistant').map((m: any, i: number) => (
              <p key={i} className={m.role === 'user' ? 'text-gold-soft' : 'text-ivory/85'}><b>{m.role === 'user' ? 'Cliente' : 'Asistente'}:</b> {m.content}</p>
            ))}
          </div>
        </Card>
      )}
      {msg && <p role="alert" className="text-sm text-red-300">{msg}</p>}
    </div>
  )
}

function Requests() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const { data } = useLoad<any>(`/api/admin/requests?page_size=100${status ? `&status=${status}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
  if (selected) return <RequestDetail id={selected} onBack={() => setSelected(null)} />
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input className={input} placeholder="Buscar por código, cliente, vehículo o patente" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={`${input} sm:max-w-60`} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Todos los estados</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-silver"><tr><th className="py-2">Código</th><th>Fecha</th><th>Cliente</th><th>Vehículo</th><th>Servicio</th><th>Estado</th></tr></thead>
          <tbody>
            {data?.items.map((r: any) => (
              <tr key={r.id} className="cursor-pointer border-t border-line hover:bg-anthracite" onClick={() => setSelected(r.id)}>
                <td className="py-3 text-gold-soft">{r.code}</td><td>{fmt(r.created_at)}</td><td>{r.customer.full_name}</td>
                <td>{r.vehicle ? `${r.vehicle.make} ${r.vehicle.model} ${r.vehicle.year ?? ''}` : '—'}</td><td>{r.requested_service ?? '—'}</td><td>{STATUS_LABEL[r.status]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.items.length === 0 && <p className="py-6 text-silver">No hay solicitudes.</p>}
      </div>
    </div>
  )
}

function Customers() {
  const [q, setQ] = useState('')
  const { data } = useLoad<any>(`/api/admin/customers?page_size=100${q ? `&q=${encodeURIComponent(q)}` : ''}`)
  return (
    <div className="space-y-4">
      <input className={input} placeholder="Buscar cliente" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-silver"><tr><th className="py-2">Nombre</th><th>Teléfono</th><th>Correo</th><th>Alta</th><th>Vehículos</th><th>Solicitudes</th></tr></thead>
          <tbody>{data?.items.map((c: any) => (
            <tr key={c.id} className="border-t border-line"><td className="py-3">{c.full_name}</td><td>{c.phone ?? '—'}</td><td>{c.email ?? '—'}</td><td>{fmt(c.created_at)}</td><td>{c.vehicles_count}</td><td>{c.requests_count}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}

function Agenda() {
  const today = new Date()
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  const to = new Date(today.getTime() + 21 * 86400000)
  const { data, reload } = useLoad<any>(`/api/admin/appointments?from=${iso(today)}&to=${iso(to)}`)
  const [msg, setMsg] = useState('')
  const update = async (id: number, status: string) => {
    setMsg('')
    try { await api(`/api/admin/appointments/${id}`, { method: 'PATCH', body: { status } }); reload() } catch (e) { setMsg(errorMessage(e)) }
  }
  return (
    <Card title="Turnos de las próximas 3 semanas">
      {msg && <p role="alert" className="mb-3 text-sm text-red-300">{msg}</p>}
      <ul className="divide-y divide-line text-sm">
        {data?.items.map((a: any) => (
          <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <span>{a.start_local.replace('T', ' ')} · {a.customer.full_name} {a.vehicle ? `· ${a.vehicle.label}` : ''} · <span className="text-gold-soft">{a.status}</span></span>
            <span className="flex gap-2">
              {a.status === 'solicitado' && <button className="btn-outline min-h-9 px-3" onClick={() => update(a.id, 'confirmado')}>Confirmar</button>}
              {a.status !== 'cancelado' && <button className="btn-ghost min-h-9 px-3" onClick={() => update(a.id, 'cancelado')}>Cancelar</button>}
            </span>
          </li>
        ))}
        {data?.items.length === 0 && <li className="py-4 text-silver">Sin turnos.</li>}
      </ul>
    </Card>
  )
}

function Radar() {
  const { data, reload } = useLoad<any>('/api/admin/radar')
  const [msg, setMsg] = useState('')
  const run = async (fn: () => Promise<unknown>) => {
    setMsg('')
    try { await fn(); reload() } catch (e) { setMsg(errorMessage(e)) }
  }
  return (
    <div className="space-y-6">
      {msg && <p role="alert" className="text-sm text-red-300">{msg}</p>}
      <Card title="Oportunidades detectadas">
        <ul className="divide-y divide-line text-sm">
          {data?.items.map((o: any) => (
            <li key={o.key} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span><span className="text-gold-soft">{o.label}</span> · {o.customer_name} {o.vehicle ? `· ${o.vehicle}` : ''} · {o.age_days} días<br /><span className="text-xs text-silver">{o.detail}</span></span>
              <button className="btn-outline min-h-9 px-3" onClick={() => run(() => api('/api/admin/radar/drafts', { method: 'POST', body: { kind: o.kind, request_id: o.request_id, conversation_id: o.conversation_id, customer_id: o.customer_id } }))}>Generar mensaje</button>
            </li>
          ))}
          {data?.items.length === 0 && <li className="py-4 text-silver">No hay oportunidades pendientes.</li>}
        </ul>
      </Card>
      <Card title="Borradores para revisar">
        <p className="mb-4 text-xs text-silver">Los mensajes no se envían automáticamente. Apruébelos, envíelos desde su canal y registre el envío.</p>
        <ul className="space-y-4">
          {data?.drafts.map((f: any) => (
            <li key={f.id} className="border border-line p-4 text-sm">
              <p className="text-xs text-silver">{f.suggestion} · generado por {f.generated_by} · estado: {f.status}</p>
              <p className="mt-2 whitespace-pre-line text-ivory">{f.message}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {f.status === 'borrador' && <button className="btn-gold min-h-9 px-3" onClick={() => run(() => api(`/api/admin/follow-ups/${f.id}`, { method: 'PATCH', body: { status: 'aprobado' } }))}>Aprobar</button>}
                {f.status === 'aprobado' && <button className="btn-gold min-h-9 px-3" onClick={() => run(() => api(`/api/admin/follow-ups/${f.id}`, { method: 'PATCH', body: { status: 'enviado', channel: f.channel ?? 'whatsapp' } }))}>Registrar como enviado</button>}
                <button className="btn-ghost min-h-9 px-3" onClick={() => navigator.clipboard?.writeText(f.message)}>Copiar</button>
                <button className="btn-ghost min-h-9 px-3" onClick={() => run(() => api(`/api/admin/follow-ups/${f.id}`, { method: 'PATCH', body: { status: 'descartado' } }))}>Descartar</button>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

const TABS: [Tab, string][] = [
  ['dashboard', 'Dashboard'], ['requests', 'Consultas'], ['customers', 'Clientes'], ['vehicles', 'Vehículos'], ['agenda', 'Agenda'],
  ['radar', 'Radar comercial'], ['services', 'Servicios'], ['settings', 'Configuración'],
]

export default function AdminApp() {
  const [admin, setAdmin] = useState<Admin | null>(null)
  const [checked, setChecked] = useState(false)
  const [tab, setTab] = useState<Tab>('dashboard')

  useEffect(() => {
    document.title = 'Panel · Signature Auto Repair'
    api<Admin>('/api/admin/auth/me').then((a) => { setCsrfToken(a.csrf_token); setAdmin(a) }).catch(() => {}).finally(() => setChecked(true))
  }, [])

  if (!checked) return <div className="min-h-screen bg-deep" />
  if (!admin) return <AuthScreen onAuth={(a) => { setCsrfToken(a.csrf_token); setAdmin(a) }} />

  const logout = async () => {
    await api('/api/admin/auth/logout', { method: 'POST' }).catch(() => {})
    setCsrfToken(null)
    setAdmin(null)
  }
  return (
    <div className="min-h-screen bg-deep text-ivory">
      <header className="border-b border-line bg-graphite">
        <div className="container-x flex flex-wrap items-center justify-between gap-4 py-4">
          <Logo tone="light" compact />
          <div className="flex items-center gap-4 text-sm text-silver">{admin.full_name}<button onClick={logout} className="btn-ghost min-h-9 px-3">Salir</button></div>
        </div>
        <nav className="container-x flex gap-1 overflow-x-auto">
          {TABS.map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)} className={`whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] ${tab === key ? 'border-b-2 border-gold text-ivory' : 'text-silver'}`}>{label}</button>
          ))}
        </nav>
      </header>
      <main className="container-x py-8">
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'requests' && <Requests />}
        {tab === 'customers' && <Customers />}
        {tab === 'agenda' && <Agenda />}
        {tab === 'radar' && <Radar />}
        {tab === 'vehicles' && <Vehicles />}
        {tab === 'services' && <Services />}
        {tab === 'settings' && <SettingsPanel />}
      </main>
    </div>
  )
}

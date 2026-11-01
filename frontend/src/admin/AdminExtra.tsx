import { useEffect, useState, type FormEvent } from 'react'

import { api, errorMessage } from '../lib/api'

const input = 'min-h-11 w-full border border-line bg-graphite px-3 text-sm text-ivory focus:border-gold focus:outline-none'
const DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

type Vehicle = {
  id: number; customer_name: string; make: string; model: string; year: number | null; version: string | null
  mileage_km: number | null; plate: string | null; vin: string | null; requests_count: number
}
type Service = {
  id: number; slug: string; name: string; description: string; category: string; is_active: boolean
  price_info: string | null; sort_order: number
}
type Settings = {
  business_name: string
  contact: Record<string, string | boolean>
  weekly_schedule: Record<string, [string, string][]>
  closed_dates: string[]
  slot_minutes: number; bays: number; min_notice_hours: number; booking_horizon_days: number; stale_after_days: number
}

function Status({ msg, error }: { msg: string; error: string }) {
  if (error) return <p role="alert" className="text-sm text-red-300">{error}</p>
  if (msg) return <p role="status" className="text-sm text-gold-soft">{msg}</p>
  return null
}

export function Vehicles() {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Vehicle[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    api<{ items: Vehicle[] }>(`/api/admin/vehicles?page_size=100${q ? `&q=${encodeURIComponent(q)}` : ''}`, { signal: controller.signal })
      .then((d) => setItems(d.items))
      .catch((e) => e.name !== 'AbortError' && setError(errorMessage(e)))
    return () => controller.abort()
  }, [q])
  return (
    <div className="space-y-4">
      <input className={input} placeholder="Buscar por marca, modelo, patente, VIN o propietario" value={q} onChange={(e) => setQ(e.target.value)} />
      <Status msg="" error={error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-silver">
            <tr><th className="py-2">Propietario</th><th>Marca</th><th>Modelo</th><th>Año</th><th>Versión</th><th>Kilometraje</th><th>Patente</th><th>VIN</th><th>Solicitudes</th></tr>
          </thead>
          <tbody>
            {items?.map((v) => (
              <tr key={v.id} className="border-t border-line">
                <td className="py-3">{v.customer_name}</td><td>{v.make}</td><td>{v.model}</td><td>{v.year ?? '—'}</td><td>{v.version ?? '—'}</td>
                <td>{v.mileage_km != null ? `${v.mileage_km.toLocaleString('es-AR')} km` : '—'}</td><td>{v.plate ?? '—'}</td><td>{v.vin ?? '—'}</td><td>{v.requests_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items?.length === 0 && <p className="py-6 text-silver">No hay vehículos registrados.</p>}
      </div>
    </div>
  )
}

function ServiceRow({ service, onSaved }: { service: Service; onSaved: () => void }) {
  const [form, setForm] = useState(service)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const save = async (e: FormEvent) => {
    e.preventDefault()
    setMsg(''); setError('')
    try {
      await api(`/api/admin/services/${service.id}`, {
        method: 'PATCH',
        body: { name: form.name, description: form.description, category: form.category, is_active: form.is_active, price_info: form.price_info || null, sort_order: form.sort_order },
      })
      setMsg('Guardado.')
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  return (
    <form onSubmit={save} className="grid gap-3 border border-line p-4 md:grid-cols-[1fr_1fr_1fr]">
      <label className="text-xs text-silver">Nombre<input className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
      <label className="text-xs text-silver">Categoría<input className={input} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} required /></label>
      <label className="text-xs text-silver">Precio informado (vacío = a cotizar)<input className={input} value={form.price_info ?? ''} maxLength={120} onChange={(e) => setForm({ ...form, price_info: e.target.value })} placeholder="Ej.: Desde ARS 150.000" /></label>
      <label className="text-xs text-silver md:col-span-3">Descripción<textarea className={`${input} py-2`} rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required /></label>
      <div className="flex flex-wrap items-center gap-4 md:col-span-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} className="h-4 w-4 accent-[#c6a56b]" />Activo en el sitio</label>
        <label className="flex items-center gap-2 text-xs text-silver">Orden<input type="number" min={0} max={1000} className={`${input} w-24`} value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })} /></label>
        <button className="btn-gold min-h-9 px-4">Guardar</button>
        <Status msg={msg} error={error} />
      </div>
    </form>
  )
}

export function Services() {
  const [items, setItems] = useState<Service[] | null>(null)
  const load = () => api<{ items: Service[] }>('/api/admin/services').then((d) => setItems(d.items)).catch(() => setItems([]))
  useEffect(() => { load() }, [])
  return (
    <div className="space-y-4">
      <p className="text-xs text-silver">Los precios solo se muestran y los informa el asistente si usted los completa. La IA nunca inventa precios.</p>
      {items?.map((s) => <ServiceRow key={s.id} service={s} onSaved={load} />)}
    </div>
  )
}

export function SettingsPanel() {
  const [form, setForm] = useState<Settings | null>(null)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { api<Settings>('/api/admin/settings').then(setForm).catch((e) => setError(errorMessage(e))) }, [])
  if (!form) return <Status msg="Cargando..." error={error} />

  const contact = (key: string, label: string) => (
    <label className="text-xs text-silver">{label}
      <input className={input} value={String(form.contact[key] ?? '')} onChange={(e) => setForm({ ...form, contact: { ...form.contact, [key]: e.target.value } })} />
    </label>
  )
  const setBlock = (day: string, value: [string, string] | null) =>
    setForm({ ...form, weekly_schedule: { ...form.weekly_schedule, [day]: value ? [value] : [] } })
  const num = (key: 'slot_minutes' | 'bays' | 'min_notice_hours' | 'booking_horizon_days' | 'stale_after_days', label: string, min: number, max: number) => (
    <label className="text-xs text-silver">{label}
      <input type="number" min={min} max={max} className={input} value={form[key]} onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })} />
    </label>
  )

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setMsg(''); setError('')
    try {
      const saved = await api<Settings>('/api/admin/settings', { method: 'PUT', body: form })
      setForm(saved)
      setMsg('Configuración guardada. El sitio y el asistente ya usan los nuevos datos.')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <form onSubmit={save} className="space-y-6">
      <section className="border border-line bg-anthracite/40 p-5">
        <h2 className="mb-4 font-display text-2xl text-ivory">Datos de contacto</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs text-silver">Nombre del negocio<input className={input} value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} required /></label>
          {contact('phone', 'Teléfono')}
          {contact('whatsapp', 'WhatsApp')}
          {contact('email', 'Correo electrónico')}
          {contact('address', 'Dirección')}
          {contact('city', 'Ciudad')}
          {contact('hours_text', 'Horario (texto visible en el sitio)')}
          {contact('maps_url', 'Enlace de Google Maps (https://...)')}
          <label className="flex items-center gap-2 text-sm md:col-span-2">
            <input type="checkbox" checked={Boolean(form.contact.is_placeholder)} onChange={(e) => setForm({ ...form, contact: { ...form.contact, is_placeholder: e.target.checked } })} className="h-4 w-4 accent-[#c6a56b]" />
            Marcar los datos como provisionales en el sitio
          </label>
        </div>
      </section>
      <section className="border border-line bg-anthracite/40 p-5">
        <h2 className="mb-4 font-display text-2xl text-ivory">Agenda y disponibilidad</h2>
        <div className="space-y-2">
          {DAYS.map((name, index) => {
            const day = String(index)
            const block = form.weekly_schedule[day]?.[0]
            return (
              <div key={day} className="grid grid-cols-[110px_auto_1fr_1fr] items-center gap-3 text-sm">
                <span>{name}</span>
                <input type="checkbox" aria-label={`Abierto el ${name}`} checked={Boolean(block)} onChange={(e) => setBlock(day, e.target.checked ? ['09:00', '18:00'] : null)} className="h-4 w-4 accent-[#c6a56b]" />
                {block ? (
                  <>
                    <input type="time" aria-label={`Apertura ${name}`} className={input} value={block[0]} onChange={(e) => setBlock(day, [e.target.value, block[1]])} />
                    <input type="time" aria-label={`Cierre ${name}`} className={input} value={block[1]} onChange={(e) => setBlock(day, [block[0], e.target.value])} />
                  </>
                ) : (
                  <span className="col-span-2 text-silver">Cerrado</span>
                )}
              </div>
            )
          })}
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {num('slot_minutes', 'Duración del turno (minutos)', 15, 480)}
          {num('bays', 'Turnos simultáneos (puestos de trabajo)', 1, 20)}
          {num('min_notice_hours', 'Anticipación mínima (horas)', 0, 168)}
          {num('booking_horizon_days', 'Reservas con hasta (días)', 1, 180)}
          {num('stale_after_days', 'Radar: sin actualización tras (días)', 1, 60)}
          <label className="text-xs text-silver">Días cerrados (AAAA-MM-DD, separados por coma)
            <input className={input} value={form.closed_dates.join(', ')} onChange={(e) => setForm({ ...form, closed_dates: e.target.value.split(',').map((d) => d.trim()).filter(Boolean) })} />
          </label>
        </div>
      </section>
      <div className="flex flex-wrap items-center gap-4">
        <button className="btn-gold">Guardar configuración</button>
        <Status msg={msg} error={error} />
      </div>
    </form>
  )
}

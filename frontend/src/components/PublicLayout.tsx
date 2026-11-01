import { lazy, Suspense, useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Lock, Menu, MessageSquareText, X } from 'lucide-react'

import { useSite } from '../lib/site'
import { Logo } from './Logo'

const Assistant = lazy(() => import('./assistant/Assistant'))

export const NAV_ITEMS = [
  { href: '/#inicio', label: 'Inicio' },
  { href: '/#nosotros', label: 'Nosotros' },
  { href: '/#servicios', label: 'Servicios' },
  { href: '/#especialidades', label: 'Especialidades' },
  { href: '/#proceso', label: 'Proceso' },
  { href: '/#contacto', label: 'Contacto' },
]

function TopBar() {
  const { site } = useSite()
  return (
    <div className="bg-deep text-silver">
      <div className="container-x flex h-11 items-center justify-between gap-4 text-[0.72rem] tracking-wide">
        <p className="truncate">
          <span className="hidden sm:inline">Atención con cita previa · </span>
          {site?.contact.hours_text ?? 'Horario de atención'}
        </p>
        <Link
          to="/admin"
          className="inline-flex h-full shrink-0 items-center gap-2 bg-anthracite px-4 font-medium uppercase tracking-[0.16em] text-gold-soft transition-colors hover:bg-line"
        >
          Acceso propietario
          <Lock aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  )
}

function Header() {
  const { openAssistant } = useSite()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => setOpen(false), [location.pathname, location.hash])

  return (
    <header className="sticky top-0 z-40 border-b border-ivory-dim bg-ivory/95 backdrop-blur supports-[backdrop-filter]:bg-ivory/85">
      <div className="container-x flex h-20 items-center justify-between gap-6">
        <Link to="/" aria-label="Signature Auto Repair, inicio" className="shrink-0">
          <Logo tone="dark" compact />
        </Link>
        <nav aria-label="Principal" className="hidden lg:block">
          <ul className="flex items-center gap-7">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <NavLink
                  to={item.href}
                  className="relative py-2 text-[0.72rem] font-semibold uppercase tracking-[0.16em] text-graphite after:absolute after:inset-x-0 after:-bottom-0.5 after:h-px after:origin-left after:scale-x-0 after:bg-gold-deep after:transition-transform hover:after:scale-x-100"
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => openAssistant()} className="btn hidden bg-graphite text-gold-soft hover:bg-anthracite sm:inline-flex">
            Solicitar atención
          </button>
          <button
            type="button"
            className="inline-flex h-11 w-11 items-center justify-center text-graphite lg:hidden"
            aria-expanded={open}
            aria-controls="menu-movil"
            aria-label={open ? 'Cerrar menú' : 'Abrir menú'}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>
      </div>
      {open && (
        <nav id="menu-movil" aria-label="Menú móvil" className="border-t border-ivory-dim bg-ivory lg:hidden">
          <ul className="container-x flex flex-col py-3">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <NavLink
                  to={item.href}
                  className="block border-b border-ivory-dim py-3.5 text-sm font-semibold uppercase tracking-[0.14em] text-graphite"
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
            <li className="pt-4">
              <button type="button" onClick={() => openAssistant()} className="btn w-full bg-graphite text-gold-soft">
                Solicitar atención
              </button>
            </li>
          </ul>
        </nav>
      )}
    </header>
  )
}

function Footer() {
  const { site } = useSite()
  const year = new Date().getFullYear()
  return (
    <footer className="border-t border-line bg-deep">
      <div className="container-x grid gap-12 py-16 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo tone="light" />
          <p className="mt-6 max-w-sm text-sm leading-relaxed text-silver">
            Taller independiente especializado en el mantenimiento y la reparación de vehículos de alta gama. Las marcas
            mencionadas en este sitio se utilizan solo a título descriptivo; no somos concesionario ni servicio oficial.
          </p>
        </div>
        <nav aria-label="Pie de página">
          <h2 className="eyebrow">Navegación</h2>
          <ul className="mt-5 space-y-3 text-sm text-silver">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <Link to={item.href} className="hover:text-ivory">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div>
          <h2 className="eyebrow">Información</h2>
          <ul className="mt-5 space-y-3 text-sm text-silver">
            <li>
              <Link to="/privacidad" className="hover:text-ivory">
                Política de privacidad
              </Link>
            </li>
            <li>
              <Link to="/privacidad#creditos" className="hover:text-ivory">
                Créditos de imágenes
              </Link>
            </li>
            {site?.contact.email && !site.contact.is_placeholder && (
              <li>
                <a href={`mailto:${site.contact.email}`} className="hover:text-ivory">
                  {site.contact.email}
                </a>
              </li>
            )}
          </ul>
        </div>
      </div>
      <div className="border-t border-line">
        <p className="container-x py-6 text-xs text-silver">
          {year} Signature Auto Repair. Todos los derechos reservados. Proyecto de demostración: los datos de contacto son
          ficticios.
        </p>
      </div>
    </footer>
  )
}

function AssistantLauncher() {
  const { assistantOpen, openAssistant } = useSite()
  if (assistantOpen) return null
  return (
    <button
      type="button"
      onClick={() => openAssistant()}
      className="fixed right-4 bottom-4 z-40 inline-flex items-center gap-3 border border-gold/50 bg-graphite/95 py-3 pr-5 pl-4 text-left shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur transition-colors hover:border-gold sm:right-6 sm:bottom-6"
    >
      <MessageSquareText aria-hidden className="h-5 w-5 text-gold" />
      <span className="flex flex-col leading-tight">
        <span className="text-[0.62rem] font-semibold uppercase tracking-[0.24em] text-silver">Recepción</span>
        <span className="font-display text-lg text-ivory">Consultar al asistente</span>
      </span>
    </button>
  )
}

export default function PublicLayout() {
  const { assistantOpen } = useSite()
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    if (assistantOpen) setMounted(true)
  }, [assistantOpen])

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#contenido" className="sr-only z-50 bg-gold px-4 py-2 text-deep focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Saltar al contenido
      </a>
      <TopBar />
      <Header />
      <main id="contenido" className="flex-1">
        <Outlet />
      </main>
      <Footer />
      <AssistantLauncher />
      {mounted && (
        <Suspense fallback={null}>
          <Assistant />
        </Suspense>
      )}
    </div>
  )
}

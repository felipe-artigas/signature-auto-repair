import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUpRight,
  CalendarCheck,
  CircleGauge,
  ClipboardCheck,
  Cog,
  Disc3,
  MessageSquareText,
  ScanLine,
  Settings2,
  Snowflake,
  Waves,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'

import Picture from '../components/Picture'
import { LogoSymbol } from '../components/Logo'
import { useSite } from '../lib/site'

const SERVICE_ICONS: Record<string, LucideIcon> = {
  'diagnostico-computarizado': ScanLine,
  'mecanica-integral': Wrench,
  'mantenimiento-preventivo': CalendarCheck,
  'sistemas-de-frenos': Disc3,
  'suspension-y-direccion': Waves,
  'electricidad-y-electronica': Zap,
  transmision: Cog,
  climatizacion: Snowflake,
  'inspeccion-general': ClipboardCheck,
}

const BRANDS = ['Porsche', 'Mercedes-Benz', 'BMW', 'Audi', 'Ferrari', 'Lamborghini', 'Maserati', 'Range Rover']

const PROCESS = [
  ['Usted describe su necesidad', 'Nos cuenta qué servicio busca o qué está notando en su vehículo, con sus palabras.'],
  ['El asistente recopila la información', 'Ordena los datos del vehículo, los síntomas y su disponibilidad, sin formularios interminables.'],
  ['El taller recibe una solicitud organizada', 'Nuestro equipo accede a un resumen claro, sin datos perdidos ni mensajes dispersos.'],
  ['Un profesional evalúa el vehículo', 'El diagnóstico lo realiza siempre una persona del taller, con el vehículo presente.'],
  ['Le presentamos una propuesta', 'Detallamos el trabajo recomendado y su costo antes de intervenir.'],
  ['Usted confirma y coordinamos', 'Con su aprobación, acordamos la fecha de ingreso y lo mantenemos informado.'],
]

function Hero() {
  const { openAssistant } = useSite()
  return (
    <section id="inicio" aria-labelledby="hero-title" className="relative isolate overflow-hidden bg-deep">
      <Picture
        name="hero"
        priority
        sizes="100vw"
        alt="Porsche 911 Carrera en una calle mojada al anochecer, con las luces traseras encendidas"
        className="absolute inset-0 -z-10 h-full w-full object-cover object-[62%_center]"
      />
      <div aria-hidden className="absolute inset-0 -z-10 bg-gradient-to-r from-deep via-deep/80 to-deep/10" />
      <div aria-hidden className="absolute inset-x-0 bottom-0 -z-10 h-40 bg-gradient-to-t from-graphite to-transparent" />
      <div className="container-x flex min-h-[560px] flex-col justify-center pt-16 pb-36 sm:min-h-[620px] lg:min-h-[680px]">
        <p className="eyebrow animate-fade-up">Taller especializado en vehículos de alta gama</p>
        <h1 id="hero-title" lang="en" className="mt-6 max-w-3xl animate-fade-up font-display text-5xl leading-[1.02] font-medium text-ivory sm:text-6xl lg:text-7xl">
          Precision in <em className="text-gold-soft">Every Detail.</em>
        </h1>
        <p className="mt-6 max-w-xl animate-fade-up text-lg leading-relaxed text-ivory/85 sm:text-xl">
          Excelencia automotriz. Atención a la altura de su vehículo.
        </p>
        <div className="mt-10 flex animate-fade-up flex-wrap gap-4">
          <button type="button" className="btn-gold" onClick={() => openAssistant()}>
            Iniciar consulta
            <ArrowRight aria-hidden className="h-4 w-4" />
          </button>
          <Link to="/#servicios" className="btn-ghost bg-deep/30">
            Ver servicios
          </Link>
        </div>
      </div>
    </section>
  )
}

function EntryCards() {
  const { openAssistant } = useSite()
  const [draft, setDraft] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    openAssistant(draft.trim())
    setDraft('')
  }
  return (
    <div className="relative z-10 -mt-24 sm:-mt-28">
      <div className="container-x grid gap-5 md:grid-cols-2">
        <form onSubmit={submit} className="border-t-2 border-gold bg-anthracite p-7 shadow-[0_24px_60px_rgba(0,0,0,0.5)] sm:p-9">
          <MessageSquareText aria-hidden className="h-7 w-7 text-gold" strokeWidth={1.5} />
          <h2 className="mt-5 font-display text-3xl text-ivory">Inicie su consulta</h2>
          <p className="mt-2 text-sm text-silver">Describa su vehículo o lo que necesita. Nuestro asistente lo guiará.</p>
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <label htmlFor="consulta-rapida" className="sr-only">
              Describa su vehículo o su consulta
            </label>
            <input
              id="consulta-rapida"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={300}
              placeholder="Ej.: BMW 330i 2021, ruido en la suspensión"
              className="min-h-12 flex-1 border border-line bg-graphite px-4 text-sm text-ivory placeholder:text-silver/80 focus:border-gold focus:outline-none"
            />
            <button type="submit" className="btn-gold">
              Consultar
            </button>
          </div>
        </form>
        <Link
          to="/#proceso"
          className="group relative isolate flex min-h-60 flex-col justify-end overflow-hidden p-7 shadow-[0_24px_60px_rgba(0,0,0,0.5)] sm:p-9"
        >
          <Picture
            name="gold"
            sizes="(min-width: 768px) 50vw, 100vw"
            alt=""
            className="absolute inset-0 -z-10 h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
          />
          <div aria-hidden className="absolute inset-0 -z-10 bg-gradient-to-t from-deep via-deep/75 to-deep/30" />
          <LogoSymbol className="h-8 w-8 text-gold" />
          <h2 className="mt-5 font-display text-3xl text-ivory">Conozca nuestro proceso</h2>
          <p className="mt-2 flex items-center gap-2 text-sm text-ivory/85">
            De la primera consulta a la entrega, con total transparencia
            <ArrowUpRight aria-hidden className="h-4 w-4 text-gold transition-transform group-hover:translate-x-1" />
          </p>
        </Link>
      </div>
    </div>
  )
}

function About() {
  const pillars = [
    ['Especialización', 'Procedimientos, herramientas y criterios pensados para la ingeniería de los vehículos premium.'],
    ['Transparencia', 'Diferenciamos lo que usted nos cuenta de lo que verifica un profesional, y presupuestamos antes de intervenir.'],
    ['Atención personalizada', 'Un interlocutor que conoce su vehículo y su historial, con comunicación clara en cada etapa.'],
  ]
  return (
    <section id="nosotros" aria-labelledby="nosotros-title" className="py-24 sm:py-32">
      <div className="container-x grid items-center gap-14 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <p className="eyebrow">Nosotros</p>
          <h2 id="nosotros-title" className="mt-5 font-display text-4xl leading-tight text-ivory sm:text-5xl">
            El cuidado que su vehículo merece, con la precisión que exige.
          </h2>
          <div className="rule-gold mt-8" />
          <p className="mt-8 max-w-xl leading-relaxed text-silver">
            Signature Auto Repair es un taller dedicado exclusivamente al mantenimiento y la reparación de vehículos de alta
            gama. Trabajamos con turnos programados para dedicar a cada vehículo el tiempo que requiere, y acompañamos al
            propietario con información clara desde la primera consulta hasta la entrega.
          </p>
          <dl className="mt-10 grid gap-8 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
            {pillars.map(([title, text]) => (
              <div key={title} className="border-l border-gold/50 pl-5">
                <dt className="font-display text-xl text-ivory">{title}</dt>
                <dd className="mt-2 text-sm leading-relaxed text-silver">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="relative">
          <div aria-hidden className="absolute -top-4 -left-4 h-24 w-24 border-t border-l border-gold/60" />
          <Picture
            name="wheel"
            sizes="(min-width: 1024px) 45vw, 100vw"
            alt="Detalle de la rueda y el paso de rueda de un superdeportivo"
            className="aspect-[4/3] w-full object-cover"
          />
        </div>
      </div>
    </section>
  )
}

function Services() {
  const { site, siteError, openAssistant } = useSite()
  return (
    <section id="servicios" aria-labelledby="servicios-title" className="border-y border-line bg-deep py-24 sm:py-32">
      <div className="container-x">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">Servicios</p>
            <h2 id="servicios-title" className="mt-5 font-display text-4xl text-ivory sm:text-5xl">
              Mantenimiento y reparación integral
            </h2>
          </div>
          <p className="max-w-md text-sm leading-relaxed text-silver">
            Cada trabajo comienza con una evaluación profesional. Los costos se informan en una propuesta detallada,
            antes de cualquier intervención.
          </p>
        </div>
        {siteError && <p className="mt-12 text-silver">No fue posible cargar los servicios. Intente nuevamente más tarde.</p>}
        <ul className="mt-14 grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
          {(site?.services ?? Array.from({ length: 9 }, () => null)).map((service, index) => {
            if (!service) return <li key={index} className="h-64 animate-pulse bg-deep" aria-hidden />
            const Icon = SERVICE_ICONS[service.slug] ?? Settings2
            return (
              <li key={service.slug} className="group flex flex-col bg-deep p-8 transition-colors hover:bg-graphite">
                <Icon aria-hidden className="h-8 w-8 text-gold" strokeWidth={1.25} />
                <p className="mt-7 text-[0.65rem] font-semibold uppercase tracking-[0.28em] text-silver">{service.category}</p>
                <h3 className="mt-2 font-display text-2xl text-ivory">{service.name}</h3>
                <p className="mt-3 flex-1 text-sm leading-relaxed text-silver">{service.description}</p>
                {service.price_info && <p className="mt-4 text-sm text-gold-soft">{service.price_info}</p>}
                <button
                  type="button"
                  onClick={() => openAssistant(`Quisiera consultar por el servicio de ${service.name.toLowerCase()}.`)}
                  className="mt-6 inline-flex items-center gap-2 self-start text-[0.7rem] font-semibold uppercase tracking-[0.2em] text-gold-soft hover:text-gold"
                >
                  Consultar
                  <span className="sr-only"> por {service.name}</span>
                  <ArrowRight aria-hidden className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

function Specialties() {
  return (
    <section id="especialidades" aria-labelledby="especialidades-title" className="py-24 sm:py-32">
      <div className="container-x grid gap-14 lg:grid-cols-[1fr_1.15fr] lg:items-center">
        <div className="order-2 lg:order-1">
          <Picture
            name="carbon"
            sizes="(min-width: 1024px) 45vw, 100vw"
            alt="Detalle de la carrocería de fibra de carbono de un superdeportivo"
            className="aspect-[4/3] w-full object-cover"
          />
        </div>
        <div className="order-1 lg:order-2">
          <p className="eyebrow">Especialidades</p>
          <h2 id="especialidades-title" className="mt-5 font-display text-4xl leading-tight text-ivory sm:text-5xl">
            Ingeniería alemana, italiana y británica
          </h2>
          <p className="mt-6 max-w-xl leading-relaxed text-silver">
            Atendemos deportivos, sedanes y SUV de alta gama que requieren conocimiento específico de sus sistemas
            electrónicos, mecánicos y de confort.
          </p>
          <ul className="mt-10 grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
            {BRANDS.map((brand) => (
              <li key={brand} className="flex h-20 items-center justify-center bg-graphite px-2 text-center font-display text-lg tracking-wide text-ivory">
                {brand}
              </li>
            ))}
          </ul>
          <p className="mt-5 text-xs leading-relaxed text-silver">
            Taller independiente. No somos representantes, concesionarios ni servicio oficial de las marcas mencionadas,
            que pertenecen a sus respectivos titulares.
          </p>
        </div>
      </div>
    </section>
  )
}

function Process() {
  return (
    <section id="proceso" aria-labelledby="proceso-title" className="relative isolate overflow-hidden bg-deep py-24 sm:py-32">
      <Picture name="carbon" sizes="100vw" alt="" className="absolute inset-0 -z-10 h-full w-full object-cover opacity-25" />
      <div aria-hidden className="absolute inset-0 -z-10 bg-gradient-to-b from-deep via-deep/85 to-deep" />
      <div className="container-x">
        <p className="eyebrow">Nuestro proceso</p>
        <h2 id="proceso-title" className="mt-5 max-w-2xl font-display text-4xl text-ivory sm:text-5xl">
          Una recepción ordenada, de principio a fin
        </h2>
        <ol className="mt-16 grid gap-x-10 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
          {PROCESS.map(([title, text], index) => (
            <li key={title} className="border-t border-line pt-6">
              <span className="font-display text-4xl text-gold">{String(index + 1).padStart(2, '0')}</span>
              <h3 className="mt-4 text-base font-semibold text-ivory">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-silver">{text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function AssistantSection() {
  const { site, openAssistant } = useSite()
  const points = [
    'Comprende su consulta en lenguaje natural y le pregunta solo lo necesario.',
    'Registra su solicitud únicamente después de que usted confirme el resumen.',
    'Consulta la agenda real del taller para proponer horarios disponibles.',
    'No realiza diagnósticos ni define precios: eso lo hace siempre un profesional.',
  ]
  return (
    <section aria-labelledby="asistente-title" className="py-24 sm:py-32">
      <div className="container-x grid gap-12 border border-line bg-anthracite/40 p-8 sm:p-12 lg:grid-cols-[1fr_1fr] lg:p-16">
        <div>
          <p className="eyebrow">Recepción inteligente</p>
          <h2 id="asistente-title" className="mt-5 font-display text-4xl text-ivory sm:text-5xl">
            Su consulta, atendida en cualquier momento
          </h2>
          <p className="mt-6 leading-relaxed text-silver">
            Nuestro asistente de recepción organiza su solicitud para que el equipo del taller pueda responderle con toda
            la información necesaria.
          </p>
          <button type="button" className="btn-gold mt-10" onClick={() => openAssistant()}>
            Hablar con el asistente
          </button>
          {site?.assistant_mode === 'mock' && (
            <p className="mt-5 text-xs text-silver">
              El asistente funciona actualmente en modo de prueba, con respuestas guiadas y sin inteligencia artificial
              conectada.
            </p>
          )}
        </div>
        <ul className="space-y-6 self-center">
          {points.map((point) => (
            <li key={point} className="flex gap-4">
              <CircleGauge aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-gold" strokeWidth={1.5} />
              <span className="text-sm leading-relaxed text-ivory/90">{point}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function Contact() {
  const { site, openAssistant } = useSite()
  const contact = site?.contact
  const rows: [string, string | undefined, string | undefined][] = [
    ['Teléfono', contact?.phone, contact && !contact.is_placeholder ? `tel:${contact.phone.replace(/[^\d+]/g, '')}` : undefined],
    ['WhatsApp', contact?.whatsapp, contact && !contact.is_placeholder ? `https://wa.me/${contact.whatsapp.replace(/\D/g, '')}` : undefined],
    ['Correo electrónico', contact?.email, contact && !contact.is_placeholder ? `mailto:${contact.email}` : undefined],
    ['Dirección', contact ? `${contact.address}, ${contact.city}` : undefined, contact?.maps_url || undefined],
  ]
  return (
    <section id="contacto" aria-labelledby="contacto-title" className="border-t border-line bg-deep py-24 sm:py-32">
      <div className="container-x grid gap-14 lg:grid-cols-2">
        <div>
          <p className="eyebrow">Contacto</p>
          <h2 id="contacto-title" className="mt-5 font-display text-4xl text-ivory sm:text-5xl">
            Coordinemos la atención de su vehículo
          </h2>
          {contact?.is_placeholder && (
            <p role="note" className="mt-6 border-l-2 border-gold bg-anthracite/60 px-4 py-3 text-sm text-ivory/90">
              Datos de contacto provisionales: serán reemplazados por la información definitiva del taller.
            </p>
          )}
          <dl className="mt-10 divide-y divide-line border-y border-line">
            {rows.map(([label, value, href]) => (
              <div key={label} className="flex flex-col gap-1 py-5 sm:flex-row sm:items-baseline sm:justify-between">
                <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-silver">{label}</dt>
                <dd className="text-ivory">
                  {href ? (
                    <a href={href} className="hover:text-gold-soft" rel="noopener noreferrer" target={href.startsWith('http') ? '_blank' : undefined}>
                      {value}
                    </a>
                  ) : (
                    (value ?? '—')
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="flex flex-col justify-between gap-10 bg-graphite p-8 sm:p-10">
          <div>
            <h3 className="font-display text-2xl text-ivory">Horario de atención</h3>
            <table className="mt-6 w-full text-sm">
              <caption className="sr-only">Horario de atención por día</caption>
              <tbody>
                {(site?.schedule ?? []).map((row) => (
                  <tr key={row.day} className="border-b border-line last:border-0">
                    <th scope="row" className="py-3 text-left font-normal text-silver">
                      {row.day}
                    </th>
                    <td className="py-3 text-right text-ivory">
                      {row.blocks.length ? row.blocks.map(([a, b]) => `${a} a ${b}`).join(' · ') : 'Cerrado'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {contact?.is_placeholder && <p className="mt-4 text-xs text-silver">Horario provisional.</p>}
          </div>
          <div>
            <p className="text-sm text-silver">La forma más rápida de iniciar su solicitud es a través de nuestro asistente.</p>
            <button type="button" className="btn-gold mt-5 w-full" onClick={() => openAssistant()}>
              Solicitar atención
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}

export default function Home() {
  return (
    <>
      <Hero />
      <EntryCards />
      <About />
      <Services />
      <Specialties />
      <Process />
      <AssistantSection />
      <Contact />
    </>
  )
}

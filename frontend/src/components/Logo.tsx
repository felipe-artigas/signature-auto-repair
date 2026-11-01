type SymbolProps = { className?: string; title?: string }

/** Símbolo de la marca: tuerca hexagonal de precisión con rodamiento y marcas de calibración. */
export function LogoSymbol({ className = 'h-10 w-10', title }: SymbolProps) {
  return (
    <svg viewBox="0 0 64 64" className={className} role={title ? 'img' : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2">
        <path d="M32 3.5 56.7 17.75v28.5L32 60.5 7.3 46.25v-28.5Z" />
        <circle cx="32" cy="32" r="12.5" />
        <path d="M32 12v4.5M49.3 42l-3.9-2.25M14.7 42l3.9-2.25" />
      </g>
      <circle cx="32" cy="32" r="3" className="fill-gold-soft" />
    </svg>
  )
}

type LogoProps = { tone?: 'light' | 'dark'; compact?: boolean }

export function Logo({ tone = 'dark', compact = false }: LogoProps) {
  const word = tone === 'dark' ? 'text-graphite' : 'text-ivory'
  const sub = tone === 'dark' ? 'text-anthracite/70' : 'text-silver'
  return (
    <span className="inline-flex items-center gap-3">
      <LogoSymbol className={`${compact ? 'h-9 w-9' : 'h-11 w-11'} text-gold`} />
      <span className="flex flex-col leading-none">
        <span className={`font-display text-[1.45rem] font-medium tracking-[0.22em] ${word}`}>SIGNATURE</span>
        <span className={`mt-1 text-[0.6rem] font-medium tracking-[0.42em] ${sub}`}>AUTO REPAIR</span>
      </span>
    </span>
  )
}

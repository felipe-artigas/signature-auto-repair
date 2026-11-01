type PictureProps = {
  name: 'hero' | 'wheel' | 'carbon' | 'gold'
  alt: string
  sizes: string
  className?: string
  priority?: boolean
}

const VARIANTS: Record<PictureProps['name'], { widths: number[]; ratio: number; fallback: number }> = {
  hero: { widths: [768, 1280, 1920, 2560], ratio: 1674 / 3840, fallback: 1280 },
  wheel: { widths: [640, 1024, 1600], ratio: 3 / 4, fallback: 1024 },
  carbon: { widths: [768, 1280, 1920], ratio: 9 / 21, fallback: 1280 },
  gold: { widths: [640, 1024, 1600], ratio: 3 / 4, fallback: 1024 },
}

export default function Picture({ name, alt, sizes, className, priority = false }: PictureProps) {
  const { widths, ratio, fallback } = VARIANTS[name]
  const srcSet = (ext: string) => widths.map((w) => `/images/${name}-${w}.${ext} ${w}w`).join(', ')
  return (
    <picture>
      <source type="image/avif" srcSet={srcSet('avif')} sizes={sizes} />
      <source type="image/webp" srcSet={srcSet('webp')} sizes={sizes} />
      <img
        src={`/images/${name}-${fallback}.jpg`}
        alt={alt}
        width={fallback}
        height={Math.round(fallback * ratio)}
        loading={priority ? 'eager' : 'lazy'}
        decoding={priority ? 'sync' : 'async'}
        fetchPriority={priority ? 'high' : 'auto'}
        className={className}
      />
    </picture>
  )
}

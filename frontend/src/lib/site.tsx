import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api } from './api'
import type { SiteData } from './types'

type SiteContextValue = {
  site: SiteData | null
  siteError: boolean
  assistantOpen: boolean
  assistantDraft: string
  openAssistant: (draft?: string) => void
  closeAssistant: () => void
}

const SiteContext = createContext<SiteContextValue | null>(null)

export function SiteProvider({ children }: { children: ReactNode }) {
  const [site, setSite] = useState<SiteData | null>(null)
  const [siteError, setSiteError] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [assistantDraft, setAssistantDraft] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    api<SiteData>('/api/public/site', { signal: controller.signal })
      .then(setSite)
      .catch((error) => {
        if (error.name !== 'AbortError') setSiteError(true)
      })
    return () => controller.abort()
  }, [])

  const openAssistant = useCallback((draft = '') => {
    setAssistantDraft(draft)
    setAssistantOpen(true)
  }, [])
  const closeAssistant = useCallback(() => setAssistantOpen(false), [])

  const value = useMemo(
    () => ({ site, siteError, assistantOpen, assistantDraft, openAssistant, closeAssistant }),
    [site, siteError, assistantOpen, assistantDraft, openAssistant, closeAssistant],
  )
  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>
}

export function useSite() {
  const context = useContext(SiteContext)
  if (!context) throw new Error('useSite debe usarse dentro de SiteProvider')
  return context
}

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { RotateCcw, Send, X } from 'lucide-react'

import { api, errorMessage } from '../../lib/api'
import { useSite } from '../../lib/site'
import type { ChatMessage, ConversationState, SummaryLine, TurnResult } from '../../lib/types'
import { LogoSymbol } from '../Logo'

const TOKEN_KEY = 'sar_conversation'
const CONSENT_VERSION = '2026-11'

function readToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
function writeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* almacenamiento no disponible */
  }
}

export default function Assistant() {
  const { assistantOpen, assistantDraft, closeAssistant, site } = useSite()
  const [token, setToken] = useState<string | null>(readToken)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [mode, setMode] = useState(site?.assistant_mode ?? 'mock')
  const [pending, setPending] = useState<SummaryLine[] | null>(null)
  const [consent, setConsent] = useState(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (assistantDraft) setInput(assistantDraft)
  }, [assistantDraft])

  useEffect(() => {
    if (!assistantOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeAssistant()
    window.addEventListener('keydown', onKey)
    inputRef.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [assistantOpen, closeAssistant])

  const load = useCallback(async (t: string) => {
    try {
      const data = await api<ConversationState>('/api/chat/conversation', { headers: { 'X-Conversation-Token': t } })
      setMessages([{ role: 'assistant', content: data.greeting }, ...data.messages])
      setMode(data.mode)
      setPending(data.pending_confirmation)
    } catch {
      writeToken(null)
      setToken(null)
      setMessages([])
    }
  }, [])

  useEffect(() => {
    if (token && messages.length === 0) load(token)
  }, [token, messages.length, load])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy, pending])

  const applyTurn = (result: TurnResult) => {
    setMode(result.mode)
    setMessages((prev) => [...prev, { role: 'assistant', content: result.reply, ui_events: result.ui_events }])
    const confirmation = result.ui_events.find((e) => e.type === 'confirmation')
    setPending(result.status === 'esperando_confirmacion' && confirmation ? confirmation.lines : null)
  }

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const data = await api<{ token: string; greeting: string; mode: 'openai' | 'mock' }>('/api/chat/conversations', {
        method: 'POST',
        body: { consent: true, consent_version: CONSENT_VERSION },
      })
      writeToken(data.token)
      setToken(data.token)
      setMode(data.mode)
      setMessages([{ role: 'assistant', content: data.greeting }])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  const send = async (event?: FormEvent) => {
    event?.preventDefault()
    const text = input.trim()
    if (!text || !token || busy) return
    setInput('')
    setError('')
    setPending(null)
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setBusy(true)
    try {
      applyTurn(
        await api<TurnResult>('/api/chat/messages', {
          method: 'POST',
          body: { message: text },
          headers: { 'X-Conversation-Token': token },
        }),
      )
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    if (!token) return
    setBusy(true)
    setError('')
    try {
      setPending(null)
      setMessages((prev) => [...prev, { role: 'user', content: 'Confirmo los datos del resumen.' }])
      applyTurn(await api<TurnResult>('/api/chat/confirm', { method: 'POST', headers: { 'X-Conversation-Token': token } }))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    writeToken(null)
    setToken(null)
    setMessages([])
    setPending(null)
    setConsent(false)
  }

  if (!assistantOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Cerrar asistente" className="absolute inset-0 bg-deep/70" onClick={closeAssistant} />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="asistente-titulo"
        className="relative flex h-full w-full flex-col border-l border-line bg-graphite sm:max-w-[460px]"
      >
        <header className="flex items-center gap-3 border-b border-line bg-deep px-5 py-4">
          <LogoSymbol className="h-8 w-8 text-gold" />
          <div className="flex-1">
            <h2 id="asistente-titulo" className="font-display text-xl text-ivory">
              Recepción Signature
            </h2>
            <p className="text-[0.65rem] uppercase tracking-[0.2em] text-silver">
              {mode === 'openai' ? 'Asistente con inteligencia artificial' : 'Modo de prueba · sin IA conectada'}
            </p>
          </div>
          {token && (
            <button type="button" onClick={reset} aria-label="Nueva conversación" className="p-2 text-silver hover:text-ivory">
              <RotateCcw className="h-5 w-5" />
            </button>
          )}
          <button type="button" onClick={closeAssistant} aria-label="Cerrar" className="p-2 text-silver hover:text-ivory">
            <X className="h-5 w-5" />
          </button>
        </header>

        {!token ? (
          <div className="flex flex-1 flex-col justify-center gap-6 p-7">
            <p className="font-display text-3xl text-ivory">Bienvenido</p>
            <p className="text-sm leading-relaxed text-silver">
              Nuestro asistente recopila los datos de su consulta y de su vehículo para que el taller pueda responderle.
              No realiza diagnósticos ni define precios.
            </p>
            <label className="flex gap-3 text-sm text-ivory/90">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 h-4 w-4 accent-[#c6a56b]" />
              <span>
                Acepto el tratamiento de mis datos según la{' '}
                <Link to="/privacidad" onClick={closeAssistant} className="text-gold-soft underline">
                  política de privacidad
                </Link>
                .
              </span>
            </label>
            <button type="button" disabled={!consent || busy} onClick={start} className="btn-gold">
              Comenzar
            </button>
            {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
          </div>
        ) : (
          <>
            <div ref={listRef} aria-live="polite" className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.map((m, i) => (
                <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex'}>
                  <p
                    className={`max-w-[85%] whitespace-pre-line px-4 py-3 text-sm leading-relaxed ${
                      m.role === 'user' ? 'bg-gold/15 text-ivory' : 'border border-line bg-anthracite text-ivory/95'
                    }`}
                  >
                    {m.content}
                  </p>
                </div>
              ))}
              {pending && (
                <div className="border border-gold/60 bg-deep p-5">
                  <p className="eyebrow">Resumen de su solicitud</p>
                  <dl className="mt-4 space-y-2 text-sm">
                    {pending.map((line) => (
                      <div key={line.field} className="grid grid-cols-[42%_1fr] gap-2">
                        <dt className="text-silver">{line.label}</dt>
                        <dd className="text-ivory">{line.value}</dd>
                      </div>
                    ))}
                  </dl>
                  <div className="mt-5 flex gap-3">
                    <button type="button" className="btn-gold flex-1" disabled={busy} onClick={confirm}>
                      Confirmar
                    </button>
                    <button type="button" className="btn-ghost flex-1" onClick={() => inputRef.current?.focus()}>
                      Modificar
                    </button>
                  </div>
                </div>
              )}
              {busy && <p className="text-xs uppercase tracking-[0.2em] text-silver">El asistente está escribiendo...</p>}
              {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
            </div>
            <form onSubmit={send} className="border-t border-line bg-deep p-4">
              <label htmlFor="mensaje-asistente" className="sr-only">
                Escriba su mensaje
              </label>
              <div className="flex gap-2">
                <textarea
                  id="mensaje-asistente"
                  ref={inputRef}
                  rows={2}
                  maxLength={1000}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) send(e)
                  }}
                  placeholder="Escriba su mensaje"
                  className="flex-1 resize-none border border-line bg-graphite px-3 py-2 text-sm text-ivory placeholder:text-silver/80 focus:border-gold focus:outline-none"
                />
                <button type="submit" disabled={busy || !input.trim()} aria-label="Enviar" className="btn-gold px-4">
                  <Send className="h-4 w-4" />
                </button>
              </div>
            </form>
          </>
        )}
      </section>
    </div>
  )
}

export type Contact = {
  phone: string
  whatsapp: string
  email: string
  address: string
  city: string
  hours_text: string
  maps_url: string
  instagram: string
  is_placeholder: boolean
}

export type PublicService = {
  slug: string
  name: string
  description: string
  category: string
  price_info: string | null
}

export type SiteData = {
  business_name: string
  contact: Contact
  schedule: { day: string; blocks: [string, string][] }[]
  assistant_mode: 'openai' | 'mock'
  services: PublicService[]
}

export type SummaryLine = { field: string; label: string; value: string }

export type UiEvent = { type: 'confirmation'; lines: SummaryLine[] }

export type ChatMessage = { role: 'user' | 'assistant'; content: string; ui_events?: UiEvent[] }

export type ConversationState = {
  greeting: string
  mode: 'openai' | 'mock'
  status: string
  messages: ChatMessage[]
  pending_confirmation: SummaryLine[] | null
}

export type TurnResult = { reply: string; ui_events: UiEvent[]; status: string; mode: 'openai' | 'mock' }

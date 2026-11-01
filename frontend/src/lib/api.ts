export class ApiError extends Error {
  status: number
  fields?: { field: string; message: string }[]

  constructor(status: number, message: string, fields?: { field: string; message: string }[]) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

type Options = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

export async function api<T>(path: string, { method = 'GET', body, headers = {}, signal }: Options = {}): Promise<T> {
  const finalHeaders: Record<string, string> = { Accept: 'application/json', ...headers }
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken && path.startsWith('/api/admin')) finalHeaders['X-CSRF-Token'] = csrfToken

  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new ApiError(0, 'No fue posible conectar con el servidor. Verifique su conexión.')
  }

  const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : 'Ocurrió un error inesperado.'
    throw new ApiError(response.status, detail, data?.fields)
  }
  return data as T
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.fields?.length) return `${error.message} ${error.fields.map((f) => f.field).join(', ')}`.trim()
    return error.message
  }
  return 'Ocurrió un error inesperado.'
}

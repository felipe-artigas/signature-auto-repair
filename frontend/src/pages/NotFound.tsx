import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <section className="container-x py-32 text-center">
      <h1 className="font-display text-5xl text-ivory">Página no encontrada</h1>
      <Link to="/" className="btn-gold mt-10">
        Volver al inicio
      </Link>
    </section>
  )
}

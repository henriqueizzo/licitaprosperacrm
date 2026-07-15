// Campo de busca reutilizável (Pipeline e Licitações) — filtro client-side,
// case-insensitive e sem acentos.

// Minúsculas e sem acentos, para comparação tolerante ("orgao" acha "Órgão")
export const normalizar = (t) =>
  String(t ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

// true se algum dos campos contém o termo (termo já normalizado)
export const contemTermo = (termoNorm, campos) =>
  campos.some((c) => c && normalizar(c).includes(termoNorm))

export default function CampoBusca({ valor, aoMudar, placeholder = 'Buscar…' }) {
  return (
    <div className="campo-busca">
      <svg
        className="campo-busca-lupa"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <circle cx="11" cy="11" r="7" />
        <line x1="21" y1="21" x2="16.5" y2="16.5" />
      </svg>
      <input
        type="text"
        value={valor}
        onChange={(e) => aoMudar(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
      />
      {valor && (
        <button
          type="button"
          className="campo-busca-limpar"
          onClick={() => aoMudar('')}
          aria-label="Limpar busca"
          title="Limpar busca"
        >
          ×
        </button>
      )}
    </div>
  )
}

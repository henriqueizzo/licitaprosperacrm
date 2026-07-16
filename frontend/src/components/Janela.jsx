// Janela modal do CRM: cabeçalho azul Prospera com controles de janela
// (minimizar ─, expandir ⛶, fechar ✕) e corpo branco sólido rolável.
// Minimizada, vira uma pílula no canto inferior direito e libera a tela.
import { useState } from 'react'

export default function Janela({ titulo, aoFechar, children }) {
  const [modo, setModo] = useState('normal') // normal | min | max

  if (modo === 'min') {
    return (
      <div className="janela-min" title="Restaurar" onClick={() => setModo('normal')}>
        <span className="janela-min-titulo">{titulo}</span>
        <span className="janela-botoes">
          <button type="button" title="Restaurar" aria-label="Restaurar"
            onClick={(e) => { e.stopPropagation(); setModo('normal') }}>⛶</button>
          <button type="button" title="Fechar" aria-label="Fechar"
            onClick={(e) => { e.stopPropagation(); aoFechar() }}>✕</button>
        </span>
      </div>
    )
  }

  const max = modo === 'max'
  return (
    <div className={`modal-fundo${max ? ' modal-fundo-max' : ''}`} onClick={aoFechar}>
      <div className={`janela${max ? ' janela-max' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="janela-cabecalho">
          <strong title={titulo}>{titulo}</strong>
          <span className="janela-botoes">
            <button type="button" title="Minimizar" aria-label="Minimizar"
              onClick={() => setModo('min')}>─</button>
            <button type="button" title={max ? 'Restaurar' : 'Expandir'}
              aria-label={max ? 'Restaurar' : 'Expandir'}
              onClick={() => setModo(max ? 'normal' : 'max')}>⛶</button>
            <button type="button" title="Fechar" aria-label="Fechar" onClick={aoFechar}>✕</button>
          </span>
        </div>
        <div className="janela-corpo">{children}</div>
      </div>
    </div>
  )
}

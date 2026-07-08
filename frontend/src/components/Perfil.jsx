import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Perfil() {
  const [perfil, setPerfil] = useState(null)
  const [msg, setMsg] = useState('')

  useEffect(() => { api.perfil().then(setPerfil).catch((e) => setMsg(e.message)) }, [])

  if (!perfil) return <p>{msg || 'Carregando…'}</p>

  const setLista = (campo) => (e) =>
    setPerfil({ ...perfil, [campo]: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })

  async function salvar() {
    try {
      await api.salvarPerfil(perfil)
      setMsg('✅ Perfil salvo. As próximas análises usarão estes parâmetros.')
    } catch (e) {
      setMsg(`Erro ao salvar: ${e.message}`)
    }
  }

  return (
    <div className="perfil">
      <label>
        Descrição da empresa (o que vende, como atua — a IA usa isso para pontuar aderência)
        <textarea rows={5} value={perfil.descricao}
          onChange={(e) => setPerfil({ ...perfil, descricao: e.target.value })} />
      </label>
      <div className="grade">
        <label>
          UFs de atuação (uma por linha)
          <textarea rows={4} value={(perfil.ufs || []).join('\n')} onChange={setLista('ufs')} />
        </label>
        <label>
          Palavras-chave da coleta (uma por linha)
          <textarea rows={8} value={(perfil.palavras_chave || []).join('\n')} onChange={setLista('palavras_chave')} />
        </label>
        <label>
          Restrições que desclassificam (uma por linha)
          <textarea rows={8} value={(perfil.restricoes || []).join('\n')} onChange={setLista('restricoes')}
            placeholder={'Ex.: Não participamos de licitações com exigência de agência física no município\nEx.: Não atendemos taxa de administração negativa'} />
        </label>
        <label>
          Valor mínimo (R$)
          <input type="number" value={perfil.valor_minimo ?? ''}
            onChange={(e) => setPerfil({ ...perfil, valor_minimo: e.target.value ? Number(e.target.value) : null })} />
        </label>
        <label>
          Valor máximo (R$)
          <input type="number" value={perfil.valor_maximo ?? ''}
            onChange={(e) => setPerfil({ ...perfil, valor_maximo: e.target.value ? Number(e.target.value) : null })} />
        </label>
      </div>
      <button className="primario" onClick={salvar}>Salvar perfil</button>
      {msg && <p className="form-msg">{msg}</p>}
    </div>
  )
}

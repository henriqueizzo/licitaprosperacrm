import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Perfil() {
  const [perfil, setPerfil] = useState(null)
  const [msg, setMsg] = useState('')

  useEffect(() => { api.perfil().then(setPerfil).catch((e) => setMsg(e.message)) }, [])

  if (!perfil) return <p>{msg || 'Carregando…'}</p>

  const setLista = (campo) => (e) =>
    setPerfil({ ...perfil, [campo]: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })
  const setTexto = (campo) => (e) => setPerfil({ ...perfil, [campo]: e.target.value })

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
      <h3 className="perfil-secao">Dados para documentos oficiais</h3>
      <p className="auto-dica">
        Usados nas declarações geradas em Word (botão "Gerar Word" na Documentação):
        cabeçalho da empresa e bloco de assinatura do representante legal.
      </p>
      <div className="grade">
        <label>
          Razão social
          <input value={perfil.razao_social || ''} onChange={setTexto('razao_social')}
            placeholder="Ex.: PROSPERA BENEFÍCIOS S.A." />
        </label>
        <label>
          CNPJ
          <input value={perfil.cnpj || ''} onChange={setTexto('cnpj')}
            placeholder="Ex.: 00.000.000/0001-00" />
        </label>
        <label>
          Endereço da sede
          <input value={perfil.endereco || ''} onChange={setTexto('endereco')}
            placeholder="Ex.: Rua Exemplo, 123, Centro, Porto Alegre/RS, CEP 90000-000" />
        </label>
        <label>
          Cidade/UF (linha de local e data)
          <input value={perfil.cidade_sede || ''} onChange={setTexto('cidade_sede')}
            placeholder="Ex.: Porto Alegre/RS" />
        </label>
        <label>
          Representante legal (nome completo)
          <input value={perfil.representante_nome || ''} onChange={setTexto('representante_nome')}
            placeholder="Ex.: Dario ..." />
        </label>
        <label>
          Cargo do representante
          <input value={perfil.representante_cargo || ''} onChange={setTexto('representante_cargo')}
            placeholder="Ex.: CEO — Prospera Benefícios" />
        </label>
      </div>
      <button className="primario" onClick={salvar}>Salvar perfil</button>
      {msg && <p className="form-msg">{msg}</p>}
    </div>
  )
}

// Wrapper fetch: envia o cookie de sessão e trata 401 globalmente (volta ao login).
let ao401 = null
export function definirAo401(fn) {
  ao401 = fn
}

async function req(url, opts = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...opts })
  if (r.status === 401 && !url.startsWith('/api/auth/')) {
    if (ao401) ao401()
    throw new Error('Sessão expirada — entre novamente')
  }
  if (!r.ok) {
    let msg = `Erro ${r.status}`
    try {
      const dados = await r.json()
      if (typeof dados.detail === 'string') msg = dados.detail
    } catch {
      /* corpo não-JSON: mantém a mensagem genérica */
    }
    throw new Error(msg)
  }
  return r.json()
}

const post = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  // Dashboard executivo (bloco "atividade" só vem para admin)
  dashboard: (dias = 30) => req(`/api/dashboard?dias=${dias}`),
  licitacoes: (params = '') => req(`/api/licitacoes${params}`),
  criarLicitacao: (dados) => req('/api/licitacoes', post(dados)),
  atualizarLicitacao: (id, patch) =>
    req(`/api/licitacoes/${id}`, { ...post(patch), method: 'PATCH' }),
  extrairLicitacao: (texto, url) => req('/api/licitacoes/extrair', post({ texto, url })),
  extrairLicitacaoPdf: (arquivo) => {
    const fd = new FormData()
    fd.append('arquivo', arquivo)
    return req('/api/licitacoes/extrair-arquivo', { method: 'POST', body: fd })
  },
  // Gera a declaração em Word e devolve { blob, nome, origem } ('ia' | 'modelo')
  gerarDeclaracao: async (licitacaoId, documento, referencia = '') => {
    const r = await fetch(`/api/licitacoes/${licitacaoId}/declaracoes`, {
      credentials: 'same-origin',
      ...post({ documento, referencia }),
    })
    if (r.status === 401) {
      if (ao401) ao401()
      throw new Error('Sessão expirada — entre novamente')
    }
    if (!r.ok) {
      let msg = `Erro ${r.status}`
      try {
        const dados = await r.json()
        if (typeof dados.detail === 'string') msg = dados.detail
      } catch { /* corpo não-JSON */ }
      throw new Error(msg)
    }
    const nome = decodeURIComponent(
      (r.headers.get('Content-Disposition') || '').match(/filename\*=UTF-8''([^;]+)/)?.[1] ||
      'declaracao.docx'
    )
    return { blob: await r.blob(), nome, origem: r.headers.get('X-Texto-Origem') || '' }
  },
  oportunidades: () => req('/api/oportunidades'),
  moverOportunidade: (id, estagio) =>
    req(`/api/oportunidades/${id}`, { ...post({ estagio }), method: 'PATCH' }),
  perfil: () => req('/api/perfil'),
  salvarPerfil: (perfil) => req('/api/perfil', { ...post(perfil), method: 'PUT' }),
  executarPipeline: () => req('/api/pipeline/executar', { method: 'POST' }),
  statusPipeline: () => req('/api/pipeline/status'),
  reanalisar: (licitacaoId) => req(`/api/licitacoes/${licitacaoId}/reanalisar`, { method: 'POST' }),
  // Documentação (checklist de habilitação + anexos)
  documentos: (licitacaoId) => req(`/api/licitacoes/${licitacaoId}/documentos`),
  anexarDocumento: (licitacaoId, arquivo, itemChecklist = '') => {
    const fd = new FormData()
    fd.append('arquivo', arquivo)
    if (itemChecklist) fd.append('item_checklist', itemChecklist)
    return req(`/api/licitacoes/${licitacaoId}/documentos`, { method: 'POST', body: fd })
  },
  excluirDocumento: (docId) => req(`/api/documentos/${docId}`, { method: 'DELETE' }),
  urlDownloadDocumento: (docId) => `/api/documentos/${docId}/download`,

  // Autenticação
  me: () => req('/api/auth/me'),
  login: (email, senha) => req('/api/auth/login', post({ email, senha })),
  logout: () => req('/api/auth/logout', { method: 'POST' }),
  trocarSenha: (senhaAtual, senhaNova) =>
    req('/api/auth/trocar-senha', post({ senha_atual: senhaAtual, senha_nova: senhaNova })),

  // Administração de usuários (só admin)
  usuarios: () => req('/api/usuarios'),
  criarUsuario: (dados) => req('/api/usuarios', post(dados)),
  atualizarUsuario: (id, patch) => req(`/api/usuarios/${id}`, { ...post(patch), method: 'PATCH' }),

  // Atividade dos usuários (só admin)
  atividade: (dias = 30) => req(`/api/admin/atividade?dias=${dias}`),
  atividadeEventos: ({ usuarioId = null, dias = 30, limit = 100 } = {}) => {
    const p = new URLSearchParams({ dias, limit })
    if (usuarioId) p.set('usuario_id', usuarioId)
    return req(`/api/admin/atividade/eventos?${p}`)
  },
}

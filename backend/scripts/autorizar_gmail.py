"""Autoriza o CRM a LER a caixa do Gmail (aba "E-mails do Dario") — roda UMA vez, no PC.

Pré-requisito (5 min no console do Google Cloud, no mesmo projeto da chave do Gemini
serve): https://console.cloud.google.com/
  1. APIs e serviços -> Biblioteca -> "Gmail API" -> Ativar.
  2. APIs e serviços -> Tela de permissão OAuth -> tipo "Interno" (conta Google
     Workspace) ou "Externo" + adicionar seu e-mail como usuário de teste.
  3. APIs e serviços -> Credenciais -> Criar credenciais -> ID do cliente OAuth ->
     tipo "App para computador" (Desktop). Copie o Client ID e o Client secret.

Uso (de dentro de backend/):
  .venv\\Scripts\\python.exe scripts\\autorizar_gmail.py --client-id XXX --client-secret YYY

O script abre o navegador para você entrar com a conta que RECEBE os e-mails do
Dario (henrique.izzo@prosperabeneficios.com) e aceitar o escopo "ler e-mails".
No fim imprime as três variáveis para colocar no .env local e nas env vars do
Render (GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN). O refresh token
não expira enquanto o acesso não for revogado (em "Externo" sem publicar, expira em
7 dias — prefira "Interno" ou publique o app).

Escopo pedido: gmail.readonly (o CRM nunca envia, apaga nem marca nada).
"""
import argparse
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

ESCOPO = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORTA = 8765
REDIRECT = f"http://localhost:{PORTA}/"


class _Receptor(http.server.BaseHTTPRequestHandler):
    codigo: str | None = None
    estado: str | None = None
    erro: str | None = None

    def do_GET(self):  # noqa: N802 (nome exigido pelo BaseHTTPRequestHandler)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if params.get("state", [""])[0] != _Receptor.estado:
            _Receptor.erro = "state inválido (resposta não veio do fluxo iniciado aqui)"
        elif "code" in params:
            _Receptor.codigo = params["code"][0]
        else:
            _Receptor.erro = params.get("error", ["sem código"])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Autorizado! Pode fechar esta aba e voltar ao terminal." if _Receptor.codigo else f"Falhou: {_Receptor.erro}"
        self.wfile.write(f"<html><body style='font-family:sans-serif'><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *args):  # silencia o log do servidor
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    ap.add_argument("--sem-navegador", action="store_true", help="só imprime o URL (abra você mesmo)")
    args = ap.parse_args()

    _Receptor.estado = secrets.token_urlsafe(16)
    servidor = http.server.HTTPServer(("localhost", PORTA), _Receptor)
    threading.Thread(target=servidor.handle_request, daemon=True).start()

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": args.client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": ESCOPO,
        "access_type": "offline",   # devolve refresh_token
        "prompt": "consent",        # força refresh_token mesmo se já autorizou antes
        "state": _Receptor.estado,
    })
    print("\n1) Entre com a conta que RECEBE os e-mails do Dario e aceite o acesso de leitura.")
    print("   Se o navegador não abrir, cole este endereço:\n   " + url + "\n")
    if not args.sem_navegador:
        webbrowser.open(url)
    print(f"2) Aguardando a autorização em {REDIRECT} ...")
    servidor.server_close() if False else None
    # handle_request já está rodando na thread; espera o código chegar
    import time
    for _ in range(600):  # até 10 min
        if _Receptor.codigo or _Receptor.erro:
            break
        time.sleep(1)
    if not _Receptor.codigo:
        print(f"\nNão recebi a autorização: {_Receptor.erro or 'tempo esgotado'}")
        return 1

    resp = httpx.post(TOKEN_URL, data={
        "code": _Receptor.codigo,
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }, timeout=30)
    if resp.status_code != 200:
        print("\nO Google recusou a troca do código:", resp.status_code, resp.text[:300])
        return 1
    dados = resp.json()
    refresh = dados.get("refresh_token")
    if not refresh:
        print("\nVeio access_token mas NÃO veio refresh_token — revogue o acesso do app em "
              "https://myaccount.google.com/permissions e rode de novo.")
        return 1

    # Confirma que o token funciona e mostra para quem é
    perfil = httpx.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": f"Bearer {dados['access_token']}"}, timeout=30,
    )
    conta = perfil.json().get("emailAddress", "?") if perfil.status_code == 200 else "?"

    print("\n3) Pronto. Conta autorizada:", conta)
    print("   Coloque estas três linhas no backend/.env (local) e nas Environment Variables do Render:\n")
    print(f"GMAIL_CLIENT_ID={args.client_id}")
    print(f"GMAIL_CLIENT_SECRET={args.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={refresh}")
    print("\n   (não comite esses valores — o .env está no .gitignore)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

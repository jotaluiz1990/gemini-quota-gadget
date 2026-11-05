"""Módulo para autenticação interativa e captura automática de cookies do Claude (claude.ai).

Abre uma janela de navegador nativo (Edge WebView2) para o usuário fazer login
no Claude (suporte a Google login, email e 2FA), detecta o cookie de sessão (sessionKey)
e o exporta automaticamente sem necessidade de abrir o DevTools (F12).
"""

import json
import os
import sys
import time
import webview

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def get_claude_session_storage_path() -> str:
    """Retorna o caminho estável para persistência da sessão do Claude no WebView2."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    # 1. Diretório principal
    p1 = os.path.join(base, ".claude_session")
    if os.path.exists(p1):
        return p1

    # 2. Se rodando a partir da raiz mas compilado gerou na pasta dist
    p2 = os.path.join(base, "dist", ".claude_session")
    if os.path.exists(p2):
        return p2

    # 3. Se rodando a partir de dist mas a raiz tiver a pasta
    p3 = os.path.join(os.path.dirname(base), ".claude_session")
    if os.path.exists(p3):
        return p3

    return p1


def has_saved_claude_session() -> bool:
    """Verifica se já existe uma sessão gravada no disco."""
    path = get_claude_session_storage_path()
    if not os.path.exists(path):
        return False
    ebwebview = os.path.join(path, "EBWebView")
    return os.path.exists(ebwebview)


def monitor_claude_cookies(window: webview.Window):
    """Monitora a sessão do usuário até encontrar o sessionKey do Claude (Modo Interativo)."""
    max_wait_seconds = 300  # 5 minutos para o usuário fazer login
    start_time = time.time()
    time.sleep(2.0)

    while time.time() - start_time < max_wait_seconds:
        time.sleep(1.5)
        try:
            curr_url = ""
            try:
                curr_url = window.get_current_url() or ""
            except Exception:
                pass

            # Se ainda estiver no fluxo de login do Google ou login do Claude, aguarda
            if "accounts.google.com" in curr_url or "claude.ai/login" in curr_url or "/auth" in curr_url:
                continue

            cookies = window.get_cookies()
            if not cookies:
                continue

            cookie_dict = {}
            for item in cookies:
                for k, v in item.items():
                    cookie_dict[k] = v.value

            # Procura por sessionKey ou __sessionKey ou token com prefixo sk-ant-sid
            session_key = None
            for k, v in cookie_dict.items():
                if k.lower() in ("sessionkey", "__sessionkey") or v.startswith("sk-ant-sid"):
                    session_key = v
                    break

            if session_key:
                cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
                result = {
                    "success": True,
                    "cookie_header": cookie_header,
                    "sessionKey": session_key,
                }
                print("CLAUDE_LOGIN_SUCCESS:" + json.dumps(result), flush=True)
                time.sleep(1.2)
                window.destroy()
                return

        except Exception:
            pass

    print("CLAUDE_LOGIN_TIMEOUT", flush=True)
    try:
        window.destroy()
    except Exception:
        pass


def run_claude_login_window():
    """Abre a janela de login interativo do Claude Web visível e em primeiro plano."""
    storage_path = get_claude_session_storage_path()
    os.makedirs(storage_path, exist_ok=True)

    window = webview.create_window(
        title="Login Anthropic Claude - Gemini Quota Gadget",
        url="https://claude.ai/login",
        width=580,
        height=740,
        resizable=True,
        on_top=True,
    )

    webview.start(
        monitor_claude_cookies,
        window,
        user_agent=CHROME_USER_AGENT,
        private_mode=False,
        storage_path=storage_path,
    )


def run_silent_claude_refresh():
    """Executa a renovação silenciosa de cookies em background (hidden=True, zero GUI)."""
    storage_path = get_claude_session_storage_path()
    if not os.path.exists(storage_path):
        print("CLAUDE_REFRESH_NO_SESSION", flush=True)
        return

    def on_loaded(window: webview.Window):
        max_attempts = 15
        for _ in range(max_attempts):
            time.sleep(1.0)
            try:
                cookies = window.get_cookies()
                if not cookies:
                    continue
                cookie_dict = {}
                for item in cookies:
                    for k, v in item.items():
                        cookie_dict[k] = v.value

                session_key = None
                for k, v in cookie_dict.items():
                    if k.lower() in ("sessionkey", "__sessionkey") or v.startswith("sk-ant-sid"):
                        session_key = v
                        break

                if session_key:
                    cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
                    result = {
                        "success": True,
                        "cookie_header": cookie_header,
                        "sessionKey": session_key,
                    }
                    print("CLAUDE_REFRESH_SUCCESS:" + json.dumps(result), flush=True)
                    window.destroy()
                    return
            except Exception:
                pass

        print("CLAUDE_REFRESH_TIMEOUT", flush=True)
        try:
            window.destroy()
        except Exception:
            pass

    try:
        window = webview.create_window(
            title="Silent Claude Refresh",
            url="https://claude.ai/",
            hidden=True,
        )
        webview.start(
            on_loaded,
            window,
            user_agent=CHROME_USER_AGENT,
            private_mode=False,
            storage_path=storage_path,
        )
    except Exception as e:
        print(f"CLAUDE_REFRESH_ERROR:{e}", flush=True)


if __name__ == "__main__":
    if "--silent" in sys.argv:
        run_silent_claude_refresh()
    else:
        run_claude_login_window()

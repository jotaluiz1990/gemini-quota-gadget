"""Módulo para autenticação interativa e renovação silenciosa de cookies do Google Gemini.

Abre uma janela de navegador nativo (Edge WebView2) para o usuário fazer login
no Gemini ou executa em segundo plano (hidden=True, zero UI) para renovar
automaticamente os tokens da sessão persistente (.gemini_session).
"""

import json
import os
import sys
import time
from typing import Optional
import webview

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def get_session_storage_path() -> str:
    """Retorna o caminho estável para persistência da sessão do WebView2."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    # 1. Diretório principal
    p1 = os.path.join(base, ".gemini_session")
    if os.path.exists(p1):
        return p1

    # 2. Se rodando a partir da raiz mas compilado gerou na pasta dist
    p2 = os.path.join(base, "dist", ".gemini_session")
    if os.path.exists(p2):
        return p2

    # 3. Se rodando a partir de dist mas a raiz tiver a pasta
    p3 = os.path.join(os.path.dirname(base), ".gemini_session")
    if os.path.exists(p3):
        return p3

    return p1


def has_saved_session() -> bool:
    """Verifica se já existe uma sessão gravada no disco."""
    path = get_session_storage_path()
    if not os.path.exists(path):
        return False
    ebwebview = os.path.join(path, "EBWebView")
    return os.path.exists(ebwebview)


def monitor_cookies(window: webview.Window):
    """Monitora a sessão do usuário até encontrar os cookies de autenticação do Gemini (Modo Interativo)."""
    max_wait_seconds = 300  # 5 minutos para o usuário fazer login
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        time.sleep(1.5)
        try:
            cookies = window.get_cookies()
            if not cookies:
                continue

            cookie_dict = {}
            for cookie_item in cookies:
                for k, v in cookie_item.items():
                    cookie_dict[k] = v.value

            # Se encontrou o cookie principal de sessão do Google
            if "__Secure-1PSID" in cookie_dict:
                cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])

                result = {
                    "success": True,
                    "cookie_header": cookie_header,
                    "1PSID": cookie_dict.get("__Secure-1PSID", ""),
                    "1PSIDTS": cookie_dict.get("__Secure-1PSIDTS", ""),
                }
                print("LOGIN_SUCCESS:" + json.dumps(result), flush=True)

                time.sleep(1.0)
                window.destroy()
                return

        except Exception:
            pass

    print("LOGIN_TIMEOUT", flush=True)
    try:
        window.destroy()
    except Exception:
        pass


def run_login_window():
    """Abre a janela de login interativo do Gemini Web."""
    storage_path = get_session_storage_path()
    os.makedirs(storage_path, exist_ok=True)

    window = webview.create_window(
        title="Login Google Gemini - Gemini Quota Gadget",
        url="https://gemini.google.com/app",
        width=560,
        height=720,
        resizable=True,
    )

    webview.start(
        monitor_cookies,
        window,
        user_agent=CHROME_USER_AGENT,
        private_mode=False,
        storage_path=storage_path,
    )


def run_silent_refresh():
    """Executa a renovação silenciosa de cookies em background (hidden=True, zero GUI)."""
    storage_path = get_session_storage_path()
    if not os.path.exists(storage_path):
        print("REFRESH_NO_SESSION", flush=True)
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

                if "__Secure-1PSID" in cookie_dict:
                    cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
                    result = {
                        "success": True,
                        "cookie_header": cookie_header,
                        "1PSID": cookie_dict.get("__Secure-1PSID", ""),
                        "1PSIDTS": cookie_dict.get("__Secure-1PSIDTS", ""),
                    }
                    print("REFRESH_SUCCESS:" + json.dumps(result), flush=True)
                    window.destroy()
                    return
            except Exception:
                pass

        print("REFRESH_TIMEOUT", flush=True)
        try:
            window.destroy()
        except Exception:
            pass

    try:
        window = webview.create_window(
            title="Silent Gemini Refresh",
            url="https://gemini.google.com/app",
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
        print(f"REFRESH_ERROR:{e}", flush=True)


if __name__ == "__main__":
    if "--silent" in sys.argv:
        run_silent_refresh()
    else:
        run_login_window()

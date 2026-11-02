"""Módulo para autenticação interativa e captura automática de cookies do Google Gemini.

Abre uma janela de navegador nativo (Edge WebView2) para o usuário fazer login
no Gemini, detecta os cookies de sessão (__Secure-1PSID, __Secure-1PSIDTS, etc.)
e os exporta automaticamente sem necessidade de abrir o DevTools (F12).
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

# Diretório base
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STORAGE_PATH = os.path.join(BASE_DIR, ".gemini_session")


def monitor_cookies(window: webview.Window):
    """Monitora a sessão do usuário até encontrar os cookies de autenticação do Gemini."""
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
                # Cada item retornado por get_cookies é um SimpleCookie
                for k, v in cookie_item.items():
                    cookie_dict[k] = v.value

            # Se encontrou o cookie principal de sessão do Google
            if "__Secure-1PSID" in cookie_dict:
                # Monta cabeçalho Cookie completo formatado
                cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])

                result = {
                    "success": True,
                    "cookie_header": cookie_header,
                    "1PSID": cookie_dict.get("__Secure-1PSID", ""),
                    "1PSIDTS": cookie_dict.get("__Secure-1PSIDTS", ""),
                }
                # Emite resultado estruturado para stdout
                print("LOGIN_SUCCESS:" + json.dumps(result), flush=True)

                time.sleep(1.0)
                window.destroy()
                return

        except Exception as e:
            pass

    print("LOGIN_TIMEOUT", flush=True)
    try:
        window.destroy()
    except Exception:
        pass


def run_login_window():
    """Abre a janela de login do Gemini Web."""
    os.makedirs(STORAGE_PATH, exist_ok=True)

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
        storage_path=STORAGE_PATH,
    )


if __name__ == "__main__":
    run_login_window()

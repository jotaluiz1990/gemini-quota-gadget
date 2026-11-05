"""Gemini Quota Gadget - Monitor Desktop em Tempo Real de Cotas do Antigravity e Gemini Web.

Widget flutuante para Windows (frameless, cantos arredondados, topmost, drag-and-drop, redimensionável, system tray)
que se conecta diretamente ao serviço local do Antigravity e à interface do Gemini Web (PRO)
para exibir o consumo real e contagem regressiva + data/hora de reset dos modelos de IA.
"""

import copy
import ctypes
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
if sys.platform == "win32":
    import winreg
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

from gemini_web_client import GeminiWebClient
from gemini_login_window import has_saved_session
from claude_web_client import ClaudeWebClient
from claude_login_window import has_saved_claude_session

# Modo auxiliar para captura ou renovação de cookies via WebView2
if "--login-webview" in sys.argv:
    from gemini_login_window import run_login_window
    run_login_window()
    sys.exit(0)

if "--silent-cookie-refresh" in sys.argv:
    from gemini_login_window import run_silent_refresh
    run_silent_refresh()
    sys.exit(0)

if "--login-claude-webview" in sys.argv:
    from claude_login_window import run_claude_login_window
    run_claude_login_window()
    sys.exit(0)

if "--silent-claude-cookie-refresh" in sys.argv:
    from claude_login_window import run_silent_claude_refresh
    run_silent_claude_refresh()
    sys.exit(0)

# Diretório base para persistência (suporte a script .py e executável .exe)
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(BASE_DIR, "quota_data.json")

AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_APP_NAME = "GeminiQuotaGadget"


def is_autostart_enabled() -> bool:
    """Verifica se o app está configurado para iniciar junto com o Windows."""
    if sys.platform != "win32":
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, AUTOSTART_APP_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart_enabled(enable: bool) -> bool:
    """Ativa ou desativa a inicialização automática no Registro do Windows."""
    if sys.platform != "win32":
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                pyw = sys.executable.replace("python.exe", "pythonw.exe")
                main_py = os.path.abspath(__file__)
                cmd = f'"{pyw}" "{main_py}"'
            winreg.SetValueEx(key, AUTOSTART_APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Erro ao atualizar autostart no Windows: {e}")
        return False

# Configurações padrão
DEFAULT_SETTINGS: Dict[str, Any] = {
    "window_state": {
        "x": None,
        "y": None,
        "width": 280,
        "height": 450,
    },
    "visible_groups": [
        "Gemini Models",
        "Gemini 4 Argon",
        "Claude and GPT models",
    ],
    "refresh_interval_sec": 30,
    "gemini_web_enabled": False,
    "gemini_web_cookie": "",
    "claude_web_enabled": False,
    "claude_web_cookie": "",
    "last_known_quota": None,
    "last_known_gemini_web": None,
    "last_known_claude_web": None,
    "font_size": "Médio",
    "opacity": 0.95,
    "display_mode": "% Restante",
}

MIN_WIDTH = 230
MIN_HEIGHT = 200
MAX_WIDTH = 800
MAX_HEIGHT = 1200

TRANSPARENT_KEY = "#010101"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _run_hidden_cmd(cmd_list: List[str], timeout_sec: float = 6.0) -> str:
    """Executa comando em segundo plano no Windows sem NUNCA abrir janela de console (Zero Popup)."""
    si = None
    flags = 0
    if sys.platform == "win32":
        flags |= 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
    try:
        return subprocess.check_output(
            cmd_list,
            text=True,
            errors="ignore",
            startupinfo=si,
            creationflags=flags,
            timeout=timeout_sec,
        ).strip()
    except Exception:
        return ""


def parse_to_utc_datetime(iso_val: Optional[Any]) -> Optional[datetime]:
    """Converte com segurança qualquer string ISO ou timestamp para datetime ciente em UTC."""
    if not iso_val:
        return None
    try:
        if isinstance(iso_val, (int, float)):
            ts = float(iso_val)
            if ts > 1e11:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        s = str(iso_val).strip()
        if s.isdigit():
            ts = float(s)
            if ts > 1e11:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def calculate_projected_ag_data(last_known: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    """Calcula os valores previstos para cada bucket com base na data/hora de reset salva."""
    groups = copy.deepcopy(last_known.get("groups", []))
    saved_ts = last_known.get("timestamp", "")
    last_read_str = ""
    if saved_ts:
        dt = parse_to_utc_datetime(saved_ts)
        if dt:
            last_read_str = dt.astimezone().strftime("%H:%M")

    now_utc = datetime.now(timezone.utc)

    for group in groups:
        for b in group.get("buckets", []):
            reset_iso = b.get("resetTime")
            if not reset_iso:
                continue

            target_utc = parse_to_utc_datetime(reset_iso)
            if not target_utc:
                continue

            diff_sec = int((target_utc - now_utc).total_seconds())
            if diff_sec <= 0:
                # O reset previsto já passou! A cota foi restabelecida para 100%!
                b["remainingFraction"] = 1.0
                b["is_reset_restored"] = True

                window = b.get("window", "")
                bucket_id = b.get("bucketId", "")

                if window == "5h" or "-5h" in bucket_id:
                    cycle = timedelta(hours=5)
                elif window == "weekly" or "weekly" in bucket_id:
                    cycle = timedelta(days=7)
                else:
                    cycle = timedelta(hours=5)

                while target_utc <= now_utc:
                    target_utc += cycle

                b["resetTime"] = target_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    return groups, last_read_str


def calculate_projected_gw_data(last_known: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Calcula estimativa para o Gemini Web se a data/hora de reset já tiver passado."""
    data = copy.deepcopy(last_known.get("data", {}))
    saved_ts = last_known.get("timestamp", "")
    last_read_str = ""
    if saved_ts:
        dt = parse_to_utc_datetime(saved_ts)
        if dt:
            last_read_str = dt.astimezone().strftime("%H:%M")

    now_epoch = datetime.now(timezone.utc).timestamp()

    # Reset Atual
    cur_epoch = data.get("current_reset_epoch")
    if cur_epoch and now_epoch >= cur_epoch:
        data["current_remaining_pct"] = 100.0
        data["current_used_pct"] = 0.0
        data["current_reset_text"] = "⏱ Cota restaurada (100%)"

    # Reset Semanal
    wk_epoch = data.get("weekly_reset_epoch")
    if wk_epoch and now_epoch >= wk_epoch:
        data["weekly_remaining_pct"] = 100.0
        data["weekly_used_pct"] = 0.0
        data["weekly_reset_text"] = "⏱ Limite semanal restaurado (100%)"

    return data, last_read_str


def calculate_projected_claude_data(last_known: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Calcula estimativa para o Claude Web se a data/hora de reset já tiver passado."""
    data = copy.deepcopy(last_known.get("data", {}))
    saved_ts = last_known.get("timestamp", "")
    last_read_str = ""
    if saved_ts:
        dt = parse_to_utc_datetime(saved_ts)
        if dt:
            last_read_str = dt.astimezone().strftime("%H:%M")

    now_epoch = datetime.now(timezone.utc).timestamp()

    # 1. Reset da janela de 5 horas
    fh_epoch = data.get("five_hour_reset_epoch")
    if fh_epoch and now_epoch >= fh_epoch:
        data["five_hour_remaining_pct"] = 100.0
        data["five_hour_used_pct"] = 0.0
        data["five_hour_reset_text"] = "⏱ Cota de sessão restaurada (100%)"

    # 2. Reset do limite semanal (7 dias)
    wk_epoch = data.get("weekly_reset_epoch")
    if wk_epoch and now_epoch >= wk_epoch:
        data["weekly_remaining_pct"] = 100.0
        data["weekly_used_pct"] = 0.0
        data["weekly_reset_text"] = "⏱ Limite semanal restaurado (100%)"

    return data, last_read_str


def format_reset_info(reset_time_iso: Optional[str], is_restored: bool = False) -> str:
    """Calcula a contagem regressiva e a data/hora local de redefinição."""
    if not reset_time_iso:
        return ""
    try:
        target_utc = parse_to_utc_datetime(reset_time_iso)
        if not target_utc:
            return ""

        local_dt = target_utc.astimezone()
        now_dt = datetime.now(timezone.utc)
        diff = target_utc - now_dt
        total_seconds = int(diff.total_seconds())

        if total_seconds <= 0:
            if is_restored:
                return "⏱ Cota restaurada (100%)"
            return f"⏱ Reset já ocorrido ({local_dt.strftime('%d/%m às %H:%M')})"

        days = total_seconds // 86400
        rem_sec = total_seconds % 86400
        hours = rem_sec // 3600
        mins = (rem_sec % 3600) // 60

        if days > 0:
            countdown = f"{days}d {hours}h" if hours > 0 else f"{days}d"
        elif hours > 0:
            countdown = f"{hours}h {mins}m" if mins > 0 else f"{hours}h"
        elif mins > 0:
            countdown = f"{mins}m"
        else:
            countdown = "<1m"

        date_str = local_dt.strftime("%d/%m às %H:%M")
        if is_restored:
            return f"⏱ Reseta em {countdown} • {date_str} (Restaurada)"
        return f"⏱ Reseta em {countdown} • {date_str}"
    except Exception:
        return ""


def get_color_for_remaining(fraction: float) -> str:
    """Retorna código de cor baseado no percentual restante (verde, amarelo ou vermelho)."""
    if fraction <= 0.20:
        return "#ef4444"  # Vermelho Alerta (<= 20%)
    elif fraction <= 0.50:
        return "#f59e0b"  # Amarelo/Laranja Atenção (<= 50%)
    else:
        return "#10b981"  # Verde Saudável (> 50%)


def get_color_for_used(fraction_used: float) -> str:
    """Retorna código de cor baseado no percentual USADO (verde se pouco usado, vermelho se muito usado)."""
    if fraction_used >= 0.80:
        return "#ef4444"  # Vermelho Alerta (>= 80% usado)
    elif fraction_used >= 0.50:
        return "#f59e0b"  # Amarelo Atenção (>= 50% usado)
    else:
        return "#10b981"  # Verde Confortável (< 50% usado)


def generate_tray_icon_image() -> Image.Image:
    """Gera um ícone moderno de bandeja em memória (RGBA)."""
    image = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill="#1e1e28")
    draw.ellipse([14, 14, 50, 50], outline="#10b981", width=5)
    draw.ellipse([24, 24, 40, 40], fill="#3b8ed0")
    return image


class AntigravityQuotaClient:
    """Cliente para descoberta de processo local e consulta de cotas do Antigravity."""

    def __init__(self):
        self.cached_pid: Optional[int] = None
        self.cached_port: Optional[int] = None
        self.cached_csrf: Optional[str] = None

    def fetch_quota(self) -> Optional[List[Dict[str, Any]]]:
        """Tenta consultar utilizando dados cacheados; se falhar, redescobre o serviço silenciosamente."""
        if self.cached_port and self.cached_csrf:
            data = self._query_port(self.cached_port, self.cached_csrf)
            if data is not None:
                return data

        # Porta em cache falhou ou não existe, limpa e redescobre
        self.cached_port = None
        self.cached_csrf = None
        return self._discover_service()

    def _discover_service(self) -> Optional[List[Dict[str, Any]]]:
        """Localiza o language_server.exe, extrai a flag --csrf_token e descobre a porta de escuta."""
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | "
                "Select-Object ProcessId, CommandLine | ConvertTo-Json"
            )
            out = _run_hidden_cmd(["powershell", "-NoProfile", "-Command", ps_cmd])

            if not out:
                return None

            proc_info = json.loads(out)
            if isinstance(proc_info, list):
                proc_info = proc_info[0]

            pid = proc_info.get("ProcessId")
            cmdline = proc_info.get("CommandLine", "")

            csrf_match = re.search(r"--csrf_token\s+([a-f0-9\-]+)", cmdline)
            if not csrf_match or not pid:
                return None

            csrf_token = csrf_match.group(1)

            ports_cmd = (
                f"Get-NetTCPConnection -OwningProcess {pid} -State Listen "
                "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort"
            )
            ports_out = _run_hidden_cmd(["powershell", "-NoProfile", "-Command", ports_cmd])

            ports = [int(p) for p in ports_out.split() if p.isdigit()]

            for port in ports:
                data = self._query_port(port, csrf_token)
                if data is not None:
                    self.cached_pid = pid
                    self.cached_port = port
                    self.cached_csrf = csrf_token
                    return data

            return None
        except Exception:
            return None

    def _query_port(self, port: int, csrf_token: str) -> Optional[List[Dict[str, Any]]]:
        """Executa a chamada Connect-RPC para RetrieveUserQuotaSummary."""
        url = f"http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "x-codeium-csrf-token": csrf_token,
                "Connect-Protocol-Version": "1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    return payload.get("response", {}).get("groups", [])
        except Exception:
            pass
        return None


class SettingsWindow(ctk.CTkToplevel):
    """Janela modal para seleção dos modelos e configuração dos cookies do Gemini Web."""

    def __init__(self, parent: "GeminiQuotaWidget", available_groups: List[str]):
        super().__init__(parent)
        self.parent = parent
        self.available_groups = available_groups

        self.title("Configurações de Cotas e Modelos")
        self.geometry("390x660")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(parent)

        px = parent.winfo_x() - 30
        py = parent.winfo_y() - 30
        self.geometry(f"+{max(10, px)}+{max(10, py)}")

        self.initial_opacity = float(self.parent.settings.get("opacity", 0.95))
        self.check_vars: Dict[str, ctk.BooleanVar] = {}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self.focus_force()

    def _build_ui(self):
        container = ctk.CTkFrame(self, corner_radius=12, fg_color="#18181f")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Scrollable container para caber tudo confortavelmente
        scroll_main = ctk.CTkScrollableFrame(container, fg_color="transparent")
        scroll_main.pack(fill="both", expand=True, padx=4, pady=4)

        # Seção 1: Modelos do Antigravity
        lbl_sec1 = ctk.CTkLabel(
            scroll_main,
            text="Modelos do Antigravity (IDE)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        lbl_sec1.pack(anchor="w", padx=8, pady=(4, 4))

        grp_box = ctk.CTkFrame(scroll_main, fg_color="#1e1e28", corner_radius=8)
        grp_box.pack(fill="x", padx=6, pady=(0, 10))

        current_visible = set(self.parent.settings.get("visible_groups", []))
        all_groups = list(dict.fromkeys(self.available_groups + list(current_visible)))
        if not all_groups:
            all_groups = DEFAULT_SETTINGS["visible_groups"]

        for grp in all_groups:
            is_active = grp in current_visible
            var = ctk.BooleanVar(value=is_active)
            self.check_vars[grp] = var

            chk = ctk.CTkCheckBox(
                grp_box,
                text=grp,
                variable=var,
                font=ctk.CTkFont(size=12, weight="bold" if "Gemini" in grp else "normal"),
                checkbox_width=18,
                checkbox_height=18,
                corner_radius=4,
            )
            chk.pack(anchor="w", padx=10, pady=6)

        # Seção 2: Gemini Web (PRO)
        lbl_sec2 = ctk.CTkLabel(
            scroll_main,
            text="Google Gemini Web (PRO)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        lbl_sec2.pack(anchor="w", padx=8, pady=(6, 4))

        web_box = ctk.CTkFrame(scroll_main, fg_color="#1e1e28", corner_radius=8)
        web_box.pack(fill="x", padx=6, pady=(0, 10))

        self.var_web_enabled = ctk.BooleanVar(value=self.parent.settings.get("gemini_web_enabled", False))
        self.chk_web = ctk.CTkCheckBox(
            web_box,
            text="Ativar Monitoramento do Gemini Web (PRO)",
            variable=self.var_web_enabled,
            font=ctk.CTkFont(size=12, weight="bold"),
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
        )
        self.chk_web.pack(anchor="w", padx=10, pady=(10, 8))

        session_active = has_saved_session()
        btn_text = "🔄 Reconectar / Trocar de Conta Google" if session_active else "🌐 Fazer Login no Gemini (Captura Automática)"
        status_text = "● Sessão persistente ativa (Renovação automática contínua ativada ✓)" if session_active else "Faça login uma vez; o gadget manterá a sessão conectada continuamente."
        status_color = "#10b981" if session_active else "#888899"

        # Botão de Login Direto com Captura Automática
        self.btn_login = ctk.CTkButton(
            web_box,
            text=btn_text,
            height=32,
            fg_color="#1a73e8",
            hover_color="#1557b0",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._start_login_flow,
        )
        self.btn_login.pack(fill="x", padx=10, pady=(0, 4))

        self.lbl_login_status = ctk.CTkLabel(
            web_box,
            text=status_text,
            font=ctk.CTkFont(size=10),
            text_color=status_color,
            justify="left",
            wraplength=310,
        )
        self.lbl_login_status.pack(anchor="w", padx=10, pady=(0, 8))

        # Separador / Opção Manual
        lbl_or = ctk.CTkLabel(
            web_box,
            text="─── ou configurar cookies manualmente ───",
            font=ctk.CTkFont(size=10),
            text_color="#555566",
        )
        lbl_or.pack(fill="x", padx=10, pady=(2, 6))

        lbl_cookie = ctk.CTkLabel(
            web_box,
            text="Cookies de Sessão:",
            font=ctk.CTkFont(size=11),
            text_color="#cccccc",
        )
        lbl_cookie.pack(anchor="w", padx=10, pady=(2, 2))

        self.entry_cookie = ctk.CTkEntry(
            web_box,
            placeholder_text="Cookies capturados automaticamente pelo botão acima",
            height=28,
            font=ctk.CTkFont(size=11),
        )
        saved_cookie = self.parent.settings.get("gemini_web_cookie", "")
        if saved_cookie:
            self.entry_cookie.insert(0, saved_cookie)
        self.entry_cookie.pack(fill="x", padx=10, pady=(0, 6))

        # Botão Testar Conexão
        self.lbl_test_result = ctk.CTkLabel(web_box, text="", font=ctk.CTkFont(size=10))
        self.lbl_test_result.pack(anchor="w", padx=10, pady=(0, 4))

        self.btn_test = ctk.CTkButton(
            web_box,
            text="Testar Conexão Atual",
            width=180,
            height=26,
            fg_color="#2b2b36",
            hover_color="#3a3a48",
            font=ctk.CTkFont(size=11),
            command=self._test_gemini_web_connection,
        )
        self.btn_test.pack(anchor="w", padx=10, pady=(0, 10))

        # Seção 3: Anthropic Claude Web (PRO / Team)
        lbl_sec_claude = ctk.CTkLabel(
            scroll_main,
            text="Anthropic Claude Web (PRO / Team)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        lbl_sec_claude.pack(anchor="w", padx=8, pady=(6, 4))

        claude_box = ctk.CTkFrame(scroll_main, fg_color="#1e1e28", corner_radius=8)
        claude_box.pack(fill="x", padx=6, pady=(0, 10))

        self.var_claude_enabled = ctk.BooleanVar(value=self.parent.settings.get("claude_web_enabled", False))
        self.chk_claude = ctk.CTkCheckBox(
            claude_box,
            text="Ativar Monitoramento do Claude Web (PRO / Team)",
            variable=self.var_claude_enabled,
            font=ctk.CTkFont(size=12, weight="bold"),
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
        )
        self.chk_claude.pack(anchor="w", padx=10, pady=(10, 8))

        claude_session_active = has_saved_claude_session()
        btn_claude_text = "🔄 Reconectar / Trocar de Conta Claude" if claude_session_active else "🌐 Fazer Login no Claude (Captura Automática)"
        status_claude_text = "● Sessão persistente ativa (Renovação automática contínua ativada ✓)" if claude_session_active else "Faça login uma vez; o gadget manterá a sessão conectada continuamente."
        status_claude_color = "#10b981" if claude_session_active else "#888899"

        # Botão de Login Direto com Captura Automática
        self.btn_claude_login = ctk.CTkButton(
            claude_box,
            text=btn_claude_text,
            height=32,
            fg_color="#d97757",
            hover_color="#b85d3f",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._start_claude_login_flow,
        )
        self.btn_claude_login.pack(fill="x", padx=10, pady=(0, 4))

        self.lbl_claude_login_status = ctk.CTkLabel(
            claude_box,
            text=status_claude_text,
            font=ctk.CTkFont(size=10),
            text_color=status_claude_color,
            justify="left",
            wraplength=310,
        )
        self.lbl_claude_login_status.pack(anchor="w", padx=10, pady=(0, 8))

        # Separador / Opção Manual
        lbl_claude_or = ctk.CTkLabel(
            claude_box,
            text="─── ou configurar cookies manualmente ───",
            font=ctk.CTkFont(size=10),
            text_color="#555566",
        )
        lbl_claude_or.pack(fill="x", padx=10, pady=(2, 6))

        lbl_claude_cookie = ctk.CTkLabel(
            claude_box,
            text="Cookie de Sessão (sessionKey):",
            font=ctk.CTkFont(size=11),
            text_color="#cccccc",
        )
        lbl_claude_cookie.pack(anchor="w", padx=10, pady=(2, 2))

        self.entry_claude_cookie = ctk.CTkEntry(
            claude_box,
            placeholder_text="sk-ant-sid01-... ou sessionKey capturada no login",
            height=28,
            font=ctk.CTkFont(size=11),
        )
        saved_claude_cookie = self.parent.settings.get("claude_web_cookie", "")
        if saved_claude_cookie:
            self.entry_claude_cookie.insert(0, saved_claude_cookie)
        self.entry_claude_cookie.pack(fill="x", padx=10, pady=(0, 6))

        # Botão Testar Conexão Claude
        self.lbl_claude_test_result = ctk.CTkLabel(claude_box, text="", font=ctk.CTkFont(size=10))
        self.lbl_claude_test_result.pack(anchor="w", padx=10, pady=(0, 4))

        self.btn_claude_test = ctk.CTkButton(
            claude_box,
            text="Testar Conexão Claude",
            width=180,
            height=26,
            fg_color="#2b2b36",
            hover_color="#3a3a48",
            font=ctk.CTkFont(size=11),
            command=self._test_claude_connection,
        )
        self.btn_claude_test.pack(anchor="w", padx=10, pady=(0, 10))

        # Seção 4: Aparência e Visualização
        lbl_sec3 = ctk.CTkLabel(
            scroll_main,
            text="Aparência e Visualização",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        lbl_sec3.pack(anchor="w", padx=8, pady=(6, 4))

        style_box = ctk.CTkFrame(scroll_main, fg_color="#1e1e28", corner_radius=8)
        style_box.pack(fill="x", padx=6, pady=(0, 10))

        # 1. Tamanho da Fonte
        lbl_font = ctk.CTkLabel(
            style_box,
            text="Tamanho da Fonte:",
            font=ctk.CTkFont(size=11),
            text_color="#cccccc",
        )
        lbl_font.pack(anchor="w", padx=10, pady=(8, 2))

        self.seg_font = ctk.CTkSegmentedButton(
            style_box,
            values=["Pequeno", "Médio", "Grande"],
            font=ctk.CTkFont(size=11),
        )
        self.seg_font.set(self.parent.settings.get("font_size", "Médio"))
        self.seg_font.pack(fill="x", padx=10, pady=(0, 8))

        # 2. Opacidade da Janela
        self.var_opacity = ctk.DoubleVar(value=self.initial_opacity)
        self.lbl_opacity_val = ctk.CTkLabel(
            style_box,
            text=f"Opacidade da Janela: {int(self.initial_opacity * 100)}%",
            font=ctk.CTkFont(size=11),
            text_color="#cccccc",
        )
        self.lbl_opacity_val.pack(anchor="w", padx=10, pady=(4, 2))

        self.slider_opacity = ctk.CTkSlider(
            style_box,
            from_=0.40,
            to=1.0,
            number_of_steps=12,
            variable=self.var_opacity,
            command=self._on_opacity_slider,
        )
        self.slider_opacity.pack(fill="x", padx=10, pady=(0, 8))

        # 3. Modo de Exibição das Cotas
        lbl_mode = ctk.CTkLabel(
            style_box,
            text="Modo de Exibição das Cotas:",
            font=ctk.CTkFont(size=11),
            text_color="#cccccc",
        )
        lbl_mode.pack(anchor="w", padx=10, pady=(4, 2))

        self.seg_mode = ctk.CTkSegmentedButton(
            style_box,
            values=["% Restante", "% Consumida"],
            font=ctk.CTkFont(size=11),
        )
        self.seg_mode.set(self.parent.settings.get("display_mode", "% Restante"))
        self.seg_mode.pack(fill="x", padx=10, pady=(0, 10))

        # Seção 4: Sistema e Inicialização
        lbl_sec4 = ctk.CTkLabel(
            scroll_main,
            text="Sistema e Inicialização",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        lbl_sec4.pack(anchor="w", padx=8, pady=(6, 4))

        sys_box = ctk.CTkFrame(scroll_main, fg_color="#1e1e28", corner_radius=8)
        sys_box.pack(fill="x", padx=6, pady=(0, 10))

        self.var_autostart = ctk.BooleanVar(value=is_autostart_enabled())
        self.switch_autostart = ctk.CTkSwitch(
            sys_box,
            text="Iniciar automaticamente com o Windows",
            variable=self.var_autostart,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_autostart_toggle,
        )
        self.switch_autostart.pack(anchor="w", padx=12, pady=10)

        # Botões de Ação Inferiores
        btn_box = ctk.CTkFrame(container, fg_color="transparent")
        btn_box.pack(fill="x", padx=8, pady=(4, 4))

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Cancelar",
            width=120,
            height=30,
            fg_color="transparent",
            border_width=1,
            border_color="#444444",
            hover_color="#2c2c34",
            command=self._on_cancel,
        )
        btn_cancel.pack(side="left")

        btn_save = ctk.CTkButton(
            btn_box,
            text="Salvar",
            width=120,
            height=30,
            command=self._save,
        )
        btn_save.pack(side="right")

    def _start_login_flow(self):
        """Dispara o processo auxiliar de login via WebView nativo para captura automática de cookies."""
        self.btn_login.configure(state="disabled", text="Abrindo navegador de login...")
        self.lbl_login_status.configure(
            text="Aguardando você fazer login na janela aberta...",
            text_color="#3b8ed0",
        )
        try:
            self.attributes("-topmost", False)
        except Exception:
            pass

        def login_worker():
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--login-webview"]
            else:
                py_exe = sys.executable.replace("python.exe", "pythonw.exe")
                if not os.path.exists(py_exe):
                    py_exe = sys.executable
                cmd = [py_exe, os.path.abspath(__file__), "--login-webview"]

            try:
                # Janela interativa DEVE ser visível (sem SW_HIDE)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                output, _ = proc.communicate()

                captured = False
                for line in output.splitlines():
                    if line.startswith("LOGIN_SUCCESS:"):
                        payload = json.loads(line[len("LOGIN_SUCCESS:"):])
                        cookie_hdr = payload.get("cookie_header", "")
                        if cookie_hdr:
                            captured = True
                            self.after(0, lambda ch=cookie_hdr: self._on_login_success(ch))
                            break

                if not captured:
                    self.after(0, lambda: self._on_login_ended("Login não concluído ou janela fechada."))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_login_ended(f"Erro ao iniciar login: {err}"))

        threading.Thread(target=login_worker, daemon=True).start()

    def _on_login_success(self, cookie_hdr: str):
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.btn_login.configure(state="normal", text="🔄 Reconectar / Trocar de Conta Google")
        self.lbl_login_status.configure(
            text="● Sessão persistente ativa (Renovação automática contínua ativada ✓)",
            text_color="#10b981",
        )
        self.var_web_enabled.set(True)
        self.entry_cookie.delete(0, "end")
        self.entry_cookie.insert(0, cookie_hdr)
        self.parent.settings["gemini_web_cookie"] = cookie_hdr
        self.parent.save_settings()
        self.parent.web_client.set_cookies(cookie_hdr)
        self._test_gemini_web_connection()

    def _on_login_ended(self, msg: str):
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        session_active = has_saved_session()
        btn_text = "🔄 Reconectar / Trocar de Conta Google" if session_active else "🌐 Fazer Login no Gemini (Captura Automática)"
        self.btn_login.configure(state="normal", text=btn_text)
        self.lbl_login_status.configure(text=f"⚠ {msg}", text_color="#f59e0b")

    def _test_gemini_web_connection(self):
        """Testa o cookie fornecido em segundo plano com auto-recuperação da sessão salva."""
        cookie_text = self.entry_cookie.get().strip()
        if not cookie_text:
            self.lbl_test_result.configure(text="⚠ Nenhum cookie configurado para testar.", text_color="#ef4444")
            return

        self.btn_test.configure(state="disabled", text="Testando...")
        self.lbl_test_result.configure(text="Conectando ao gemini.google.com...", text_color="#aaaaaa")

        def run_test():
            client = GeminiWebClient(cookie_text)
            quota = client.fetch_quota(force_refresh=True)

            # Se a consulta falhou e existe uma sessão gravada no WebView2, tenta renovação silenciosa
            if not quota and has_saved_session():
                self.after(0, lambda: self.lbl_test_result.configure(text="Renovando sessão salva em segundo plano...", text_color="#aaaaaa"))
                fresh = self.parent._execute_silent_gemini_refresh()
                if fresh:
                    client.set_cookies(fresh)
                    quota = client.fetch_quota(force_refresh=True)
                    if quota:
                        self.after(0, lambda: self.entry_cookie.delete(0, "end"))
                        self.after(0, lambda: self.entry_cookie.insert(0, fresh))
                        self.parent.settings["gemini_web_cookie"] = fresh
                        self.parent.save_settings()
                        self.parent.web_client.set_cookies(fresh)

            if quota:
                msg = f"✓ Conectado! (Uso Atual: {quota.get('current_used_pct')}%)"
                col = "#10b981"
            else:
                err = client.last_error or "Falha de autenticação"
                msg = f"✗ Erro: {err}"
                col = "#ef4444"

            self.after(0, lambda: self._show_test_result(msg, col))

        threading.Thread(target=run_test, daemon=True).start()

    def _show_test_result(self, msg: str, color: str):
        self.btn_test.configure(state="normal", text="Testar Conexão Atual")
        self.lbl_test_result.configure(text=msg, text_color=color)

    def _start_claude_login_flow(self):
        """Dispara o processo auxiliar de login via WebView nativo para captura automática de cookies do Claude."""
        self.btn_claude_login.configure(state="disabled", text="Abrindo navegador de login...")
        self.lbl_claude_login_status.configure(
            text="Aguardando você fazer login na janela aberta...",
            text_color="#d97757",
        )
        try:
            self.attributes("-topmost", False)
        except Exception:
            pass

        def login_worker():
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--login-claude-webview"]
            else:
                py_exe = sys.executable.replace("python.exe", "pythonw.exe")
                if not os.path.exists(py_exe):
                    py_exe = sys.executable
                cmd = [py_exe, os.path.abspath(__file__), "--login-claude-webview"]

            try:
                # Janela interativa DEVE ser visível (sem SW_HIDE)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                output, _ = proc.communicate()

                captured = False
                for line in output.splitlines():
                    if line.startswith("CLAUDE_LOGIN_SUCCESS:"):
                        payload = json.loads(line[len("CLAUDE_LOGIN_SUCCESS:"):])
                        cookie_hdr = payload.get("cookie_header", "")
                        if cookie_hdr:
                            captured = True
                            self.after(0, lambda ch=cookie_hdr: self._on_claude_login_success(ch))
                            break

                if not captured:
                    self.after(0, lambda: self._on_claude_login_ended("Login não concluído ou janela fechada."))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_claude_login_ended(f"Erro ao iniciar login: {err}"))

        threading.Thread(target=login_worker, daemon=True).start()

    def _on_claude_login_success(self, cookie_hdr: str):
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.btn_claude_login.configure(state="normal", text="🔄 Reconectar / Trocar de Conta Claude")
        self.lbl_claude_login_status.configure(
            text="● Sessão persistente ativa (Renovação automática contínua ativada ✓)",
            text_color="#10b981",
        )
        self.var_claude_enabled.set(True)
        self.entry_claude_cookie.delete(0, "end")
        self.entry_claude_cookie.insert(0, cookie_hdr)
        self.parent.settings["claude_web_cookie"] = cookie_hdr
        self.parent.save_settings()
        self.parent.claude_client.set_cookies(cookie_hdr)
        self._test_claude_connection()

    def _on_claude_login_ended(self, msg: str):
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        session_active = has_saved_claude_session()
        btn_text = "🔄 Reconectar / Trocar de Conta Claude" if session_active else "🌐 Fazer Login no Claude (Captura Automática)"
        self.btn_claude_login.configure(state="normal", text=btn_text)
        self.lbl_claude_login_status.configure(text=f"⚠ {msg}", text_color="#f59e0b")

    def _test_claude_connection(self):
        """Testa o cookie fornecido em segundo plano com auto-recuperação da sessão salva."""
        cookie_text = self.entry_claude_cookie.get().strip()
        if not cookie_text:
            self.lbl_claude_test_result.configure(text="⚠ Nenhum cookie configurado para testar.", text_color="#ef4444")
            return

        self.btn_claude_test.configure(state="disabled", text="Testando...")
        self.lbl_claude_test_result.configure(text="Conectando a claude.ai...", text_color="#aaaaaa")

        def run_test():
            client = ClaudeWebClient(cookie_text)
            quota = client.fetch_quota(force_refresh=True)

            # Se a consulta falhou e existe uma sessão gravada no WebView2, tenta renovação silenciosa
            if not quota and has_saved_claude_session():
                self.after(0, lambda: self.lbl_claude_test_result.configure(text="Renovando sessão salva em segundo plano...", text_color="#aaaaaa"))
                fresh = self.parent._execute_silent_claude_refresh()
                if fresh:
                    client.set_cookies(fresh)
                    quota = client.fetch_quota(force_refresh=True)
                    if quota:
                        self.after(0, lambda: self.entry_claude_cookie.delete(0, "end"))
                        self.after(0, lambda: self.entry_claude_cookie.insert(0, fresh))
                        self.parent.settings["claude_web_cookie"] = fresh
                        self.parent.save_settings()
                        self.parent.claude_client.set_cookies(fresh)

            if quota:
                plan = quota.get("plan", "PRO")
                used_5h = quota.get("five_hour_used_pct", 0.0)
                msg = f"✓ Conectado! (Plano {plan} • 5h: {used_5h}% usado)"
                col = "#10b981"
            else:
                err = client.last_error or "Falha de autenticação"
                msg = f"✗ Erro: {err}"
                col = "#ef4444"

            self.after(0, lambda: self._show_claude_test_result(msg, col))

        threading.Thread(target=run_test, daemon=True).start()

    def _show_claude_test_result(self, msg: str, color: str):
        self.btn_claude_test.configure(state="normal", text="Testar Conexão Claude")
        self.lbl_claude_test_result.configure(text=msg, text_color=color)

    def _on_opacity_slider(self, val: float):
        pct = int(round(val * 100))
        self.lbl_opacity_val.configure(text=f"Opacidade da Janela: {pct}%")
        self.parent.attributes("-alpha", max(0.3, min(1.0, val)))
        self.parent.setup_hide_from_taskbar()

    def _on_cancel(self):
        # Restaura a opacidade original se o usuário cancelar
        self.parent.attributes("-alpha", self.initial_opacity)
        self.parent.setup_hide_from_taskbar()
        self.destroy()

    def _on_autostart_toggle(self):
        set_autostart_enabled(self.var_autostart.get())

    def _save(self):
        new_visible = [grp for grp, var in self.check_vars.items() if var.get()]
        if not new_visible:
            new_visible = [list(self.check_vars.keys())[0]]

        self.parent.settings["visible_groups"] = new_visible
        self.parent.settings["gemini_web_enabled"] = self.var_web_enabled.get()
        self.parent.settings["gemini_web_cookie"] = self.entry_cookie.get().strip()
        self.parent.settings["claude_web_enabled"] = self.var_claude_enabled.get()
        self.parent.settings["claude_web_cookie"] = self.entry_claude_cookie.get().strip()

        # Novas configurações visuais
        chosen_opacity = round(self.var_opacity.get(), 2)
        self.parent.settings["opacity"] = chosen_opacity
        self.parent.attributes("-alpha", chosen_opacity)
        self.parent.setup_hide_from_taskbar()

        self.parent.settings["font_size"] = self.seg_font.get()
        self.parent.settings["display_mode"] = self.seg_mode.get()

        # Atualiza os clientes web no pai
        self.parent.web_client.set_cookies(self.parent.settings["gemini_web_cookie"])
        self.parent.claude_client.set_cookies(self.parent.settings["claude_web_cookie"])

        self.parent.save_settings()
        self.parent.full_rebuild_cards()
        self.parent.refresh_data()
        self.destroy()


class GeminiQuotaWidget(ctk.CTk):
    """Widget Desktop Flutuante com cantos arredondados, sem barra de tarefas, sem flicker e redimensionável."""

    def __init__(self):
        super().__init__()

        self.client = AntigravityQuotaClient()
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.known_groups: List[str] = list(DEFAULT_SETTINGS["visible_groups"])
        self.latest_quota_data: List[Dict[str, Any]] = []

        self.load_settings()

        # Cliente do Gemini Web com callback dinâmico de Set-Cookie
        self.web_client = GeminiWebClient(
            self.settings.get("gemini_web_cookie", ""),
            on_cookie_update=self._on_web_cookies_updated,
        )
        self._last_silent_refresh_attempt: float = 0.0

        # Cliente do Anthropic Claude Web com callback dinâmico de Set-Cookie
        self.claude_client = ClaudeWebClient(
            self.settings.get("claude_web_cookie", ""),
            on_cookie_update=self._on_claude_cookies_updated,
        )
        self._last_silent_claude_refresh_attempt: float = 0.0

        # Dicionários de referências a widgets existentes para atualização sem flicker
        self.rendered_cards: Dict[str, ctk.CTkFrame] = {}
        self.card_headers: Dict[str, ctk.CTkFrame] = {}
        self.card_badges: Dict[str, ctk.CTkLabel] = {}
        self.card_banners: Dict[str, ctk.CTkLabel] = {}
        self.bucket_widgets: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.gemini_web_card: Optional[ctk.CTkFrame] = None
        self.gemini_web_header: Optional[ctk.CTkFrame] = None
        self.gemini_web_badge: Optional[ctk.CTkLabel] = None
        self.gemini_web_banner: Optional[ctk.CTkLabel] = None
        self.gemini_web_widgets: Dict[str, Any] = {}
        self.claude_web_card: Optional[ctk.CTkFrame] = None
        self.claude_web_header: Optional[ctk.CTkFrame] = None
        self.claude_web_badge: Optional[ctk.CTkLabel] = None
        self.claude_web_banner: Optional[ctk.CTkLabel] = None
        self.claude_web_widgets: Dict[str, Any] = {}
        self.offline_widget: Optional[ctk.CTkFrame] = None

        # Coordenadas e Dimensões da Janela (suporte pleno a desktop multi-monitor)
        pos_x = self.settings.get("window_state", {}).get("x")
        pos_y = self.settings.get("window_state", {}).get("y")
        self.current_w = int(self.settings.get("window_state", {}).get("width", 280))
        self.current_h = int(self.settings.get("window_state", {}).get("height", 450))

        if sys.platform == "win32":
            vx = ctypes.windll.user32.GetSystemMetrics(76)
            vy = ctypes.windll.user32.GetSystemMetrics(77)
            vw = ctypes.windll.user32.GetSystemMetrics(78)
            vh = ctypes.windll.user32.GetSystemMetrics(79)
        else:
            vx, vy = 0, 0
            vw = self.winfo_screenwidth()
            vh = self.winfo_screenheight()

        if pos_x is None or pos_y is None:
            pos_x = max(20, vw - self.current_w - 40)
            pos_y = 60
        else:
            # Valida para manter a janela visível no desktop virtual
            pos_x = max(vx, min(vx + vw - 80, int(pos_x)))
            pos_y = max(vy, min(vy + vh - 80, int(pos_y)))

        self.settings["window_state"]["x"] = pos_x
        self.settings["window_state"]["y"] = pos_y
        self.settings["window_state"]["width"] = self.current_w
        self.settings["window_state"]["height"] = self.current_h

        # Janela frameless e topmost (sem ícone na barra de tarefas)
        self.title("Antigravity Quota Live")
        self.geometry(f"{self.current_w}x{self.current_h}+{pos_x}+{pos_y}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        # Cantos arredondados: cor transparente na raiz + DWM Windows 11
        self.setup_rounded_corners()

        # Aplica opacidade configurada (0.4 a 1.0)
        opacity = float(self.settings.get("opacity", 0.95))
        self.attributes("-alpha", max(0.3, min(1.0, opacity)))

        # Garante remoção definitiva do ícone da barra de tarefas no Windows
        self.setup_hide_from_taskbar()
        self.after(50, self.setup_hide_from_taskbar)
        self.after(250, self.setup_hide_from_taskbar)

        # Variáveis de arraste de posição
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        # Variáveis de redimensionamento
        self._res_mode = ""
        self._res_start_x = 0
        self._res_start_y = 0
        self._res_orig_w = self.current_w
        self._res_orig_h = self.current_h

        self.settings_window: Optional[SettingsWindow] = None
        self.tray_icon: Optional[pystray.Icon] = None

        self.build_ui()
        self.setup_drag_bindings()
        self.setup_resize_bindings()

        # Exibe imediatamente dados em cache / previstos para evitar tela em branco ao iniciar
        self._load_cached_quota_on_startup()

        # Consulta inicial
        self.refresh_data()

        # Agendamento do loop contínuo automático (a cada 30 segundos)
        self.schedule_next_refresh()

        # Bandeja do sistema
        self.start_system_tray()

    def get_font_sizes(self) -> Dict[str, int]:
        """Retorna tamanhos das fontes e componentes baseado na escala configurada."""
        mode = self.settings.get("font_size", "Médio")
        if mode == "Grande":
            return {
                "title": 15,
                "card_title": 14,
                "badge": 10,
                "banner": 11,
                "label": 13,
                "value": 13,
                "reset": 11,
                "footer": 11,
                "bar_h": 8,
            }
        elif mode == "Pequeno":
            return {
                "title": 12,
                "card_title": 11,
                "badge": 9,
                "banner": 10,
                "label": 11,
                "value": 11,
                "reset": 10,
                "footer": 10,
                "bar_h": 6,
            }
        else:  # "Médio" (Padrão confortavelmente aumentado)
            return {
                "title": 13,
                "card_title": 13,
                "badge": 9,
                "banner": 10,
                "label": 12,
                "value": 12,
                "reset": 10,
                "footer": 10,
                "bar_h": 7,
            }

    def apply_font_sizes(self):
        """Aplica os tamanhos de fonte aos componentes fixos da interface."""
        fonts = self.get_font_sizes()
        if hasattr(self, "lbl_app_title"):
            self.lbl_app_title.configure(font=ctk.CTkFont(size=fonts["title"], weight="bold"))
        if hasattr(self, "lbl_footer"):
            self.lbl_footer.configure(font=ctk.CTkFont(size=fonts["footer"]))

    def setup_rounded_corners(self):
        """Aplica cantos arredondados reais via transparência de cor e API DWM do Windows."""
        if sys.platform == "win32":
            try:
                self.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
                self.configure(fg_color=TRANSPARENT_KEY)

                self.update_idletasks()
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_ROUND = 2
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
                    ctypes.sizeof(ctypes.c_int),
                )
            except Exception:
                pass

    def setup_hide_from_taskbar(self):
        """Garante que a janela NÃO apareça na barra de tarefas do Windows (WS_EX_TOOLWINDOW)."""
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            hwnd = self.winfo_id()
            parent = ctypes.windll.user32.GetParent(hwnd)
            target = parent if parent else hwnd

            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020

            style = ctypes.windll.user32.GetWindowLongW(target, GWL_EXSTYLE)
            new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            if new_style != style:
                ctypes.windll.user32.SetWindowLongW(target, GWL_EXSTYLE, new_style)
                ctypes.windll.user32.SetWindowPos(
                    target, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
                )
        except Exception:
            pass

    def build_ui(self):
        """Constrói a interface visual com cantos arredondados e botões perfeitamente alinhados."""
        self.card = ctk.CTkFrame(
            self,
            corner_radius=16,
            border_width=1,
            border_color="#3a3a44",
            fg_color="#18181f",
        )
        self.card.pack(fill="both", expand=True, padx=2, pady=2)

        # Barra Superior
        self.top_bar = ctk.CTkFrame(self.card, fg_color="transparent")
        self.top_bar.pack(fill="x", padx=12, pady=(10, 4))

        # Indicador de status (bolinha verde/cinza)
        self.status_dot = ctk.CTkLabel(
            self.top_bar,
            text="●",
            font=ctk.CTkFont(size=14),
            text_color="#10b981",
            width=16,
        )
        self.status_dot.pack(side="left", padx=(0, 4))

        fonts = self.get_font_sizes()
        self.lbl_app_title = ctk.CTkLabel(
            self.top_bar,
            text="Antigravity Quota",
            font=ctk.CTkFont(size=fonts["title"], weight="bold"),
            text_color="#ffffff",
        )
        self.lbl_app_title.pack(side="left")

        # Container dos 3 botões de ação com proporções idênticas
        actions_box = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        actions_box.pack(side="right")

        BTN_SIZE = 26
        BTN_RADIUS = 13

        # Botão Fechar / Ocultar para Tray (✕)
        self.btn_hide = ctk.CTkButton(
            actions_box,
            text="✕",
            width=BTN_SIZE,
            height=BTN_SIZE,
            corner_radius=BTN_RADIUS,
            fg_color="transparent",
            hover_color="#c0392b",
            text_color="#a0a0a0",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.hide_to_tray,
        )
        self.btn_hide.pack(side="right", padx=(3, 0))

        # Botão Configurações (⚙)
        self.btn_settings = ctk.CTkButton(
            actions_box,
            text="⚙",
            width=BTN_SIZE,
            height=BTN_SIZE,
            corner_radius=BTN_RADIUS,
            fg_color="transparent",
            hover_color="#2c2c36",
            text_color="#a0a0a0",
            font=ctk.CTkFont(size=13),
            command=self.open_settings,
        )
        self.btn_settings.pack(side="right", padx=(3, 0))

        # Botão Atualizar (↻)
        self.btn_refresh = ctk.CTkButton(
            actions_box,
            text="↻",
            width=BTN_SIZE,
            height=BTN_SIZE,
            corner_radius=BTN_RADIUS,
            fg_color="transparent",
            hover_color="#2c2c36",
            text_color="#a0a0a0",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.refresh_data,
        )
        self.btn_refresh.pack(side="right")

        # Container rolável para os cards de modelos
        self.content_scroll = ctk.CTkScrollableFrame(
            self.card,
            fg_color="transparent",
            corner_radius=8,
        )
        self.content_scroll.pack(fill="both", expand=True, padx=8, pady=(2, 2))

        # Barra inferior com status de atualização e alça de redimensionamento
        self.bottom_bar = ctk.CTkFrame(self.card, fg_color="transparent", height=24)
        self.bottom_bar.pack(side="bottom", fill="x", padx=10, pady=(2, 6))

        self.lbl_footer = ctk.CTkLabel(
            self.bottom_bar,
            text="Atualizando...",
            font=ctk.CTkFont(size=fonts["footer"]),
            text_color="#777788",
        )
        self.lbl_footer.pack(side="left", padx=(4, 0))

        # Alça visual de canto (ícone ◿ no canto inferior direito)
        self.grip_corner = ctk.CTkLabel(
            self.card,
            text="◿",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#555566",
            cursor="size_nw_se",
            width=16,
            height=16,
        )
        self.grip_corner.place(relx=1.0, rely=1.0, x=-5, y=-5, anchor="se")

        # Bordas ativas para puxar com o mouse
        self.grip_right = ctk.CTkFrame(self.card, width=6, fg_color="transparent", cursor="size_we")
        self.grip_right.place(relx=1.0, rely=0.08, relheight=0.86, x=-2, anchor="ne")

        self.grip_bottom = ctk.CTkFrame(self.card, height=6, fg_color="transparent", cursor="size_ns")
        self.grip_bottom.place(relx=0.0, rely=1.0, relwidth=0.88, y=-2, anchor="sw")

    def setup_drag_bindings(self):
        """Habilita mover a janela clicando no fundo ou barra de títulos."""
        draggable_widgets = [self.card, self.top_bar, self.lbl_app_title, self.status_dot, self.lbl_footer, self.bottom_bar]
        for w in draggable_widgets:
            w.bind("<Button-1>", self.on_drag_start)
            w.bind("<B1-Motion>", self.on_drag_motion)
            w.bind("<ButtonRelease-1>", self.on_drag_end)

    def on_drag_start(self, event):
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def on_drag_motion(self, event):
        new_x = event.x_root - self._drag_offset_x
        new_y = event.y_root - self._drag_offset_y
        self.settings["window_state"]["x"] = new_x
        self.settings["window_state"]["y"] = new_y
        self.geometry(f"+{new_x}+{new_y}")

    def on_drag_end(self, event):
        self.settings["window_state"]["x"] = self.winfo_x()
        self.settings["window_state"]["y"] = self.winfo_y()
        self.save_settings()

    def setup_resize_bindings(self):
        """Habilita redimensionar puxando o canto inferior direito ou as bordas."""
        self.grip_corner.bind("<Button-1>", lambda e: self.on_resize_start(e, "wh"))
        self.grip_corner.bind("<B1-Motion>", self.on_resize_motion)
        self.grip_corner.bind("<ButtonRelease-1>", self.on_resize_end)

        self.grip_right.bind("<Button-1>", lambda e: self.on_resize_start(e, "w"))
        self.grip_right.bind("<B1-Motion>", self.on_resize_motion)
        self.grip_right.bind("<ButtonRelease-1>", self.on_resize_end)

        self.grip_bottom.bind("<Button-1>", lambda e: self.on_resize_start(e, "h"))
        self.grip_bottom.bind("<B1-Motion>", self.on_resize_motion)
        self.grip_bottom.bind("<ButtonRelease-1>", self.on_resize_end)

    def on_resize_start(self, event, mode: str):
        self._res_mode = mode
        self._res_start_x = event.x_root
        self._res_start_y = event.y_root
        self._res_orig_w = self.current_w
        self._res_orig_h = self.current_h

    def on_resize_motion(self, event):
        scale = self._get_window_scaling() if hasattr(self, "_get_window_scaling") else 1.0
        dw = int((event.x_root - self._res_start_x) / scale)
        dh = int((event.y_root - self._res_start_y) / scale)

        new_w = self._res_orig_w
        new_h = self._res_orig_h

        if "w" in self._res_mode:
            new_w = max(MIN_WIDTH, min(MAX_WIDTH, self._res_orig_w + dw))
        if "h" in self._res_mode:
            new_h = max(MIN_HEIGHT, min(MAX_HEIGHT, self._res_orig_h + dh))

        self.current_w = new_w
        self.current_h = new_h
        self.geometry(f"{new_w}x{new_h}")
        self.check_scrollbar_visibility()

    def on_resize_end(self, event):
        self.settings["window_state"]["x"] = self.winfo_x()
        self.settings["window_state"]["y"] = self.winfo_y()
        self.settings["window_state"]["width"] = self.current_w
        self.settings["window_state"]["height"] = self.current_h
        self.save_settings()
        self.check_scrollbar_visibility()

    def check_scrollbar_visibility(self):
        """Oculta a barra de rolagem lateral quando todo o conteúdo cabe na tela."""
        try:
            self.update_idletasks()
            canvas = self.content_scroll._parent_canvas
            bbox = canvas.bbox("all")
            if bbox:
                content_height = bbox[3] - bbox[1]
                canvas_height = canvas.winfo_height()
                if content_height <= canvas_height + 4:
                    self.content_scroll._scrollbar.grid_remove()
                else:
                    self.content_scroll._scrollbar.grid()
        except Exception:
            pass

    def load_settings(self):
        """Carrega preferências salvas ou migra esquema com merge dos novos campos."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        merged = dict(DEFAULT_SETTINGS)
                        merged.update(data)
                        if "window_state" in data and isinstance(data["window_state"], dict):
                            ws = dict(DEFAULT_SETTINGS["window_state"])
                            ws.update(data["window_state"])
                            merged["window_state"] = ws
                        self.settings = merged
                        return
            except Exception as e:
                print(f"Erro ao ler settings: {e}")
        self.save_settings()

    def save_settings(self):
        """Salva configurações no arquivo JSON."""
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Erro ao salvar settings: {e}")

    def _on_web_cookies_updated(self, new_cookie: str):
        """Atualiza e salva automaticamente os cookies renovados via Set-Cookie."""
        if new_cookie and new_cookie != self.settings.get("gemini_web_cookie", ""):
            self.settings["gemini_web_cookie"] = new_cookie
            self.save_settings()

    def _on_claude_cookies_updated(self, new_cookie: str):
        """Atualiza e salva automaticamente os cookies do Claude renovados via Set-Cookie."""
        if new_cookie and new_cookie != self.settings.get("claude_web_cookie", ""):
            self.settings["claude_web_cookie"] = new_cookie
            self.save_settings()

    def _execute_silent_gemini_refresh(self, timeout_sec: float = 20.0) -> Optional[str]:
        """Dispara subprocesso silencioso para renovar cookies em background via WebView2 (sem popup)."""
        si = None
        flags = 0
        if sys.platform == "win32":
            flags |= 0x08000000  # CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--silent-cookie-refresh"]
        else:
            cmd = [sys.executable, os.path.abspath(__file__), "--silent-cookie-refresh"]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=si,
                creationflags=flags,
            )
            output, _ = proc.communicate(timeout=timeout_sec)
            for line in output.splitlines():
                if line.startswith("REFRESH_SUCCESS:"):
                    data = json.loads(line[len("REFRESH_SUCCESS:"):])
                    cookie_hdr = data.get("cookie_header", "")
                    if cookie_hdr:
                        return cookie_hdr
        except Exception as e:
            print(f"Erro na renovação silenciosa de cookies: {e}")
        return None

    def _execute_silent_claude_refresh(self, timeout_sec: float = 20.0) -> Optional[str]:
        """Dispara subprocesso silencioso para renovar cookies do Claude em background via WebView2 (sem popup)."""
        si = None
        flags = 0
        if sys.platform == "win32":
            flags |= 0x08000000  # CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--silent-claude-cookie-refresh"]
        else:
            cmd = [sys.executable, os.path.abspath(__file__), "--silent-claude-cookie-refresh"]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=si,
                creationflags=flags,
            )
            output, _ = proc.communicate(timeout=timeout_sec)
            for line in output.splitlines():
                if line.startswith("CLAUDE_REFRESH_SUCCESS:"):
                    data = json.loads(line[len("CLAUDE_REFRESH_SUCCESS:"):])
                    cookie_hdr = data.get("cookie_header", "")
                    if cookie_hdr:
                        return cookie_hdr
        except Exception as e:
            print(f"Erro na renovação silenciosa de cookies do Claude: {e}")
        return None

    def refresh_data(self):
        """Busca cotas reais do Antigravity, Gemini Web e Claude Web em background com auto-recuperação de sessão."""
        def fetch_worker():
            ag_groups = self.client.fetch_quota()
            gw_quota = None
            if self.settings.get("gemini_web_enabled", False):
                gw_quota = self.web_client.fetch_quota()
                # Se falhou e existe uma sessão salva no WebView2 ou cookie anterior
                if gw_quota is None and (has_saved_session() or self.settings.get("gemini_web_cookie")):
                    now = time.time()
                    if now - self._last_silent_refresh_attempt > 60:
                        self._last_silent_refresh_attempt = now
                        new_cookie = self._execute_silent_gemini_refresh()
                        if new_cookie:
                            self.settings["gemini_web_cookie"] = new_cookie
                            self.save_settings()
                            self.web_client.set_cookies(new_cookie)
                            gw_quota = self.web_client.fetch_quota()

            cw_quota = None
            if self.settings.get("claude_web_enabled", False):
                cw_quota = self.claude_client.fetch_quota()
                if cw_quota is None and (has_saved_claude_session() or self.settings.get("claude_web_cookie")):
                    now = time.time()
                    if now - self._last_silent_claude_refresh_attempt > 60:
                        self._last_silent_claude_refresh_attempt = now
                        new_cookie = self._execute_silent_claude_refresh()
                        if new_cookie:
                            self.settings["claude_web_cookie"] = new_cookie
                            self.save_settings()
                            self.claude_client.set_cookies(new_cookie)
                            cw_quota = self.claude_client.fetch_quota()

            self.after(0, lambda: self._apply_fetched_data(ag_groups, gw_quota, cw_quota))

        threading.Thread(target=fetch_worker, daemon=True).start()

    def _load_cached_quota_on_startup(self):
        """Carrega e exibe instantaneamente os dados previstos/em cache salvos na última sessão."""
        last_known = self.settings.get("last_known_quota")
        if last_known and last_known.get("groups"):
            projected_groups, last_read_str = calculate_projected_ag_data(last_known)
            self.status_dot.configure(text_color="#f59e0b")
            msg = f"Estimativa • Antigravity offline (leitura {last_read_str})" if last_read_str else "Estimativa • Antigravity offline"
            self.lbl_footer.configure(text=msg)
            self.update_quota_display(projected_groups, is_projected=True, last_read_str=last_read_str)

        last_known_gw = self.settings.get("last_known_gemini_web")
        if self.settings.get("gemini_web_enabled", False) and last_known_gw and last_known_gw.get("data"):
            projected_gw, lr_str = calculate_projected_gw_data(last_known_gw)
            self.update_gemini_web_card(projected_gw, is_projected=True, last_read_str=lr_str)

        last_known_cw = self.settings.get("last_known_claude_web")
        if self.settings.get("claude_web_enabled", False) and last_known_cw and last_known_cw.get("data"):
            projected_cw, lr_str = calculate_projected_claude_data(last_known_cw)
            self.update_claude_web_card(projected_cw, is_projected=True, last_read_str=lr_str)

    def _apply_fetched_data(
        self,
        ag_groups: Optional[List[Dict[str, Any]]],
        gw_quota: Optional[Dict[str, Any]],
        cw_quota: Optional[Dict[str, Any]] = None,
    ):
        """Aplica os dados coletados nos componentes em tela SEM flicker."""
        now_str = datetime.now().strftime("%H:%M:%S")

        # 1. Antigravity Quota
        if ag_groups:
            self.latest_quota_data = ag_groups
            discovered_names = [g.get("displayName") for g in ag_groups if g.get("displayName")]
            self.known_groups = list(dict.fromkeys(self.known_groups + discovered_names))
            self.status_dot.configure(text_color="#10b981")

            if self.offline_widget is not None:
                self.offline_widget.destroy()
                self.offline_widget = None

            # Salva a última leitura bem-sucedida para persistência e estimativa futura
            self.settings["last_known_quota"] = {
                "timestamp": datetime.now().isoformat(),
                "groups": ag_groups,
            }
            self.save_settings()

            self.update_quota_display(ag_groups, is_projected=False)
            self.lbl_footer.configure(text=f"Atualizado às {now_str}")
        else:
            # Antigravity está offline: carrega última leitura e calcula dados previstos considerando resets
            last_known = self.settings.get("last_known_quota")
            if last_known and last_known.get("groups"):
                projected_groups, last_read_str = calculate_projected_ag_data(last_known)
                self.status_dot.configure(text_color="#f59e0b")
                msg = f"Estimativa • Antigravity offline (leitura {last_read_str})" if last_read_str else "Estimativa • Antigravity offline"
                self.lbl_footer.configure(text=msg)

                if self.offline_widget is not None:
                    self.offline_widget.destroy()
                    self.offline_widget = None

                self.update_quota_display(projected_groups, is_projected=True, last_read_str=last_read_str)
            else:
                self.status_dot.configure(text_color="#ef4444")
                self.lbl_footer.configure(text="Aguardando conexão com Antigravity...")
                if (
                    not self.latest_quota_data
                    and not self.settings.get("gemini_web_enabled", False)
                    and not self.settings.get("claude_web_enabled", False)
                ):
                    self.render_offline_state()

        # 2. Gemini Web Quota
        if self.settings.get("gemini_web_enabled", False):
            if gw_quota:
                # Salva última leitura válida do Gemini Web
                self.settings["last_known_gemini_web"] = {
                    "timestamp": datetime.now().isoformat(),
                    "data": gw_quota,
                }
                self.save_settings()
                self.update_gemini_web_card(gw_quota, is_projected=False)
            else:
                last_known_gw = self.settings.get("last_known_gemini_web")
                if last_known_gw and last_known_gw.get("data"):
                    projected_gw, lr_str = calculate_projected_gw_data(last_known_gw)
                    self.update_gemini_web_card(projected_gw, is_projected=True, last_read_str=lr_str)
                else:
                    self.update_gemini_web_card(None, is_projected=False)
        elif self.gemini_web_card is not None:
            self.gemini_web_card.destroy()
            self.gemini_web_card = None
            self.gemini_web_badge = None
            self.gemini_web_banner = None
            self.gemini_web_widgets.clear()

        # 3. Claude Web Quota
        if self.settings.get("claude_web_enabled", False):
            if cw_quota:
                # Salva última leitura válida do Claude Web
                self.settings["last_known_claude_web"] = {
                    "timestamp": datetime.now().isoformat(),
                    "data": cw_quota,
                }
                self.save_settings()
                self.update_claude_web_card(cw_quota, is_projected=False)
            else:
                last_known_cw = self.settings.get("last_known_claude_web")
                if last_known_cw and last_known_cw.get("data"):
                    projected_cw, lr_str = calculate_projected_claude_data(last_known_cw)
                    self.update_claude_web_card(projected_cw, is_projected=True, last_read_str=lr_str)
                else:
                    self.update_claude_web_card(None, is_projected=False)
        elif self.claude_web_card is not None:
            self.claude_web_card.destroy()
            self.claude_web_card = None
            self.claude_web_badge = None
            self.claude_web_banner = None
            self.claude_web_widgets.clear()

        self.check_scrollbar_visibility()

    def full_rebuild_cards(self):
        """Limpa referências para reconstrução completa ao alterar seleção nas configurações."""
        self.apply_font_sizes()
        for widget in self.content_scroll.winfo_children():
            widget.destroy()
        self.rendered_cards.clear()
        self.card_headers.clear()
        self.card_badges.clear()
        self.card_banners.clear()
        self.bucket_widgets.clear()
        self.gemini_web_card = None
        self.gemini_web_header = None
        self.gemini_web_badge = None
        self.gemini_web_banner = None
        self.gemini_web_widgets.clear()
        self.claude_web_card = None
        self.claude_web_header = None
        self.claude_web_badge = None
        self.claude_web_banner = None
        self.claude_web_widgets.clear()
        self.offline_widget = None

    def update_quota_display(
        self,
        groups: List[Dict[str, Any]],
        is_projected: bool = False,
        last_read_str: str = "",
    ):
        """Atualiza valores dos widgets de modelos do Antigravity em tempo real sem recriação (Zero Flicker)."""
        visible_set = set(self.settings.get("visible_groups", []))
        display_mode = self.settings.get("display_mode", "% Restante")
        fonts = self.get_font_sizes()

        active_rendered_groups = set(self.rendered_cards.keys())
        wanted_groups = {g.get("displayName") for g in groups if g.get("displayName") in visible_set}
        if active_rendered_groups != wanted_groups:
            self.full_rebuild_cards()

        for group in groups:
            group_name = group.get("displayName", "Modelo")
            if group_name not in visible_set:
                continue

            buckets = group.get("buckets", [])
            if not buckets:
                continue

            # Cria o Card do Grupo se ainda não existir
            if group_name not in self.rendered_cards:
                card = ctk.CTkFrame(
                    self.content_scroll,
                    fg_color="#20202a",
                    border_width=1,
                    border_color="#30303c",
                    corner_radius=10,
                )
                card.pack(fill="x", padx=4, pady=5)
                self.rendered_cards[group_name] = card

                header = ctk.CTkFrame(card, fg_color="transparent")
                header.pack(fill="x", padx=10, pady=(8, 2))
                self.card_headers[group_name] = header

                lbl_name = ctk.CTkLabel(
                    header,
                    text=group_name,
                    font=ctk.CTkFont(size=fonts["card_title"], weight="bold"),
                    text_color="#ffffff",
                )
                lbl_name.pack(side="left")

                badge_est = ctk.CTkLabel(
                    header,
                    text="⚠ ESTIMADO",
                    font=ctk.CTkFont(size=fonts["badge"], weight="bold"),
                    fg_color="#d97706",
                    text_color="#18181f",
                    corner_radius=4,
                    padx=5,
                    pady=1,
                )
                self.card_badges[group_name] = badge_est

                lbl_banner = ctk.CTkLabel(
                    card,
                    text="",
                    font=ctk.CTkFont(size=fonts["banner"]),
                    text_color="#f59e0b",
                    anchor="w",
                )
                self.card_banners[group_name] = lbl_banner

            card = self.rendered_cards[group_name]
            header = self.card_headers[group_name]
            badge_est = self.card_badges[group_name]
            lbl_banner = self.card_banners[group_name]

            # Estilo do Card: Tom Amarelado/Âmbar se Estimado
            if is_projected:
                card.configure(fg_color="#272216", border_color="#d97706", border_width=1.5)
                badge_est.pack(side="left", padx=(6, 0))
                msg = f"Dados previstos • Antigravity offline (leitura {last_read_str})" if last_read_str else "Dados previstos • Antigravity offline"
                lbl_banner.configure(text=msg)
                lbl_banner.pack(fill="x", padx=10, pady=(0, 4), after=header)
            else:
                card.configure(fg_color="#20202a", border_color="#30303c", border_width=1)
                badge_est.pack_forget()
                lbl_banner.pack_forget()

            # Atualiza ou cria cada bucket dentro do card
            for b in buckets:
                bucket_id = b.get("bucketId", b.get("window", "default"))
                key = (group_name, bucket_id)

                fraction = float(b.get("remainingFraction", 1.0))
                if display_mode == "% Consumida":
                    fraction_used = max(0.0, min(1.0, 1.0 - fraction))
                    pct_val = round(fraction_used * 100, 1)
                    val_text = f"{pct_val}% consumido"
                    bar_val = fraction_used
                    color = get_color_for_used(fraction_used)
                else:
                    pct_val = round(fraction * 100, 1)
                    val_text = f"{pct_val}% restante"
                    bar_val = max(0.0, min(1.0, fraction))
                    color = get_color_for_remaining(fraction)

                window_name = "Limite 5 Horas" if b.get("window") == "5h" else "Limite Semanal"
                is_restored = bool(b.get("is_reset_restored", False))
                reset_text = format_reset_info(b.get("resetTime"), is_restored=is_restored)

                if key not in self.bucket_widgets:
                    bucket_frame = ctk.CTkFrame(card, fg_color="transparent")
                    bucket_frame.pack(fill="x", padx=10, pady=(2, 6))

                    row1 = ctk.CTkFrame(bucket_frame, fg_color="transparent")
                    row1.pack(fill="x")

                    lbl_win = ctk.CTkLabel(
                        row1,
                        text=window_name,
                        font=ctk.CTkFont(size=fonts["label"]),
                        text_color="#aaaaaa",
                    )
                    lbl_win.pack(side="left")

                    lbl_pct = ctk.CTkLabel(
                        row1,
                        text=val_text,
                        font=ctk.CTkFont(size=fonts["value"], weight="bold"),
                        text_color=color,
                    )
                    lbl_pct.pack(side="right")

                    pbar = ctk.CTkProgressBar(
                        bucket_frame,
                        width=210,
                        height=fonts["bar_h"],
                        corner_radius=3,
                        progress_color=color,
                    )
                    pbar.set(bar_val)
                    pbar.pack(fill="x", pady=(2, 2))

                    lbl_reset = ctk.CTkLabel(
                        bucket_frame,
                        text=reset_text,
                        font=ctk.CTkFont(size=fonts["reset"]),
                        text_color="#888899",
                    )
                    lbl_reset.pack(anchor="w")

                    self.bucket_widgets[key] = {
                        "lbl_pct": lbl_pct,
                        "pbar": pbar,
                        "lbl_reset": lbl_reset,
                    }
                else:
                    w = self.bucket_widgets[key]
                    w["lbl_pct"].configure(text=val_text, text_color=color)
                    w["pbar"].set(bar_val)
                    w["pbar"].configure(progress_color=color)
                    w["lbl_reset"].configure(text=reset_text)

    def update_gemini_web_card(
        self,
        data: Optional[Dict[str, Any]],
        is_projected: bool = False,
        last_read_str: str = "",
    ):
        """Renderiza ou atualiza o card do Gemini Web (PRO) com dados reais ou previstos."""
        display_mode = self.settings.get("display_mode", "% Restante")
        fonts = self.get_font_sizes()

        if self.gemini_web_card is None:
            card = ctk.CTkFrame(
                self.content_scroll,
                fg_color="#20202a",
                border_width=1,
                border_color="#30303c",
                corner_radius=10,
            )
            card.pack(fill="x", padx=4, pady=5)
            self.gemini_web_card = card

            # Cabeçalho com tag PRO e badge ESTIMADO
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=10, pady=(8, 2))
            self.gemini_web_header = header

            lbl_title = ctk.CTkLabel(
                header,
                text="Gemini Web",
                font=ctk.CTkFont(size=fonts["card_title"], weight="bold"),
                text_color="#ffffff",
            )
            lbl_title.pack(side="left")

            tag_pro = ctk.CTkLabel(
                header,
                text="PRO",
                font=ctk.CTkFont(size=fonts["badge"], weight="bold"),
                fg_color="#3b8ed0",
                corner_radius=4,
                text_color="#ffffff",
                padx=5,
                pady=1,
            )
            tag_pro.pack(side="left", padx=(6, 0))

            badge_est = ctk.CTkLabel(
                header,
                text="⚠ ESTIMADO",
                font=ctk.CTkFont(size=fonts["badge"], weight="bold"),
                fg_color="#d97706",
                text_color="#18181f",
                corner_radius=4,
                padx=5,
                pady=1,
            )
            self.gemini_web_badge = badge_est

            lbl_banner = ctk.CTkLabel(
                card,
                text="",
                font=ctk.CTkFont(size=fonts["banner"]),
                text_color="#f59e0b",
                anchor="w",
            )
            self.gemini_web_banner = lbl_banner

            # Bloco 1: Uso Atual
            b1 = ctk.CTkFrame(card, fg_color="transparent")
            b1.pack(fill="x", padx=10, pady=(2, 5))

            row1 = ctk.CTkFrame(b1, fg_color="transparent")
            row1.pack(fill="x")
            lbl_b1_title = ctk.CTkLabel(row1, text="Uso Atual", font=ctk.CTkFont(size=fonts["label"]), text_color="#aaaaaa")
            lbl_b1_title.pack(side="left")
            lbl_b1_val = ctk.CTkLabel(row1, text="--%", font=ctk.CTkFont(size=fonts["value"], weight="bold"), text_color="#10b981")
            lbl_b1_val.pack(side="right")

            pbar1 = ctk.CTkProgressBar(b1, width=210, height=fonts["bar_h"], corner_radius=3, progress_color="#10b981")
            pbar1.set(0)
            pbar1.pack(fill="x", pady=(2, 2))

            lbl_b1_reset = ctk.CTkLabel(b1, text="Aguardando dados...", font=ctk.CTkFont(size=fonts["reset"]), text_color="#888899")
            lbl_b1_reset.pack(anchor="w")

            # Bloco 2: Limite Semanal
            b2 = ctk.CTkFrame(card, fg_color="transparent")
            b2.pack(fill="x", padx=10, pady=(2, 6))

            row2 = ctk.CTkFrame(b2, fg_color="transparent")
            row2.pack(fill="x")
            lbl_b2_title = ctk.CTkLabel(row2, text="Limite Semanal", font=ctk.CTkFont(size=fonts["label"]), text_color="#aaaaaa")
            lbl_b2_title.pack(side="left")
            lbl_b2_val = ctk.CTkLabel(row2, text="--%", font=ctk.CTkFont(size=fonts["value"], weight="bold"), text_color="#10b981")
            lbl_b2_val.pack(side="right")

            pbar2 = ctk.CTkProgressBar(b2, width=210, height=fonts["bar_h"], corner_radius=3, progress_color="#10b981")
            pbar2.set(0)
            pbar2.pack(fill="x", pady=(2, 2))

            lbl_b2_reset = ctk.CTkLabel(b2, text="Aguardando dados...", font=ctk.CTkFont(size=fonts["reset"]), text_color="#888899")
            lbl_b2_reset.pack(anchor="w")

            self.gemini_web_widgets = {
                "b1_val": lbl_b1_val,
                "b1_bar": pbar1,
                "b1_reset": lbl_b1_reset,
                "b2_val": lbl_b2_val,
                "b2_bar": pbar2,
                "b2_reset": lbl_b2_reset,
            }

        # Estilo do Card: Tom Amarelado se Estimado
        if is_projected:
            self.gemini_web_card.configure(fg_color="#272216", border_color="#d97706", border_width=1.5)
            if self.gemini_web_badge:
                self.gemini_web_badge.pack(side="left", padx=(6, 0))
            if self.gemini_web_banner and self.gemini_web_header:
                msg = f"Dados previstos • Gemini Web offline (leitura {last_read_str})" if last_read_str else "Dados previstos • Gemini Web offline"
                self.gemini_web_banner.configure(text=msg)
                self.gemini_web_banner.pack(fill="x", padx=10, pady=(0, 4), after=self.gemini_web_header)
        else:
            self.gemini_web_card.configure(fg_color="#20202a", border_color="#30303c", border_width=1)
            if self.gemini_web_badge:
                self.gemini_web_badge.pack_forget()
            if self.gemini_web_banner:
                self.gemini_web_banner.pack_forget()

        # Atualiza dados se disponíveis
        w = self.gemini_web_widgets
        if data:
            c_used = data.get("current_used_pct", 0.0)
            c_rem = data.get("current_remaining_pct", round(max(0.0, 100.0 - c_used), 1))
            if display_mode == "% Consumida":
                c_frac = max(0.0, min(1.0, c_used / 100.0))
                c_col = get_color_for_used(c_frac)
                w["b1_val"].configure(text=f"{c_used}% consumido", text_color=c_col)
                w["b1_bar"].set(c_frac)
                w["b1_bar"].configure(progress_color=c_col)
            else:
                c_frac = max(0.0, min(1.0, c_rem / 100.0))
                c_col = get_color_for_remaining(c_frac)
                w["b1_val"].configure(text=f"{c_rem}% restante", text_color=c_col)
                w["b1_bar"].set(c_frac)
                w["b1_bar"].configure(progress_color=c_col)

            c_reset = data.get("current_reset_text", "Limite redefinido em breve")
            w["b1_reset"].configure(text=c_reset)

            w_used = data.get("weekly_used_pct", 0.0)
            w_rem = data.get("weekly_remaining_pct", round(max(0.0, 100.0 - w_used), 1))
            if display_mode == "% Consumida":
                w_frac = max(0.0, min(1.0, w_used / 100.0))
                w_col = get_color_for_used(w_frac)
                w["b2_val"].configure(text=f"{w_used}% consumido", text_color=w_col)
                w["b2_bar"].set(w_frac)
                w["b2_bar"].configure(progress_color=w_col)
            else:
                w_frac = max(0.0, min(1.0, w_rem / 100.0))
                w_col = get_color_for_remaining(w_frac)
                w["b2_val"].configure(text=f"{w_rem}% restante", text_color=w_col)
                w["b2_bar"].set(w_frac)
                w["b2_bar"].configure(progress_color=w_col)

            w_reset = data.get("weekly_reset_text", "Limite semanal redefinido em breve")
            w["b2_reset"].configure(text=w_reset)
        else:
            if has_saved_session():
                err = "Renovando sessão automaticamente..."
                tip = "Aguardando renovação de tokens..."
            else:
                err = self.web_client.last_error or "Aguardando login no Gemini (abra ⚙)"
                tip = "Faça login no Gemini em ⚙"
            w["b1_val"].configure(text="Offline", text_color="#ef4444")
            w["b1_reset"].configure(text=err)
            w["b2_val"].configure(text="Offline", text_color="#ef4444")
            w["b2_reset"].configure(text=tip)

    def update_claude_web_card(
        self,
        data: Optional[Dict[str, Any]],
        is_projected: bool = False,
        last_read_str: str = "",
    ):
        """Renderiza ou atualiza o card do Anthropic Claude Web com dados reais ou previstos."""
        display_mode = self.settings.get("display_mode", "% Restante")
        fonts = self.get_font_sizes()

        if self.claude_web_card is None:
            card = ctk.CTkFrame(
                self.content_scroll,
                fg_color="#20202a",
                border_width=1,
                border_color="#30303c",
                corner_radius=10,
            )
            card.pack(fill="x", padx=4, pady=5)
            self.claude_web_card = card

            # Cabeçalho com tag de Plano (PRO/TEAM) e badge ESTIMADO
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=10, pady=(8, 2))
            self.claude_web_header = header

            lbl_title = ctk.CTkLabel(
                header,
                text="Claude Web",
                font=ctk.CTkFont(size=fonts["card_title"], weight="bold"),
                text_color="#ffffff",
            )
            lbl_title.pack(side="left")

            plan_str = "PRO"
            if data and data.get("plan"):
                plan_str = str(data.get("plan")).upper()

            tag_plan = ctk.CTkLabel(
                header,
                text=plan_str,
                font=ctk.CTkFont(size=fonts["badge"], weight="bold"),
                fg_color="#d97757",
                corner_radius=4,
                text_color="#ffffff",
                padx=5,
                pady=1,
            )
            tag_plan.pack(side="left", padx=(6, 0))

            badge_est = ctk.CTkLabel(
                header,
                text="⚠ ESTIMADO",
                font=ctk.CTkFont(size=fonts["badge"], weight="bold"),
                fg_color="#d97706",
                text_color="#18181f",
                corner_radius=4,
                padx=5,
                pady=1,
            )
            self.claude_web_badge = badge_est

            lbl_banner = ctk.CTkLabel(
                card,
                text="",
                font=ctk.CTkFont(size=fonts["banner"]),
                text_color="#f59e0b",
                anchor="w",
            )
            self.claude_web_banner = lbl_banner

            # Bloco 1: Janela de 5 Horas (Sessão)
            b1 = ctk.CTkFrame(card, fg_color="transparent")
            b1.pack(fill="x", padx=10, pady=(2, 5))

            row1 = ctk.CTkFrame(b1, fg_color="transparent")
            row1.pack(fill="x")
            lbl_b1_title = ctk.CTkLabel(row1, text="Sessão (5 Horas)", font=ctk.CTkFont(size=fonts["label"]), text_color="#aaaaaa")
            lbl_b1_title.pack(side="left")
            lbl_b1_val = ctk.CTkLabel(row1, text="--%", font=ctk.CTkFont(size=fonts["value"], weight="bold"), text_color="#10b981")
            lbl_b1_val.pack(side="right")

            pbar1 = ctk.CTkProgressBar(b1, width=210, height=fonts["bar_h"], corner_radius=3, progress_color="#10b981")
            pbar1.set(0)
            pbar1.pack(fill="x", pady=(2, 2))

            lbl_b1_reset = ctk.CTkLabel(b1, text="Aguardando dados...", font=ctk.CTkFont(size=fonts["reset"]), text_color="#888899")
            lbl_b1_reset.pack(anchor="w")

            # Bloco 2: Limite Semanal (7 Dias)
            b2 = ctk.CTkFrame(card, fg_color="transparent")
            b2.pack(fill="x", padx=10, pady=(2, 6))

            row2 = ctk.CTkFrame(b2, fg_color="transparent")
            row2.pack(fill="x")
            lbl_b2_title = ctk.CTkLabel(row2, text="Limite Semanal", font=ctk.CTkFont(size=fonts["label"]), text_color="#aaaaaa")
            lbl_b2_title.pack(side="left")
            lbl_b2_val = ctk.CTkLabel(row2, text="--%", font=ctk.CTkFont(size=fonts["value"], weight="bold"), text_color="#10b981")
            lbl_b2_val.pack(side="right")

            pbar2 = ctk.CTkProgressBar(b2, width=210, height=fonts["bar_h"], corner_radius=3, progress_color="#10b981")
            pbar2.set(0)
            pbar2.pack(fill="x", pady=(2, 2))

            lbl_b2_reset = ctk.CTkLabel(b2, text="Aguardando dados...", font=ctk.CTkFont(size=fonts["reset"]), text_color="#888899")
            lbl_b2_reset.pack(anchor="w")

            self.claude_web_widgets = {
                "tag_plan": tag_plan,
                "b1_val": lbl_b1_val,
                "b1_bar": pbar1,
                "b1_reset": lbl_b1_reset,
                "b2_val": lbl_b2_val,
                "b2_bar": pbar2,
                "b2_reset": lbl_b2_reset,
            }

        # Atualiza tag de plano se disponível
        if data and data.get("plan") and "tag_plan" in self.claude_web_widgets:
            self.claude_web_widgets["tag_plan"].configure(text=str(data.get("plan")).upper())

        # Estilo do Card: Tom Amarelado se Estimado
        if is_projected:
            self.claude_web_card.configure(fg_color="#272216", border_color="#d97706", border_width=1.5)
            if self.claude_web_badge:
                self.claude_web_badge.pack(side="left", padx=(6, 0))
            if self.claude_web_banner and self.claude_web_header:
                msg = f"Dados previstos • Claude Web offline (leitura {last_read_str})" if last_read_str else "Dados previstos • Claude Web offline"
                self.claude_web_banner.configure(text=msg)
                self.claude_web_banner.pack(fill="x", padx=10, pady=(0, 4), after=self.claude_web_header)
        else:
            self.claude_web_card.configure(fg_color="#20202a", border_color="#30303c", border_width=1)
            if self.claude_web_badge:
                self.claude_web_badge.pack_forget()
            if self.claude_web_banner:
                self.claude_web_banner.pack_forget()

        # Atualiza dados se disponíveis
        w = self.claude_web_widgets
        if data:
            c_used = data.get("five_hour_used_pct", 0.0)
            c_rem = data.get("five_hour_remaining_pct", round(max(0.0, 100.0 - c_used), 1))
            if display_mode == "% Consumida":
                c_frac = max(0.0, min(1.0, c_used / 100.0))
                c_col = get_color_for_used(c_frac)
                w["b1_val"].configure(text=f"{c_used}% consumido", text_color=c_col)
                w["b1_bar"].set(c_frac)
                w["b1_bar"].configure(progress_color=c_col)
            else:
                c_frac = max(0.0, min(1.0, c_rem / 100.0))
                c_col = get_color_for_remaining(c_frac)
                w["b1_val"].configure(text=f"{c_rem}% restante", text_color=c_col)
                w["b1_bar"].set(c_frac)
                w["b1_bar"].configure(progress_color=c_col)

            c_reset = data.get("five_hour_reset_text", "⏱ Limite de sessão restaurado")
            w["b1_reset"].configure(text=c_reset)

            w_used = data.get("weekly_used_pct", 0.0)
            w_rem = data.get("weekly_remaining_pct", round(max(0.0, 100.0 - w_used), 1))
            if display_mode == "% Consumida":
                w_frac = max(0.0, min(1.0, w_used / 100.0))
                w_col = get_color_for_used(w_frac)
                w["b2_val"].configure(text=f"{w_used}% consumido", text_color=w_col)
                w["b2_bar"].set(w_frac)
                w["b2_bar"].configure(progress_color=w_col)
            else:
                w_frac = max(0.0, min(1.0, w_rem / 100.0))
                w_col = get_color_for_remaining(w_frac)
                w["b2_val"].configure(text=f"{w_rem}% restante", text_color=w_col)
                w["b2_bar"].set(w_frac)
                w["b2_bar"].configure(progress_color=w_col)

            w_reset = data.get("weekly_reset_text", "⏱ Limite semanal restaurado")
            w["b2_reset"].configure(text=w_reset)
        else:
            if has_saved_claude_session():
                err = "Renovando sessão do Claude..."
                tip = "Aguardando renovação de sessão..."
            else:
                err = self.claude_client.last_error or "Aguardando login no Claude (abra ⚙)"
                tip = "Faça login no Claude em ⚙"
            w["b1_val"].configure(text="Offline", text_color="#ef4444")
            w["b1_reset"].configure(text=err)
            w["b2_val"].configure(text="Offline", text_color="#ef4444")
            w["b2_reset"].configure(text=tip)

    def render_offline_state(self):
        """Exibe mensagem amigável quando o serviço local não responde."""
        self.full_rebuild_cards()

        box = ctk.CTkFrame(self.content_scroll, fg_color="#202028", corner_radius=8)
        box.pack(fill="x", padx=4, pady=12)
        self.offline_widget = box

        lbl = ctk.CTkLabel(
            box,
            text="Antigravity Fechado\nou Inicializando...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cccccc",
        )
        lbl.pack(pady=(12, 6))

        btn = ctk.CTkButton(
            box,
            text="Tentar Reconectar",
            width=140,
            height=28,
            font=ctk.CTkFont(size=11),
            command=self.refresh_data,
        )
        btn.pack(pady=(0, 12))

    def schedule_next_refresh(self):
        """Agenda atualização contínua em background (a cada 30 segundos)."""
        interval = self.settings.get("refresh_interval_sec", 30) * 1000
        self.after(interval, self._on_scheduled_refresh)

    def _on_scheduled_refresh(self):
        self.refresh_data()
        self.schedule_next_refresh()

    def open_settings(self):
        """Abre a modal de configurações de modelos e Gemini Web."""
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self, self.known_groups)

    def show_window(self):
        self.deiconify()
        self.setup_hide_from_taskbar()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()

    def hide_to_tray(self):
        self.withdraw()

    def start_system_tray(self):
        """Inicia ícone da bandeja em thread desacoplada."""
        self.tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        self.tray_thread.start()

    def _run_tray(self):
        icon_img = generate_tray_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar Widget", lambda: self.after(0, self.show_window), default=True),
            pystray.MenuItem("Configurações", lambda: self.after(0, self.open_settings)),
            pystray.MenuItem("Atualizar Agora", lambda: self.after(0, self.refresh_data)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", lambda: self.after(0, self.exit_app)),
        )
        self.tray_icon = pystray.Icon("antigravity_quota_gadget", icon_img, "Antigravity Quota Live", menu=menu)
        self.tray_icon.run()

    def exit_app(self):
        """Encerra a aplicação de forma limpa garantindo persistência da posição."""
        try:
            self.settings["window_state"]["x"] = self.winfo_x()
            self.settings["window_state"]["y"] = self.winfo_y()
            self.settings["window_state"]["width"] = self.current_w
            self.settings["window_state"]["height"] = self.current_h
            self.save_settings()
        except Exception:
            pass
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)


if __name__ == "__main__":
    app = GeminiQuotaWidget()
    app.mainloop()

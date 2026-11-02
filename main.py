"""Gemini Quota Gadget - Monitor Desktop em Tempo Real de Cotas do Antigravity.

Widget flutuante para Windows (frameless, cantos arredondados, topmost, drag-and-drop, redimensionável, system tray)
que se conecta diretamente ao serviço local do Antigravity para exibir o consumo
real e contagem regressiva + data/hora de reset dos modelos de IA, com personalização
de quais modelos exibir e atualização suave sem flicker.
"""

import ctypes
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

# Diretório base para persistência (suporte a script .py e executável .exe)
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(BASE_DIR, "quota_data.json")

# Configurações padrão
DEFAULT_SETTINGS: Dict[str, Any] = {
    "window_state": {
        "x": None,
        "y": None,
        "width": 275,
        "height": 435,
    },
    "visible_groups": [
        "Gemini Models",
        "Gemini 4 Argon",
        "Claude and GPT models",
    ],
    "refresh_interval_sec": 30,
}

MIN_WIDTH = 230
MIN_HEIGHT = 200
MAX_WIDTH = 800
MAX_HEIGHT = 1200

# Cor transparente para cantos arredondados suaves
TRANSPARENT_KEY = "#010101"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def format_reset_info(reset_time_iso: Optional[str]) -> str:
    """Calcula a contagem regressiva e a data/hora local de redefinição."""
    if not reset_time_iso:
        return ""
    try:
        iso_clean = reset_time_iso.replace("Z", "+00:00")
        target_utc = datetime.fromisoformat(iso_clean)
        local_dt = target_utc.astimezone()  # Fuso horário local do Windows
        now_dt = datetime.now(timezone.utc)
        diff = target_utc - now_dt
        total_seconds = int(diff.total_seconds())

        if total_seconds <= 0:
            countdown = "<1m"
        else:
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
        return f"⏱ Reseta em {countdown} • {date_str}"
    except Exception:
        return ""


def get_color_for_fraction(fraction: float) -> str:
    """Retorna código de cor baseado no percentual restante (verde, amarelo ou vermelho)."""
    if fraction <= 0.20:
        return "#ef4444"  # Vermelho Alerta (<= 20%)
    elif fraction <= 0.50:
        return "#f59e0b"  # Amarelo/Laranja Atenção (<= 50%)
    else:
        return "#10b981"  # Verde Saudável (> 50%)


def generate_tray_icon_image() -> Image.Image:
    """Gera um ícone moderno de bandeja em memória (RGBA)."""
    image = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill="#1e1e28")
    draw.ellipse([14, 14, 50, 50], outline="#10b981", width=5)
    draw.ellipse([24, 24, 40, 40], fill="#3b8ed0")
    return image


class AntigravityQuotaClient:
    """Cliente para descoberta de processo local e consulta de cotas via Connect-RPC."""

    def __init__(self):
        self.cached_pid: Optional[int] = None
        self.cached_port: Optional[int] = None
        self.cached_csrf: Optional[str] = None

    def fetch_quota(self) -> Optional[List[Dict[str, Any]]]:
        """Tenta consultar utilizando dados cacheados; se falhar, redescobre o serviço."""
        if self.cached_port and self.cached_csrf:
            data = self._query_port(self.cached_port, self.cached_csrf)
            if data is not None:
                return data

        # Redescoberta do processo
        if self._discover_service():
            return self._query_port(self.cached_port, self.cached_csrf)
        return None

    def _discover_service(self) -> bool:
        """Localiza o language_server.exe, extrai a flag --csrf_token e descobre a porta de escuta."""
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | "
                "Select-Object ProcessId, CommandLine | ConvertTo-Json"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                text=True,
                errors="ignore",
            ).strip()

            if not out:
                return False

            proc_info = json.loads(out)
            if isinstance(proc_info, list):
                proc_info = proc_info[0]

            pid = proc_info.get("ProcessId")
            cmdline = proc_info.get("CommandLine", "")

            csrf_match = re.search(r"--csrf_token\s+([a-f0-9\-]+)", cmdline)
            if not csrf_match or not pid:
                return False

            csrf_token = csrf_match.group(1)

            # Busca portas TCP em escuta
            ports_cmd = (
                f"Get-NetTCPConnection -OwningProcess {pid} -State Listen "
                "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort"
            )
            ports_out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ports_cmd],
                text=True,
                errors="ignore",
            ).strip()

            ports = [int(p) for p in ports_out.split() if p.isdigit()]

            for port in ports:
                data = self._query_port(port, csrf_token)
                if data is not None:
                    self.cached_pid = pid
                    self.cached_port = port
                    self.cached_csrf = csrf_token
                    return True

            return False
        except Exception as e:
            print(f"Aviso de descoberta do Antigravity: {e}")
            return False

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
    """Janela modal para seleção dos modelos de linguagem que devem aparecer no gadget."""

    def __init__(self, parent: "GeminiQuotaWidget", available_groups: List[str]):
        super().__init__(parent)
        self.parent = parent
        self.available_groups = available_groups

        self.title("Modelos Visíveis")
        self.geometry("310x380")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(parent)

        px = parent.winfo_x() - 20
        py = parent.winfo_y() - 30
        self.geometry(f"+{max(10, px)}+{max(10, py)}")

        self.check_vars: Dict[str, ctk.BooleanVar] = {}

        self._build_ui()
        self.grab_set()
        self.focus_force()

    def _build_ui(self):
        container = ctk.CTkFrame(self, corner_radius=12, fg_color="#18181f")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        lbl_title = ctk.CTkLabel(
            container,
            text="Exibição de Modelos",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ffffff",
        )
        lbl_title.pack(pady=(12, 4))

        lbl_desc = ctk.CTkLabel(
            container,
            text="Escolha quais modelos deseja ver no gadget:",
            font=ctk.CTkFont(size=11),
            text_color="#aaaaaa",
        )
        lbl_desc.pack(pady=(0, 10))

        # Lista com checkboxes
        scroll = ctk.CTkScrollableFrame(container, height=180, fg_color="#1e1e28", corner_radius=8)
        scroll.pack(fill="x", padx=12, pady=(0, 12))

        current_visible = set(self.parent.settings.get("visible_groups", []))

        # Adiciona grupos conhecidos e disponíveis
        all_groups = list(dict.fromkeys(self.available_groups + list(current_visible)))
        if not all_groups:
            all_groups = DEFAULT_SETTINGS["visible_groups"]

        for grp in all_groups:
            is_active = grp in current_visible
            var = ctk.BooleanVar(value=is_active)
            self.check_vars[grp] = var

            chk = ctk.CTkCheckBox(
                scroll,
                text=grp,
                variable=var,
                font=ctk.CTkFont(size=12, weight="bold" if "Gemini" in grp else "normal"),
                checkbox_width=18,
                checkbox_height=18,
                corner_radius=4,
            )
            chk.pack(anchor="w", padx=8, pady=6)

        # Botões Salvar / Cancelar
        btn_box = ctk.CTkFrame(container, fg_color="transparent")
        btn_box.pack(fill="x", padx=12, pady=(4, 10))

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Cancelar",
            width=120,
            height=30,
            fg_color="transparent",
            border_width=1,
            border_color="#444444",
            hover_color="#2c2c34",
            command=self.destroy,
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

    def _save(self):
        new_visible = [grp for grp, var in self.check_vars.items() if var.get()]
        if not new_visible:
            new_visible = [list(self.check_vars.keys())[0]]

        self.parent.settings["visible_groups"] = new_visible
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

        # Dicionário de referências a widgets existentes para evitar reconstrução e eliminar o flicker
        self.rendered_cards: Dict[str, ctk.CTkFrame] = {}
        self.bucket_widgets: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.offline_widget: Optional[ctk.CTkFrame] = None

        self.load_settings()

        # Coordenadas e Dimensões da Janela
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        pos_x = self.settings.get("window_state", {}).get("x")
        pos_y = self.settings.get("window_state", {}).get("y")
        self.current_w = int(self.settings.get("window_state", {}).get("width", 275))
        self.current_h = int(self.settings.get("window_state", {}).get("height", 435))

        if pos_x is None or pos_y is None:
            pos_x = max(20, sw - self.current_w - 40)
            pos_y = 60
        else:
            pos_x = max(0, min(sw - self.current_w, int(pos_x)))
            pos_y = max(0, min(sh - 200, int(pos_y)))

        self.settings["window_state"]["x"] = pos_x
        self.settings["window_state"]["y"] = pos_y
        self.settings["window_state"]["width"] = self.current_w
        self.settings["window_state"]["height"] = self.current_h

        # Configuração da Janela: frameless e topmost (sem ícone na barra de tarefas)
        self.title("Antigravity Quota Live")
        self.geometry(f"{self.current_w}x{self.current_h}+{pos_x}+{pos_y}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        # Cantos arredondados: cor transparente na janela raiz + DWM Windows 11
        self.setup_rounded_corners()

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

        # Consulta inicial
        self.refresh_data()

        # Agendamento do loop contínuo automático (a cada 30 segundos)
        self.schedule_next_refresh()

        # Bandeja do sistema (único local de presença do app no sistema)
        self.start_system_tray()

    def setup_rounded_corners(self):
        """Aplica cantos arredondados reais via transparência de cor e API DWM do Windows."""
        if sys.platform == "win32":
            try:
                # Fundo raiz transparente elimina as quinas quadradas
                self.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
                self.configure(fg_color=TRANSPARENT_KEY)

                # Cantos arredondados DWM do Windows 11
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

    def build_ui(self):
        """Constrói a interface visual com cantos arredondados e botões proporcionais."""
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

        self.lbl_app_title = ctk.CTkLabel(
            self.top_bar,
            text="Antigravity Quota",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        self.lbl_app_title.pack(side="left")

        # Container dos 3 botões da direita (para manter alinhamento e proporções estritas)
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

        # Botão Atualizar (↻) - agora uniforme com os demais botões
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
            font=ctk.CTkFont(size=10),
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
        """Carrega preferências salvas ou migra esquema."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "visible_groups" in data:
                        self.settings = data
                        return
                    elif "window_state" in data:
                        self.settings["window_state"] = data.get("window_state", {})
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

    def refresh_data(self):
        """Busca cotas reais e atualiza os componentes em tela SEM recriar (Zero Flicker)."""
        groups = self.client.fetch_quota()

        if groups:
            self.latest_quota_data = groups
            discovered_names = [g.get("displayName") for g in groups if g.get("displayName")]
            self.known_groups = list(dict.fromkeys(self.known_groups + discovered_names))

            self.status_dot.configure(text_color="#10b981")  # Verde online
            if self.offline_widget is not None:
                self.offline_widget.destroy()
                self.offline_widget = None

            self.update_quota_display(groups)

            now_str = datetime.now().strftime("%H:%M:%S")
            self.lbl_footer.configure(text=f"Atualizado às {now_str}")
        else:
            self.status_dot.configure(text_color="#ef4444")  # Vermelho offline
            self.lbl_footer.configure(text="Aguardando conexão com Antigravity...")
            if not self.latest_quota_data:
                self.render_offline_state()

        self.check_scrollbar_visibility()

    def full_rebuild_cards(self):
        """Limpa referências para reconstrução completa quando a lista de modelos visíveis for alterada."""
        for widget in self.content_scroll.winfo_children():
            widget.destroy()
        self.rendered_cards.clear()
        self.bucket_widgets.clear()
        self.offline_widget = None

    def update_quota_display(self, groups: List[Dict[str, Any]]):
        """Atualiza valores dos widgets existentes em tempo real sem recriação (Zero Piscada)."""
        visible_set = set(self.settings.get("visible_groups", []))

        # Se as chaves renderizadas forem diferentes do conjunto visível, reconstrói
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
                header.pack(fill="x", padx=10, pady=(8, 4))

                lbl_name = ctk.CTkLabel(
                    header,
                    text=group_name,
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#ffffff",
                )
                lbl_name.pack(side="left")

            card = self.rendered_cards[group_name]

            # Atualiza ou cria cada bucket dentro do card
            for b in buckets:
                bucket_id = b.get("bucketId", b.get("window", "default"))
                key = (group_name, bucket_id)

                fraction = float(b.get("remainingFraction", 1.0))
                pct = round(fraction * 100, 1)
                color = get_color_for_fraction(fraction)
                window_name = "Limite 5 Horas" if b.get("window") == "5h" else "Limite Semanal"
                reset_text = format_reset_info(b.get("resetTime"))

                if key not in self.bucket_widgets:
                    # Cria os widgets do bucket uma única vez
                    bucket_frame = ctk.CTkFrame(card, fg_color="transparent")
                    bucket_frame.pack(fill="x", padx=10, pady=(2, 6))

                    row1 = ctk.CTkFrame(bucket_frame, fg_color="transparent")
                    row1.pack(fill="x")

                    lbl_win = ctk.CTkLabel(
                        row1,
                        text=window_name,
                        font=ctk.CTkFont(size=11),
                        text_color="#aaaaaa",
                    )
                    lbl_win.pack(side="left")

                    lbl_pct = ctk.CTkLabel(
                        row1,
                        text=f"{pct}% restante",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        text_color=color,
                    )
                    lbl_pct.pack(side="right")

                    pbar = ctk.CTkProgressBar(
                        bucket_frame,
                        width=210,
                        height=6,
                        corner_radius=3,
                        progress_color=color,
                    )
                    pbar.set(max(0.0, min(1.0, fraction)))
                    pbar.pack(fill="x", pady=(2, 2))

                    lbl_reset = ctk.CTkLabel(
                        bucket_frame,
                        text=reset_text,
                        font=ctk.CTkFont(size=10),
                        text_color="#888899",
                    )
                    lbl_reset.pack(anchor="w")

                    self.bucket_widgets[key] = {
                        "lbl_pct": lbl_pct,
                        "pbar": pbar,
                        "lbl_reset": lbl_reset,
                    }
                else:
                    # Atualização suave em memória (Zero Flicker)
                    w = self.bucket_widgets[key]
                    w["lbl_pct"].configure(text=f"{pct}% restante", text_color=color)
                    w["pbar"].set(max(0.0, min(1.0, fraction)))
                    w["pbar"].configure(progress_color=color)
                    w["lbl_reset"].configure(text=reset_text)

        self.check_scrollbar_visibility()

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
        """Abre a modal de configurações de modelos."""
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self, self.known_groups)

    def show_window(self):
        self.deiconify()
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
        """Encerra a aplicação de forma limpa."""
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

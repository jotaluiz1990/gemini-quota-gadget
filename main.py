"""Gemini Quota Gadget - Multi-Profile Desktop AI Quota Monitor.

Micro-aplicativo desktop frameless para Windows desenvolvido com CustomTkinter,
com suporte a múltiplos perfis de IA, reset diário automatizado, atalhos globais
em segundo plano e integração com a bandeja do sistema (System Tray).
"""

import ctypes
import datetime
import json
import os
import sys
import threading
from typing import Any, Dict, Optional

import customtkinter as ctk
import keyboard
from PIL import Image, ImageDraw
import pystray

# Determinação do diretório base para persistência (suporte a script e executável PyInstaller)
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(BASE_DIR, "quota_data.json")

# Dimensões da janela principal
WIDTH = 220
HEIGHT = 275

# Perfis padrão inicializados se o arquivo não existir
DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "Gemini Pro": {
        "current": 50,
        "max": 50,
        "last_reset": datetime.date.today().isoformat(),
    },
    "Gemini Flash": {
        "current": 100,
        "max": 100,
        "last_reset": datetime.date.today().isoformat(),
    },
    "Argon": {
        "current": 30,
        "max": 30,
        "last_reset": datetime.date.today().isoformat(),
    },
}

DEFAULT_WINDOW_STATE: Dict[str, Any] = {
    "x": None,
    "y": None,
    "theme": "dark",
    "shortcut": "ctrl+shift+p",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def generate_tray_icon_image() -> Image.Image:
    """Gera dinamicamente uma imagem em memória para o ícone da bandeja do sistema (System Tray)."""
    image = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Fundo arredondado
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill="#1f538d")
    # Núcleo brilhante estilizado
    draw.ellipse([18, 18, 46, 46], fill="#3b8ed0")
    draw.ellipse([26, 26, 38, 38], fill="#ffffff")
    return image


class SettingsWindow(ctk.CTkToplevel):
    """Janela modal para edição de configurações globais e limites de cota por perfil."""

    def __init__(self, parent: "GeminiQuotaWidget"):
        super().__init__(parent)
        self.parent = parent

        self.title("Configurações")
        self.geometry("320x420")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(parent)

        # Centraliza sobre o widget pai
        px = parent.winfo_x() - 50
        py = parent.winfo_y() - 70
        self.geometry(f"+{max(10, px)}+{max(10, py)}")

        self.quota_entries: Dict[str, ctk.CTkEntry] = {}

        self._build_ui()
        self.grab_set()
        self.focus_force()

    def _build_ui(self):
        container = ctk.CTkFrame(self, corner_radius=10, fg_color="#1e1e24")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Título
        lbl_title = ctk.CTkLabel(
            container,
            text="Configurações",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#ffffff",
        )
        lbl_title.pack(pady=(12, 10))

        # Seção do Atalho Global
        lbl_shortcut = ctk.CTkLabel(
            container,
            text="Atalho Global de Dedução:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cccccc",
        )
        lbl_shortcut.pack(anchor="w", padx=16, pady=(4, 2))

        self.entry_shortcut = ctk.CTkEntry(
            container,
            width=260,
            height=30,
            placeholder_text="ex: ctrl+shift+p",
        )
        current_shortcut = self.parent.window_state.get("shortcut", "ctrl+shift+p")
        self.entry_shortcut.insert(0, current_shortcut)
        self.entry_shortcut.pack(padx=16, pady=(0, 12))

        # Seção de Cotas Máximas por Modelo
        lbl_quotas = ctk.CTkLabel(
            container,
            text="Cota Máxima por Modelo:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cccccc",
        )
        lbl_quotas.pack(anchor="w", padx=16, pady=(0, 6))

        scroll_frame = ctk.CTkScrollableFrame(container, width=260, height=130, fg_color="#18181c")
        scroll_frame.pack(padx=16, pady=(0, 10), fill="x")

        for profile_name, pdata in self.parent.profiles.items():
            row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=4)

            p_lbl = ctk.CTkLabel(row, text=profile_name, font=ctk.CTkFont(size=12), text_color="#e0e0e0")
            p_lbl.pack(side="left")

            entry = ctk.CTkEntry(row, width=70, height=26, justify="center")
            entry.insert(0, str(pdata.get("max", 50)))
            entry.pack(side="right")
            self.quota_entries[profile_name] = entry

        # Mensagem de erro / feedback
        self.lbl_feedback = ctk.CTkLabel(
            container,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#e74c3c",
        )
        self.lbl_feedback.pack(pady=(0, 6))

        # Botões de Ação
        btn_box = ctk.CTkFrame(container, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=(0, 12))

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Cancelar",
            width=120,
            height=32,
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
            height=32,
            command=self._save_settings,
        )
        btn_save.pack(side="right")

    def _save_settings(self):
        new_shortcut = self.entry_shortcut.get().strip().lower()
        if not new_shortcut:
            self.lbl_feedback.configure(text="O atalho não pode estar vazio.")
            return

        # Validação numérica das cotas
        new_max_values = {}
        for pname, entry in self.quota_entries.items():
            val_str = entry.get().strip()
            if not val_str.isdigit() or int(val_str) <= 0:
                self.lbl_feedback.configure(text=f"Valor inválido para {pname}.")
                return
            new_max_values[pname] = int(val_str)

        # Atualiza limites no pai
        for pname, new_max in new_max_values.items():
            self.parent.profiles[pname]["max"] = new_max
            # Ajusta cota atual se ultrapassar o novo máximo
            if self.parent.profiles[pname]["current"] > new_max:
                self.parent.profiles[pname]["current"] = new_max

        # Atualiza atalho e reinicializa listener
        self.parent.window_state["shortcut"] = new_shortcut
        self.parent.setup_hotkey(new_shortcut)

        # Salva dados persistentes e atualiza visual
        self.parent.save_data()
        self.parent.update_display()
        self.destroy()


class GeminiQuotaWidget(ctk.CTk):
    """Widget de desktop flutuante principal para monitoramento e gestão de cota de IA."""

    def __init__(self):
        super().__init__()

        # Estado e Persistência
        self.window_state: Dict[str, Any] = dict(DEFAULT_WINDOW_STATE)
        self.profiles: Dict[str, Dict[str, Any]] = dict(DEFAULT_PROFILES)
        self.active_profile: str = "Gemini Pro"
        self.load_data()

        # Coordenadas da Janela
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        pos_x = self.window_state.get("x")
        pos_y = self.window_state.get("y")

        if pos_x is None or pos_y is None:
            pos_x = (sw - WIDTH) // 2
            pos_y = (sh - HEIGHT) // 2
        else:
            pos_x = max(0, min(sw - WIDTH, int(pos_x)))
            pos_y = max(0, min(sh - HEIGHT, int(pos_y)))

        self.window_state["x"] = pos_x
        self.window_state["y"] = pos_y

        # Configuração da Janela
        self.title("Gemini Quota")
        self.geometry(f"{WIDTH}x{HEIGHT}+{pos_x}+{pos_y}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        # Variáveis de arraste e atalhos
        self._offset_x = 0
        self._offset_y = 0
        self._hotkey_handler = None

        # Controle de instâncias
        self.settings_window: Optional[SettingsWindow] = None
        self.tray_icon: Optional[pystray.Icon] = None

        # Construção da Interface
        self.build_ui()
        self.setup_drag_bindings()
        self.setup_windows_taskbar()

        # Configura atalho global
        shortcut = self.window_state.get("shortcut", "ctrl+shift+p")
        self.setup_hotkey(shortcut)

        # Inicializa o motor de reset temporizado contínuo (a cada 60s)
        self.check_daily_reset()

        # Inicia bandeja do sistema em thread separada
        self.start_system_tray()

    def build_ui(self):
        """Constrói a interface visual completa do widget."""
        self.card = ctk.CTkFrame(
            self,
            corner_radius=12,
            border_width=1,
            border_color="#3a3a3c",
            fg_color="#1e1e24",
        )
        self.card.pack(fill="both", expand=True, padx=2, pady=2)

        # Barra Superior: Título + Botão Configurações + Botão Ocultar
        top_bar = ctk.CTkFrame(self.card, fg_color="transparent")
        top_bar.pack(fill="x", padx=10, pady=(8, 2))

        self.title_label = ctk.CTkLabel(
            top_bar,
            text="Gemini Quota",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e0e0e0",
        )
        self.title_label.pack(side="left")

        # Botão Fechar / Ocultar para Bandeja
        self.btn_hide = ctk.CTkButton(
            top_bar,
            text="✕",
            width=20,
            height=20,
            corner_radius=10,
            fg_color="transparent",
            hover_color="#c0392b",
            text_color="#a0a0a0",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.hide_to_tray,
        )
        self.btn_hide.pack(side="right", padx=(4, 0))

        # Botão Configurações (Engrenagem)
        self.btn_settings = ctk.CTkButton(
            top_bar,
            text="⚙",
            width=20,
            height=20,
            corner_radius=10,
            fg_color="transparent",
            hover_color="#2c2c34",
            text_color="#a0a0a0",
            font=ctk.CTkFont(size=12),
            command=self.open_settings,
        )
        self.btn_settings.pack(side="right")

        # Menu Seletor de Perfis (CTkOptionMenu discreto)
        self.profile_var = ctk.StringVar(value=self.active_profile)
        self.profile_menu = ctk.CTkOptionMenu(
            self.card,
            values=list(self.profiles.keys()),
            variable=self.profile_var,
            width=190,
            height=24,
            corner_radius=6,
            fg_color="#2b2b36",
            button_color="#3a3a48",
            button_hover_color="#4a4a58",
            dropdown_fg_color="#24242e",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.on_profile_change,
        )
        self.profile_menu.pack(pady=(4, 6))

        # Contador Numérico
        self.counter_label = ctk.CTkLabel(
            self.card,
            text="",
            font=ctk.CTkFont(size=25, weight="bold"),
            text_color="#ffffff",
        )
        self.counter_label.pack(pady=(2, 4))

        # Barra de Progresso
        self.progress_bar = ctk.CTkProgressBar(
            self.card,
            width=190,
            height=9,
            corner_radius=5,
        )
        self.progress_bar.pack(pady=(0, 6))

        # Rótulo de Ajuda com Atalho
        self.shortcut_label = ctk.CTkLabel(
            self.card,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#888888",
        )
        self.shortcut_label.pack(pady=(0, 8))

        # Botões de Ação
        self.btn_deduct = ctk.CTkButton(
            self.card,
            text="-1 Prompt",
            width=190,
            height=30,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.deduct_prompt,
        )
        self.btn_deduct.pack(pady=(0, 6))

        self.btn_reset = ctk.CTkButton(
            self.card,
            text="Reset",
            width=190,
            height=26,
            fg_color="transparent",
            border_width=1,
            border_color="#444444",
            hover_color="#2c2c34",
            text_color="#cccccc",
            font=ctk.CTkFont(size=12),
            command=self.reset_quota,
        )
        self.btn_reset.pack(pady=(0, 8))

        self.update_display()

    def setup_drag_bindings(self):
        """Vincula manipuladores de eventos de clique e arrasto aos elementos de fundo."""
        draggable_widgets = [
            self,
            self.card,
            self.title_label,
            self.counter_label,
            self.shortcut_label,
        ]
        for widget in draggable_widgets:
            widget.bind("<Button-1>", self.on_drag_start)
            widget.bind("<B1-Motion>", self.on_drag_motion)
            widget.bind("<ButtonRelease-1>", self.on_drag_end)

    def on_drag_start(self, event):
        self._offset_x = event.x_root - self.winfo_x()
        self._offset_y = event.y_root - self.winfo_y()

    def on_drag_motion(self, event):
        new_x = event.x_root - self._offset_x
        new_y = event.y_root - self._offset_y
        self.window_state["x"] = new_x
        self.window_state["y"] = new_y
        self.geometry(f"+{new_x}+{new_y}")

    def on_drag_end(self, event):
        self.save_data()

    def setup_windows_taskbar(self):
        """Habilita o ícone na barra de tarefas para janela frameless no Windows."""
        if sys.platform == "win32":
            self.update_idletasks()
            try:
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

                self.wm_withdraw()
                self.after(20, self._reveal_window)
            except Exception as e:
                print(f"Notice: taskbar styling fallback: {e}")
                self.lift()
                self.attributes("-topmost", True)
        else:
            self.lift()

    def _reveal_window(self):
        self.wm_deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()

    def load_data(self):
        """Carrega e migra transparentemente o esquema de dados JSON."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Migração caso o JSON esteja no formato legado anterior
                if "profiles" not in data:
                    legacy_current = data.get("current", 50)
                    legacy_max = data.get("max", 50)
                    today_str = datetime.date.today().isoformat()

                    self.profiles = dict(DEFAULT_PROFILES)
                    self.profiles["Gemini Pro"]["current"] = legacy_current
                    self.profiles["Gemini Pro"]["max"] = legacy_max
                    self.profiles["Gemini Pro"]["last_reset"] = today_str

                    self.window_state = dict(DEFAULT_WINDOW_STATE)
                    self.window_state["x"] = data.get("x")
                    self.window_state["y"] = data.get("y")
                    self.active_profile = "Gemini Pro"
                    self.save_data()
                    return

                # Esquema atualizado
                self.profiles = data.get("profiles", dict(DEFAULT_PROFILES))
                self.window_state = data.get("window_state", dict(DEFAULT_WINDOW_STATE))
                self.active_profile = data.get("active_profile", "Gemini Pro")

                # Garante integridade se algum perfil padrão faltar
                for default_p, pvals in DEFAULT_PROFILES.items():
                    if default_p not in self.profiles:
                        self.profiles[default_p] = dict(pvals)

                if self.active_profile not in self.profiles:
                    self.active_profile = list(self.profiles.keys())[0]

                return
            except Exception as e:
                print(f"Erro ao carregar quota_data.json: {e}")

        # Fallback para novos arquivos
        self.profiles = dict(DEFAULT_PROFILES)
        self.window_state = dict(DEFAULT_WINDOW_STATE)
        self.active_profile = "Gemini Pro"
        self.save_data()

    def save_data(self):
        """Persiste o estado completo de perfis e janela no arquivo JSON."""
        try:
            payload = {
                "window_state": self.window_state,
                "profiles": self.profiles,
                "active_profile": self.active_profile,
            }
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"Erro ao gravar dados em {DATA_FILE}: {e}")

    def update_display(self):
        """Atualiza componentes visuais (contador, progresso, cor e atalho) conforme perfil ativo."""
        profile_data = self.profiles.get(self.active_profile, {"current": 0, "max": 1})
        current = profile_data.get("current", 0)
        max_quota = profile_data.get("max", 1)

        self.counter_label.configure(text=f"{current}/{max_quota}")

        ratio = current / max_quota if max_quota > 0 else 0
        ratio = max(0.0, min(1.0, ratio))
        self.progress_bar.set(ratio)

        # Regra de transição de cor: vermelho se <= 20%, azul se > 20%
        if ratio <= 0.20:
            self.progress_bar.configure(progress_color="#e74c3c")
        else:
            self.progress_bar.configure(progress_color="#3b8ed0")

        # Atualiza texto do atalho
        current_shortcut = self.window_state.get("shortcut", "ctrl+shift+p").upper()
        self.shortcut_label.configure(text=f"Atalho: {current_shortcut}")

        # Sincroniza seletor de perfil
        if hasattr(self, "profile_var") and self.profile_var.get() != self.active_profile:
            self.profile_var.set(self.active_profile)

    def on_profile_change(self, selected_profile: str):
        """Trata a alteração de perfil selecionado no CTkOptionMenu."""
        if selected_profile in self.profiles:
            self.active_profile = selected_profile
            self.save_data()
            self.update_display()

    def deduct_prompt(self):
        """Deduz 1 da cota do perfil ativo e atualiza persistência/UI."""
        profile_data = self.profiles.get(self.active_profile)
        if profile_data and profile_data.get("current", 0) > 0:
            profile_data["current"] -= 1
            self.save_data()
            self.update_display()

    def reset_quota(self):
        """Restaura a cota do perfil ativo para o valor máximo."""
        profile_data = self.profiles.get(self.active_profile)
        if profile_data:
            profile_data["current"] = profile_data.get("max", 50)
            self.save_data()
            self.update_display()

    def check_daily_reset(self):
        """Motor de reset diário: verifica a data de cada perfil e agenda nova execução em 60s."""
        today_iso = datetime.date.today().isoformat()
        has_changed = False

        for pname, pdata in self.profiles.items():
            last_reset = pdata.get("last_reset")
            if last_reset != today_iso:
                pdata["current"] = pdata.get("max", 50)
                pdata["last_reset"] = today_iso
                has_changed = True

        if has_changed:
            self.save_data()
            self.update_display()

        # Reagenda em background na thread principal do Tkinter
        self.after(60000, self.check_daily_reset)

    def setup_hotkey(self, shortcut: str):
        """Registra o atalho global em segundo plano com tratamento seguro de thread."""
        if hasattr(self, "_hotkey_handler") and self._hotkey_handler is not None:
            try:
                keyboard.remove_hotkey(self._hotkey_handler)
            except Exception:
                pass
            self._hotkey_handler = None

        try:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            self._hotkey_handler = keyboard.add_hotkey(
                shortcut, lambda: self.after(0, self.deduct_prompt)
            )
        except Exception as e:
            print(f"Erro ao registrar atalho global '{shortcut}': {e}")

    def open_settings(self):
        """Abre a janela modal de configurações."""
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self)

    def show_window(self):
        """Restaura a visibilidade do widget e garante que esteja no topo."""
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()

    def hide_to_tray(self):
        """Oculta a janela principal para a bandeja do sistema."""
        self.withdraw()

    def start_system_tray(self):
        """Inicializa o ícone da bandeja em uma thread dedicada não bloqueante."""
        self.tray_thread = threading.Thread(target=self._run_tray_loop, daemon=True)
        self.tray_thread.start()

    def _run_tray_loop(self):
        """Loop de execução da bandeja com pystray e tratamento thread-safe."""
        icon_image = generate_tray_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar Widget", lambda: self.after(0, self.show_window), default=True),
            pystray.MenuItem("Configurações", lambda: self.after(0, self.open_settings)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", lambda: self.after(0, self.exit_app)),
        )
        self.tray_icon = pystray.Icon("gemini_quota_gadget", icon_image, "Gemini Quota Gadget", menu=menu)
        self.tray_icon.run()

    def exit_app(self):
        """Finalização segura: remove hooks de teclado, para o tray e destrói o app."""
        try:
            keyboard.unhook_all_hotkeys()
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

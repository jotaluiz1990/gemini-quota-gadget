import ctypes
import json
import os
import sys
import customtkinter as ctk
import keyboard

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quota_data.json")
DEFAULT_MAX_QUOTA = 50
WIDTH = 220
HEIGHT = 250

# Visual theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class GeminiQuotaWidget(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Data state
        self.max_quota = DEFAULT_MAX_QUOTA
        self.current_quota = DEFAULT_MAX_QUOTA
        self.pos_x = None
        self.pos_y = None
        self.load_quota()

        # Calculate position (saved position or screen center)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if self.pos_x is None or self.pos_y is None:
            self.pos_x = (sw - WIDTH) // 2
            self.pos_y = (sh - HEIGHT) // 2
        else:
            # Ensure coordinates are within screen bounds
            self.pos_x = max(0, min(sw - WIDTH, self.pos_x))
            self.pos_y = max(0, min(sh - HEIGHT, self.pos_y))

        # Window settings
        self.title("Gemini Quota")
        self.geometry(f"{WIDTH}x{HEIGHT}+{self.pos_x}+{self.pos_y}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        # Position offset variables for dragging
        self._offset_x = 0
        self._offset_y = 0

        # UI Layout
        self.build_ui()

        # Setup drag and drop
        self.setup_drag_bindings()

        # Global hotkey (Ctrl + Shift + P)
        self.setup_hotkey()

        # Ensure taskbar visibility and topmost on Windows
        self.setup_windows_taskbar()

    def setup_windows_taskbar(self):
        if sys.platform == "win32":
            self.update_idletasks()
            try:
                # Add WS_EX_APPWINDOW to make borderless window appear on the taskbar
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

                # Re-assert visibility and topmost status
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

    def build_ui(self):
        # Card container with subtle border
        self.card = ctk.CTkFrame(
            self,
            corner_radius=12,
            border_width=1,
            border_color="#3a3a3c",
            fg_color="#1e1e24",
        )
        self.card.pack(fill="both", expand=True, padx=2, pady=2)

        # Top Bar (Title & Close Button)
        top_bar = ctk.CTkFrame(self.card, fg_color="transparent")
        top_bar.pack(fill="x", padx=12, pady=(10, 0))

        self.title_label = ctk.CTkLabel(
            top_bar,
            text="Gemini Quota",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e0e0e0",
        )
        self.title_label.pack(side="left")

        self.btn_close = ctk.CTkButton(
            top_bar,
            text="✕",
            width=22,
            height=22,
            corner_radius=11,
            fg_color="transparent",
            hover_color="#c0392b",
            text_color="#a0a0a0",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.close_app,
        )
        self.btn_close.pack(side="right")

        # Quota Counter
        self.counter_label = ctk.CTkLabel(
            self.card,
            text="",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="#ffffff",
        )
        self.counter_label.pack(pady=(12, 4))

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(
            self.card,
            width=180,
            height=10,
            corner_radius=5,
        )
        self.progress_bar.pack(pady=(0, 6))

        # Shortcut Helper
        self.shortcut_label = ctk.CTkLabel(
            self.card,
            text="Atalho: Ctrl + Shift + P",
            font=ctk.CTkFont(size=10),
            text_color="#888888",
        )
        self.shortcut_label.pack(pady=(0, 10))

        # Buttons
        self.btn_deduct = ctk.CTkButton(
            self.card,
            text="-1 Prompt",
            width=180,
            height=32,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.deduct_prompt,
        )
        self.btn_deduct.pack(pady=(0, 6))

        self.btn_reset = ctk.CTkButton(
            self.card,
            text="Reset",
            width=180,
            height=28,
            fg_color="transparent",
            border_width=1,
            border_color="#444444",
            hover_color="#2c2c34",
            text_color="#cccccc",
            font=ctk.CTkFont(size=12),
            command=self.reset_quota,
        )
        self.btn_reset.pack(pady=(0, 10))

        # Update initial display
        self.update_display()

    def setup_drag_bindings(self):
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
        self.pos_x = new_x
        self.pos_y = new_y
        self.geometry(f"+{new_x}+{new_y}")

    def on_drag_end(self, event):
        self.save_quota()

    def load_quota(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.current_quota = int(data.get("current", DEFAULT_MAX_QUOTA))
                    self.max_quota = int(data.get("max", DEFAULT_MAX_QUOTA))
                    self.pos_x = data.get("x")
                    self.pos_y = data.get("y")
                    return
            except Exception:
                pass
        self.current_quota = DEFAULT_MAX_QUOTA
        self.max_quota = DEFAULT_MAX_QUOTA
        self.save_quota()

    def save_quota(self):
        try:
            payload = {
                "current": self.current_quota,
                "max": self.max_quota,
            }
            if self.pos_x is not None and self.pos_y is not None:
                payload["x"] = self.pos_x
                payload["y"] = self.pos_y

            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"Error saving quota: {e}")

    def update_display(self):
        # Update text counter
        self.counter_label.configure(text=f"{self.current_quota}/{self.max_quota}")

        # Update progress bar and color
        ratio = self.current_quota / self.max_quota if self.max_quota > 0 else 0
        ratio = max(0.0, min(1.0, ratio))
        self.progress_bar.set(ratio)

        # Progress bar turns red when <= 20% (0.2), blue otherwise
        if ratio <= 0.20:
            self.progress_bar.configure(progress_color="#e74c3c")
        else:
            self.progress_bar.configure(progress_color="#3b8ed0")

    def deduct_prompt(self):
        if self.current_quota > 0:
            self.current_quota -= 1
            self.save_quota()
            self.update_display()

    def reset_quota(self):
        self.current_quota = self.max_quota
        self.save_quota()
        self.update_display()

    def setup_hotkey(self):
        try:
            keyboard.add_hotkey("ctrl+shift+p", lambda: self.after(0, self.deduct_prompt))
        except Exception as e:
            print(f"Error setting up hotkey: {e}")

    def close_app(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = GeminiQuotaWidget()
    app.mainloop()

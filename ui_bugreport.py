"""Hot-patch: prida tlacitko Nahlásit chybu do sidebaru Gasbyn Clipper."""
from __future__ import annotations

def install(app_cls):
    import bugreport
    import customtkinter as ctk

    if getattr(app_cls, "_bugreport_installed", False):
        return
    app_cls._bugreport_installed = True

    orig_build = app_cls._build_sidebar

    def _build_sidebar(self):
        orig_build(self)
        try:
            side = self.winfo_children()[0]
        except Exception:
            return
        try:
            ctk.CTkButton(
                side, text="Nahlásit chybu", height=32, corner_radius=8,
                fg_color="#17191E", hover_color="#24272E", text_color="#FF9A52",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                command=self.report_bug,
            ).pack(fill="x", padx=20, pady=(8, 0), before=side.winfo_children()[-1])
        except Exception:
            ctk.CTkButton(
                side, text="Nahlásit chybu", height=32, corner_radius=8,
                fg_color="#17191E", hover_color="#24272E", text_color="#FF9A52",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                command=self.report_bug,
            ).pack(fill="x", padx=20, pady=(8, 0))

    def report_bug(self):
        BG, PANEL, INPUT, BORDER = "#08090B", "#121419", "#17191E", "#24272E"
        TEXT, MUTED, ORANGE, ORANGE_LIGHT, GREEN, RED = (
            "#F4F4F5", "#858A94", "#FF6A00", "#FF9A52", "#48D597", "#F87171")
        font = lambda s, b=False: ctk.CTkFont(family="Segoe UI", size=s, weight="bold" if b else "normal")
        win = ctk.CTkToplevel(self)
        win.title("Nahlásit chybu")
        win.geometry("520x420")
        win.configure(fg_color=BG)
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Popiš problém", font=font(16, True), text_color=TEXT).pack(
            anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(win, text="Automaticky se připojí logy, verze a sestava PC.",
                     font=font(11), text_color=MUTED, wraplength=460, justify="left").pack(anchor="w", padx=20)
        box = ctk.CTkTextbox(win, fg_color=PANEL, border_color=BORDER, border_width=1,
                             corner_radius=12, font=font(12), text_color=TEXT)
        box.pack(fill="both", expand=True, padx=20, pady=14)
        status = ctk.CTkLabel(win, text="", font=font(11), text_color=MUTED)
        status.pack(anchor="w", padx=20)

        def send():
            desc = box.get("1.0", "end").strip()
            if not desc:
                status.configure(text="Napiš aspoň krátký popis.", text_color=RED)
                return
            try:
                log = self.log_box.get("1.0", "end") if hasattr(self, "log_box") else ""
            except Exception:
                log = ""
            try:
                path = bugreport.submit_bug_report(desc, log)
                status.configure(text=f"Uloženo: {path}\nOtevřel se GitHub – přilož soubor k issue.",
                                 text_color=GREEN)
            except Exception as exc:
                status.configure(text=f"Chyba: {exc}", text_color=RED)

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(row, text="Zrušit", height=36, corner_radius=9, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=font(12),
                      command=win.destroy).pack(side="left")
        ctk.CTkButton(row, text="Odeslat hlášení", height=36, corner_radius=9, fg_color=ORANGE,
                      hover_color=ORANGE_LIGHT, text_color="white", font=font(12, True),
                      command=send).pack(side="right")

    app_cls._build_sidebar = _build_sidebar
    app_cls.report_bug = report_bug

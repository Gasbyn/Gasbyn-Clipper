"""Gasbyn Clipper - grafické rozhraní (vzhled inspirovaný Gasbyn Optimizeru).

Spuštění: python app.py
"""

from __future__ import annotations

import copy
import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import core
import updater
import youtube
from editor import EditorPage
from loadout import LoadoutPage
from version import APP_VERSION
import time

from core import (Reporter, Cancelled, run_job, clean_cache, cache_report,
                  auto_clean, check_environment, load_or_default, save, ROOT,
                  record_feedback, setup_status, pull_ollama_model, prefetch_whisper,
                  OLLAMA_INSTALLER_URL)
from schema import SECTIONS, default_settings, _coerce

# barvy z GasbynOptimizeru (MainWindow.xaml)
BG = "#08090B"
PANEL = "#121419"
INPUT = "#17191E"
BORDER = "#24272E"
BLOCK = "#2A2E37"
TEXT = "#F4F4F5"
MUTED = "#858A94"
DIM = "#5E636D"
ORANGE = "#FF6A00"
ORANGE_LIGHT = "#FF9A52"
ORANGE_SOFT = "#21150E"
GREEN = "#48D597"
RED = "#F87171"
YELLOW = "#FBBF24"
FONT = "Segoe UI"
MONO = "Consolas"


def fnt(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def mono(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO, size=size)


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {(seconds % 3600) // 60:02d} min"


def score_color(score: float) -> str:
    if score >= 75:
        return GREEN
    if score >= 50:
        return ORANGE_LIGHT
    return RED


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Gasbyn Clipper")
        self.geometry("1280x800")
        self.minsize(1050, 680)
        self.configure(fg_color=BG)

        self.cfg = load_or_default()
        self.events: queue.Queue = queue.Queue()
        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav: dict[str, ctk.CTkButton] = {}
        self.setting_widgets: dict[tuple[str, str], tuple] = {}
        self.bg_events: queue.Queue = queue.Queue()
        self._update_info: dict | None = None
        # fronta zdrojů: index právě běžícího, počet, čas začátku (pro ETA)
        self._queue_idx = 0
        self._queue_total = 1
        self._queue_t0: float | None = None
        self._queue_frac = 0.0

        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True, padx=28, pady=24)

        self._build_create_page()
        self._build_results_page()
        self._build_settings_page()
        self._build_cache_page()
        self.pages["editor"] = EditorPage(self.content, self)
        self.pages["loadout"] = LoadoutPage(self.content, self)
        self.current_loadout: dict | None = None
        self._stage_key = None
        self._stage_t0 = 0.0
        # Ollama se spustí na pozadí hned po zapnutí aplikace
        threading.Thread(target=core.start_ollama_background, args=(self.cfg,), daemon=True).start()

        self.show("create")
        self.after(100, self._poll_events)
        self.after(200, self._poll_extra)
        if updater.is_frozen() and self.cfg["updates"]["auto_check"]:
            self._start_update_check()

    # ------------------------------------------------------------ kostra

    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self, width=230, fg_color=PANEL, corner_radius=0)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        ctk.CTkLabel(side, text="GASBYN", font=fnt(24, True), text_color=ORANGE).pack(
            anchor="w", padx=24, pady=(30, 0))
        ctk.CTkLabel(side, text="CLIPPER", font=fnt(13, True), text_color=TEXT).pack(
            anchor="w", padx=24)
        ctk.CTkLabel(side, text="AI klipy pro Shorts, Reels a TikTok", font=fnt(10),
                     text_color=DIM).pack(anchor="w", padx=24, pady=(2, 26))

        items = [("create", "Vytvořit klipy"), ("results", "Hotové klipy"),
                 ("settings", "Nastavení"), ("cache", "Cache a úklid")]
        for key, label in items:
            btn = ctk.CTkButton(
                side, text=label, anchor="w", height=40, corner_radius=10,
                fg_color="transparent", hover_color="#17191E", text_color=MUTED,
                font=fnt(13), command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=14, pady=3)
            self.nav[key] = btn

        ctk.CTkFrame(side, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=20)
        self.env_label = ctk.CTkLabel(side, text="Prostředí nekontrolováno", font=fnt(11),
                                      text_color=MUTED, justify="left", wraplength=190)
        self.env_label.pack(anchor="w", padx=24)
        ctk.CTkButton(side, text="Zkontrolovat prostředí", height=32, corner_radius=8,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=fnt(11),
                      command=self.check_env).pack(fill="x", padx=20, pady=(10, 0))
        self.update_btn = ctk.CTkButton(
            side, text="", height=34, corner_radius=8, fg_color=ORANGE, hover_color=ORANGE_LIGHT,
            text_color="white", font=fnt(11, True), command=self.install_update)
        ctk.CTkLabel(side, text=f"Verze {APP_VERSION}", font=fnt(10), text_color=DIM).pack(
            side="bottom", anchor="w", padx=24, pady=12)

    def show(self, name: str) -> None:
        for key, frame in self.pages.items():
            frame.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for key, btn in self.nav.items():
            active = key == name
            btn.configure(fg_color=ORANGE_SOFT if active else "transparent",
                          text_color=ORANGE_LIGHT if active else MUTED)
        if name == "results":
            self.refresh_results_list()
        elif name == "cache":
            self.refresh_cache()

    def _card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color=PANEL, border_color=BORDER, border_width=1,
                            corner_radius=14)

    def _title(self, parent, text: str, sub: str) -> None:
        ctk.CTkLabel(parent, text=text, font=fnt(26, True), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(parent, text=sub, font=fnt(12), text_color=MUTED,
                     wraplength=820, justify="left").pack(anchor="w", pady=(2, 18))

    # ------------------------------------------------------------ 1. vytvořit

    def _build_create_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.pages["create"] = page
        self._title(page, "Vytvořit klipy",
                    "Vlož URL VODu nebo cestu k videu. AI najde momenty, každému dá hodnocení 0 až 100 "
                    "a vystřihne vertikální klipy. Klipy pod nastaveným prahem se nevytvoří.")

        self._build_setup_card(page)
        self._build_search_card(page)

        card = self._card(page)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=20)

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.url_var = ctk.StringVar(value=self.cfg["source"]["url"])
        ctk.CTkEntry(row, textvariable=self.url_var, height=40, corner_radius=9,
                     fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=fnt(12),
                     placeholder_text="URL nebo cesta; více oddělených středníkem ; se zpracuje postupně"
                     ).pack(side="left", fill="x", expand=True)
        self.start_btn = ctk.CTkButton(
            row, text="Spustit AI Clipper", height=40, corner_radius=9, fg_color=ORANGE,
            hover_color=ORANGE_LIGHT, text_color="white", font=fnt(13, True),
            command=self.start)
        self.start_btn.pack(side="left", padx=(12, 0))
        self.stop_btn = ctk.CTkButton(
            row, text="Zrušit", height=40, corner_radius=9, fg_color="transparent",
            border_width=1, border_color=RED, text_color=RED, hover_color=INPUT,
            font=fnt(12), state="disabled", command=self.cancel)
        self.stop_btn.pack(side="left", padx=(8, 0))

        opts = ctk.CTkFrame(inner, fg_color="transparent")
        opts.pack(fill="x", pady=(16, 0))
        self.captions_var = ctk.BooleanVar(value=bool(self.cfg["captions"]["enabled"]))
        ctk.CTkSwitch(opts, text="Titulky", variable=self.captions_var, progress_color=ORANGE,
                      font=fnt(12), text_color=TEXT).pack(side="left")
        self.reselect_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts, text="Znovu zavolat AI (ignorovat cache)",
                        variable=self.reselect_var, fg_color=ORANGE, hover_color=ORANGE_LIGHT,
                        border_color=BORDER, font=fnt(12), text_color=TEXT
                        ).pack(side="left", padx=(28, 0))
        self.prep_btn = ctk.CTkButton(opts, text="Načíst video a nastavit loadout", height=30,
                                      corner_radius=8, fg_color=INPUT, hover_color=BORDER,
                                      text_color=ORANGE_LIGHT, font=fnt(11, True),
                                      command=self.prepare_loadout)
        self.prep_btn.pack(side="left", padx=(28, 0))
        self.loadout_label = ctk.CTkLabel(opts, text="Loadout: výchozí (střed 9:16)",
                                          font=fnt(11), text_color=MUTED)
        self.loadout_label.pack(side="left", padx=(14, 0))

        self.progress = ctk.CTkProgressBar(inner, progress_color=ORANGE, fg_color=INPUT,
                                           height=8, corner_radius=4)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(18, 6))
        stats =ctk.CTkFrame(inner, fg_color="transparent")
        stats.pack(fill="x")
        self.overall_label = ctk.CTkLabel(stats, text="Celkem 0 %", font=fnt(12, True),
                                          text_color=TEXT, anchor="w")
        self.overall_label.pack(side="left")
        self.eta_label = ctk.CTkLabel(stats, text="", font=fnt(11), text_color=MUTED, anchor="e")
        self.eta_label.pack(side="right")
        self.status = ctk.CTkLabel(inner, text="Připraveno", font=fnt(11), text_color=MUTED,
                                   anchor="w")
        self.status.pack(fill="x")

        ctk.CTkLabel(page, text="Průběh", font=fnt(12, True), text_color=MUTED).pack(
            anchor="w", pady=(18, 6))
        self.log_box = ctk.CTkTextbox(page, fg_color=PANEL, border_color=BORDER, border_width=1,
                                      corner_radius=14, font=mono(12), text_color="#B7BBC3")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start(self) -> None:
        sources = [s.strip() for s in self.url_var.get().split(";") if s.strip()]
        if not sources:
            self.status.configure(text="Vlož URL nebo cestu k videu.", text_color=RED)
            return
        if self.worker and self.worker.is_alive():
            return
        cfg = copy.deepcopy(self.cfg)
        self.cancel_event = threading.Event()
        rep = Reporter(
            log=lambda m: self.events.put(("log", m)),
            progress=lambda f, t: self.events.put(("progress", f, t)),
            cancel=self.cancel_event,
        )
        kwargs = {"reselect": bool(self.reselect_var.get()),
                  "captions_override": bool(self.captions_var.get()),
                  "loadout": self.current_loadout}
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress.set(0)
        self._queue_total = len(sources)
        self._queue_idx = 0
        self._queue_frac = 0.0
        self._queue_t0 = time.time()
        self._update_overall(0.0)
        self.status.configure(text="Spouštím…", text_color=MUTED)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._work, args=(sources, cfg, rep, kwargs),
                                       daemon=True)
        self.worker.start()

    def _work(self, sources: list[str], cfg: dict, rep: Reporter, kwargs: dict) -> None:
        # Zdroje se zpracují postupně, aby běžel jen jeden přepis a jedno ffmpeg.
        for i, src in enumerate(sources):
            self.events.put(("queue", i, len(sources)))
            try:
                result = run_job(src, cfg, rep, **kwargs)
                self.events.put(("job_done", result))
            except Cancelled as exc:
                self.events.put(("cancelled", str(exc)))
                return
            except Exception as exc:  # noqa: BLE001 - chceme ukázat chybu uživateli
                self.events.put(("log", f"Zdroj {src} selhal: {exc}"))
                self.events.put(("log", traceback.format_exc()))
                self.events.put(("error", f"{exc}"))
        self.events.put(("all_done", len(sources)))

    def cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            self.status.configure(text="Ruším…", text_color=YELLOW)

    def _finish_worker_ui(self) -> None:
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    STAGES = [(0.0, 0.25, "stažení videa"), (0.25, 0.55, "přepis"),
              (0.55, 0.75, "hodnocení AI"), (0.75, 1.0, "střih klipů")]

    def _update_overall(self, frac_current: float) -> None:
        """Celkový % přes frontu, odhad dokončení aktuálního kroku a celého zpracování."""
        total = max(1, self._queue_total)
        overall = min(1.0, (self._queue_idx + frac_current) / total)
        self.progress.set(overall)
        self.overall_label.configure(
            text=f"Celkem {overall * 100:.0f} %"
                 + (f"  ·  zdroj {self._queue_idx + 1}/{total}" if total > 1 else ""))
        now = time.time()
        if self._queue_t0 is None or overall <= 0.02:
            self.eta_label.configure(text="")
            return
        remaining = (now - self._queue_t0) * (1 - overall) / overall
        idx = next(i for i, (a_, b_, _n) in enumerate(self.STAGES)
                   if frac_current < b_ or i == len(self.STAGES) - 1)
        a_, b_, name = self.STAGES[idx]
        if self._stage_key != (self._queue_idx, idx):
            self._stage_key = (self._queue_idx, idx)
            self._stage_t0 = now
        parts = []
        local = (frac_current - a_) / (b_ - a_)
        if local > 0.03 and now > self._stage_t0:
            stage_left = (now - self._stage_t0) * (1 - local) / local
            parts.append(f"{name[0].upper() + name[1:]} hotovo za {fmt_duration(stage_left)}")
        parts.append(f"Vše za {fmt_duration(remaining)}")
        self.eta_label.configure(text="  ·  ".join(parts))

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self._append_log(ev[1])
                elif kind == "queue":
                    self._queue_idx = ev[1]
                    self._queue_total = ev[2]
                    self._queue_frac = 0.0
                    self._update_overall(0.0)
                elif kind == "progress":
                    self._queue_frac = ev[1]
                    self._update_overall(ev[1])
                    if ev[2]:
                        self.status.configure(text=f"Právě: {ev[2]}", text_color=MUTED)
                elif kind == "job_done":
                    result = ev[1]
                    self._selected_folder = result["out_dir"]
                    self.status.configure(text=f"Hotovo: {len(result['clips'])} klipů",
                                          text_color=GREEN)
                    if self.cfg["output"]["open_folder_after"]:
                        open_path(result["out_dir"])
                elif kind == "all_done":
                    self._finish_worker_ui()
                    self._update_overall(1.0)
                    self.eta_label.configure(text="")
                    self.status.configure(text=f"Fronta hotová ({ev[1]} zdrojů)",
                                          text_color=GREEN)
                    self.refresh_results_list()
                elif kind == "cancelled":
                    self._finish_worker_ui()
                    self.status.configure(text=ev[1], text_color=YELLOW)
                elif kind == "error":
                    self.status.configure(text=f"Chyba: {ev[1]}", text_color=RED)
                elif kind == "prep_done":
                    self.prep_btn.configure(state="normal")
                    self.status.configure(text="Snímek je připravený, nastav loadout.", text_color=GREEN)
                    self.pages["loadout"].open(ev[1], ev[2])
                    self.show("loadout")
                elif kind == "prep_error":
                    self.prep_btn.configure(state="normal")
                    self.status.configure(text=f"Chyba: {ev[1]}", text_color=RED)
                elif kind == "search_done":
                    self.search_btn.configure(state="normal")
                    self.search_status.configure(text=f"Nalezeno: {len(ev[1])}", text_color=MUTED)
                    self._render_results(ev[1])
                elif kind == "search_error":
                    self.search_btn.configure(state="normal")
                    self.search_status.configure(text=f"Hledání selhalo: {ev[1]}", text_color=RED)
                elif kind == "setup_log":
                    self._append_log(ev[1])
                elif kind == "setup_progress":
                    self.setup_bar.set(ev[1])
                    if ev[2]:
                        self.setup_status.configure(text=ev[2])
                elif kind == "setup_done":
                    self._setup_busy(False)
                    self.refresh_setup()
                elif kind == "setup_error":
                    self._setup_busy(False)
                    self.setup_status.configure(text=f"Chyba: {ev[1]}", text_color=RED)
                    self.refresh_setup()
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    # ------------------------------------------------------------ první spuštění

    def _build_setup_card(self, page) -> None:
        self.setup_card = self._card(page)
        self.setup_card.pack(fill="x", pady=(0, 14))
        inner = ctk.CTkFrame(self.setup_card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)
        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="Připravenost k použití", font=fnt(13, True), text_color=TEXT
                     ).pack(side="left")
        self.setup_summary = ctk.CTkLabel(head, text="", font=fnt(11), text_color=MUTED)
        self.setup_summary.pack(side="left", padx=(12, 0))
        self.setup_rows = ctk.CTkFrame(inner, fg_color="transparent")
        self.setup_rows.pack(fill="x", pady=(8, 0))
        self.setup_bar = ctk.CTkProgressBar(inner, progress_color=ORANGE, fg_color=INPUT,
                                            height=6, corner_radius=3)
        self.setup_bar.set(0)
        self.setup_status = ctk.CTkLabel(inner, text="", font=fnt(11), text_color=MUTED, anchor="w")
        self.setup_status.pack(fill="x")
        self.after(300, self.refresh_setup)

    def _setup_busy(self, busy: bool) -> None:
        for btn in getattr(self, "_setup_buttons", []):
            btn.configure(state="disabled" if busy else "normal")

    def refresh_setup(self) -> None:
        """Projde stav a vykreslí řádky s tlačítky pro to, co chybí."""
        for w in self.setup_rows.winfo_children():
            w.destroy()
        self._setup_buttons: list = []
        self.setup_status.configure(text="")
        self.setup_bar.pack_forget()
        st = setup_status(self.cfg)
        ok_all = st["ffmpeg"] and (st["model_ready"] or st["provider"] == "openrouter")
        self.setup_summary.configure(
            text="Hotovo, můžeš klipovat." if ok_all else "Chybí pár kroků, viz níže.",
            text_color=GREEN if ok_all else YELLOW)

        def row(label: str, ok: bool, button: str | None = None, action=None) -> None:
            line = ctk.CTkFrame(self.setup_rows, fg_color="transparent")
            line.pack(fill="x", pady=2)
            ctk.CTkLabel(line, text=("✓  " if ok else "○  ") + label, font=fnt(12),
                         text_color=GREEN if ok else TEXT, anchor="w").pack(side="left")
            if not ok and button and action:
                b = ctk.CTkButton(line, text=button, height=28, corner_radius=8, fg_color=ORANGE,
                                  hover_color=ORANGE_LIGHT, font=fnt(11, True),
                                  command=action)
                b.pack(side="right")
                self._setup_buttons.append(b)

        row("ffmpeg (součástí instalace)", st["ffmpeg"])
        if st["provider"] == "ollama":
            row("Ollama běží", st["ollama_running"],
                "Stáhnout a nainstalovat Ollamu" if not st["ollama_installed"] else "Spustit Ollamu",
                self.setup_install_ollama)
            row(f"Model {self.cfg['ai']['ollama_model']} stažen", st["model_ready"],
                "Stáhnout model", self.setup_pull_model)
        else:
            row("OpenRouter klíč v proměnné prostředí", bool(os.environ.get(
                self.cfg["ai"]["openrouter_api_key_env"])))
        row("Přepisovací model Whisper", self._whisper_cached(),
            "Stáhnout Whisper", self.setup_prefetch_whisper)
        self.setup_bar.pack(fill="x", pady=(8, 0))
        self.setup_bar.set(0)

    def _whisper_cached(self) -> bool:
        # faster-whisper ukládá modely do cache Hugging Face; hrubá kontrola podle složky
        name = self.cfg["transcription"]["model"]
        hub = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".cache" / "huggingface" / "hub"
        return hub.exists() and any(name in p.name for p in hub.iterdir())

    def _run_setup(self, fn) -> None:
        self._setup_busy(True)
        rep = Reporter(
            log=lambda m: self.events.put(("setup_log", m)),
            progress=lambda f, t: self.events.put(("setup_progress", f, t)),
        )

        def job() -> None:
            try:
                fn(rep)
                self.events.put(("setup_done",))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("setup_error", str(exc)))
        threading.Thread(target=job, daemon=True).start()

    def setup_install_ollama(self) -> None:
        def fn(rep: Reporter) -> None:
            if core.ollama_installed():
                rep.log("Ollama je nainstalovaná, spouštím ji ...")
                exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
                subprocess.Popen([str(exe) if exe.exists() else "ollama", "serve"],
                                 creationflags=0x08000000)  # CREATE_NO_WINDOW
                time.sleep(3)
                return
            rep.log("Stahuji instalátor Ollamy (oficiální stránka ollama.com) ...")
            import requests as rq
            target = Path(os.environ.get("TEMP", ".")) / "OllamaSetup.exe"
            with rq.get(OLLAMA_INSTALLER_URL, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0)) or None
                done = 0
                with open(target, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            rep.progress(done / total, f"Stahuji Ollamu {done / total * 100:.0f} %")
            rep.log("Spouštím instalátor Ollamy. Po dokončení se vrať sem a klikni Obnovit.")
            subprocess.Popen([str(target)])

        self._run_setup(fn)

    def setup_pull_model(self) -> None:
        self._run_setup(lambda rep: pull_ollama_model(self.cfg, rep))

    def setup_prefetch_whisper(self) -> None:
        self._run_setup(lambda rep: prefetch_whisper(self.cfg, rep))

    # ------------------------------------------------------------ hodnocení klipů

    # ------------------------------------------------------------ vyhledání videa a loadout

    def _build_search_card(self, page) -> None:
        card = self._card(page)
        card.pack(fill="x", pady=(0, 14))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(inner, text="Najít video na platformě", font=fnt(13, True), text_color=TEXT
                     ).pack(anchor="w")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))
        self.platform_var = ctk.StringVar(value="Kick")
        ctk.CTkOptionMenu(row, variable=self.platform_var, values=["Kick"], width=110, height=34,
                          corner_radius=9, fg_color=INPUT, button_color=BORDER,
                          button_hover_color=BLOCK, dropdown_fg_color=PANEL, text_color=TEXT,
                          font=fnt(12)).pack(side="left")
        self.channel_var = ctk.StringVar(value="gasbyn")
        ctk.CTkEntry(row, textvariable=self.channel_var, width=200, height=34, corner_radius=9,
                     fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=fnt(12),
                     placeholder_text="jméno kanálu").pack(side="left", padx=(10, 0))
        self.kind_videos = ctk.BooleanVar(value=True)
        self.kind_clips = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(row, text="Videa (VOD)", variable=self.kind_videos, fg_color=ORANGE,
                        hover_color=ORANGE_LIGHT, border_color=BORDER, font=fnt(12),
                        text_color=TEXT).pack(side="left", padx=(14, 0))
        ctk.CTkCheckBox(row, text="Klipy a shorty", variable=self.kind_clips, fg_color=ORANGE,
                        hover_color=ORANGE_LIGHT, border_color=BORDER, font=fnt(12),
                        text_color=TEXT).pack(side="left", padx=(14, 0))
        self.search_btn = ctk.CTkButton(row, text="Hledat", width=100, height=34, corner_radius=9,
                                        fg_color=ORANGE, hover_color=ORANGE_LIGHT,
                                        text_color="white", font=fnt(12, True),
                                        command=self.search_videos)
        self.search_btn.pack(side="right")
        self.search_status = ctk.CTkLabel(inner, text="", font=fnt(11), text_color=MUTED, anchor="w")
        self.search_status.pack(fill="x", pady=(8, 0))
        self.search_frame = ctk.CTkScrollableFrame(inner, fg_color=INPUT, corner_radius=10, height=170)
        self.search_frame.pack(fill="x", pady=(6, 0))

    def search_videos(self) -> None:
        kinds = [k for k, var in (("videos", self.kind_videos), ("clips", self.kind_clips)) if var.get()]
        if not kinds:
            self.search_status.configure(text="Vyber aspoň jednu kategorii.", text_color=RED)
            return
        channel = self.channel_var.get()
        self.search_btn.configure(state="disabled")
        self.search_status.configure(text="Hledám nejnovější…", text_color=MUTED)

        def job() -> None:
            try:
                items = core.search_kick(channel, kinds, limit=12)
            except Exception as exc:  # noqa: BLE001
                self.events.put(("search_error", str(exc)))
                return
            self.events.put(("search_done", items))
        threading.Thread(target=job, daemon=True).start()

    def _render_results(self, items: list[dict]) -> None:
        for w in self.search_frame.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(self.search_frame, text="Nic nenalezeno.", font=fnt(12), text_color=MUTED
                         ).pack(anchor="w", pady=8)
            return
        for it in items:
            row = ctk.CTkFrame(self.search_frame, fg_color="transparent")
            row.pack(fill="x", pady=2, padx=4)
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(left, text=it["title"], font=fnt(12, True), text_color=TEXT, anchor="w",
                         justify="left", wraplength=480).pack(anchor="w")
            kind = "VOD" if it["kind"] == "videos" else "klip"
            created = it["created"].replace("T", " ")
            ctk.CTkLabel(left, text=f"{kind} · {created} · {it['seconds'] / 60:.0f} min",
                         font=fnt(11), text_color=MUTED, anchor="w").pack(anchor="w")
            ctk.CTkButton(row, text="Vybrat", width=80, height=28, corner_radius=8, fg_color=INPUT,
                          hover_color=BORDER, text_color=ORANGE_LIGHT, font=fnt(11, True),
                          command=lambda u=it["url"], t=it["title"]: self._pick_url(u, t)
                          ).pack(side="right", padx=6)

    def _pick_url(self, url: str, title: str) -> None:
        self.url_var.set(url)
        self.status.configure(text=f"Vybráno: {title}", text_color=GREEN)

    def prepare_loadout(self) -> None:
        """Stáhne video (nebo použije lokální), vytáhne první snímek a otevře editor loadoutu."""
        src = self.url_var.get().strip()
        if not src:
            self.status.configure(text="Vlož nebo vyber video.", text_color=RED)
            return
        if self.worker and self.worker.is_alive():
            return
        cfg = copy.deepcopy(self.cfg)
        self.prep_btn.configure(state="disabled")
        self.status.configure(text="Připravuji snímek pro loadout…", text_color=MUTED)
        rep = Reporter(log=lambda m: self.events.put(("log", m)),
                       progress=lambda f, t: self.events.put(("progress", f, t)))

        def job() -> None:
            try:
                video, vid, _downloaded = core.get_source(src, cfg, rep)
                probe = core.probe_video(video)
                frame = core.extract_frame(video, core.work_root(cfg) / "frames" / f"{vid}.png", 1.0)
                lo = core.last_loadout(cfg) or core.default_loadout("short", probe["width"], probe["height"])
                self.events.put(("prep_done", {"video_id": vid, "probe": probe, "frame": str(frame)}, lo))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("prep_error", str(exc)))
        threading.Thread(target=job, daemon=True).start()

    def apply_loadout(self, lo: dict) -> None:
        self.current_loadout = lo
        self.loadout_label.configure(text=f"Loadout: {lo['name']}")
        self.show("create")
        self.status.configure(text=f"Loadout „{lo['name']}“ je nastavený pro toto video.", text_color=GREEN)

    def _feedback(self, folder: Path, clip: dict, good: bool, btn_row) -> None:
        record_feedback(self.cfg, clip, good)
        for w in btn_row.winfo_children():
            w.configure(state="disabled")
        self.status.configure(
            text="Díky, příště AI přihlédne k tomuto hodnocení." if good
            else "Díky, příště se AI tomuto stylu vyhne.", text_color=GREEN)

    # ------------------------------------------------------------ editor, aktualizace, YouTube

    def open_path(self, path: Path) -> None:
        open_path(path)

    def open_editor(self, folder: Path, file_name: str) -> None:
        if self.pages["editor"].load(folder, file_name):
            self.show("editor")

    def _start_update_check(self) -> None:
        def job() -> None:
            try:
                info = updater.check_for_update()
            except Exception as exc:  # noqa: BLE001
                # Neúspěšná kontrola na pozadí tichá: žádné tlačítko, jen zápis do logu.
                print(f"Kontrola aktualizací selhala: {exc}")
                return
            if info:
                self.bg_events.put(("upd_found", info))
        threading.Thread(target=job, daemon=True).start()

    def install_update(self) -> None:
        if not self._update_info:
            return
        url = self._update_info["url"]
        self.update_btn.configure(state="disabled", text="Stahuji…")

        def job() -> None:
            try:
                path = updater.download_installer(
                    url, progress=lambda f: self.bg_events.put(("upd_progress", f)))
                self.bg_events.put(("upd_ready", str(path)))
            except Exception as exc:  # noqa: BLE001
                self.bg_events.put(("upd_error", f"Stažení selhalo: {exc}"))
        threading.Thread(target=job, daemon=True).start()

    def _update_failed(self, message: str) -> None:
        """Zobrazí skutečnou chybu a nabídne opakování. Tlačítko se ukáže jen u instalace."""
        print(f"Aktualizace selhala: {message}")
        self.update_btn.configure(text="Aktualizace selhala, zkusit znovu",
                                  state="normal", command=self.install_update)
        self.update_btn.pack(side="bottom", fill="x", padx=20, pady=(0, 8))
        self.status.configure(text=f"Aktualizace: {message}", text_color=RED)

    def _poll_extra(self) -> None:
        try:
            while True:
                ev = self.bg_events.get_nowait()
                kind = ev[0]
                if kind == "upd_found":
                    self._update_info = ev[1]
                    if self.cfg["updates"]["auto_install"]:
                        self.install_update()
                    else:
                        self.update_btn.configure(
                            text=f"Aktualizovat na v{ev[1]['version']}", state="normal")
                        self.update_btn.pack(side="bottom", fill="x", padx=20, pady=(0, 8))
                elif kind == "upd_progress":
                    self.update_btn.configure(text=f"Stahuji {ev[1] * 100:.0f} %")
                elif kind == "upd_ready":
                    try:
                        updater.install_and_restart(Path(ev[1]))
                    except OSError as exc:
                        self._update_failed(f"Spuštění instalátoru selhalo: {exc}")
                        continue
                    self.destroy()
                    return
                elif kind == "upd_error":
                    self._update_failed(ev[1])
                elif kind == "yt_done":
                    self.yt_status.configure(text=ev[1], text_color=GREEN)
                elif kind == "yt_error":
                    self.yt_status.configure(text=f"Chyba: {ev[1]}", text_color=RED)
        except queue.Empty:
            pass
        self.after(200, self._poll_extra)

    def connect_youtube(self) -> None:
        raw = self.cfg["youtube"]["client_secret_file"]
        secret = Path(raw) if raw else None
        if not secret or not secret.exists():
            self.yt_status.configure(
                text="Nejdřív vyber soubor client_secret a ulož nastavení.", text_color=RED)
            return
        self.yt_status.configure(text="Otevírám přihlášení v prohlížeči…", text_color=MUTED)

        def job() -> None:
            try:
                youtube.connect(secret, ROOT)
                self.bg_events.put(("yt_done", "Účet YouTube je připojený."))
            except Exception as exc:  # noqa: BLE001
                self.bg_events.put(("yt_error", str(exc)))
        threading.Thread(target=job, daemon=True).start()

    def disconnect_youtube(self) -> None:
        youtube.disconnect(ROOT)
        self.yt_status.configure(text="Odpojeno.", text_color=MUTED)

    def check_env(self) -> None:
        lines = check_environment(self.cfg)
        self.env_label.configure(text="\n".join(lines),
                                 text_color=GREEN if all("OK" in l or "ano" in l or "nastaven" in l
                                                         for l in lines) else YELLOW)
        messagebox.showinfo("Prostředí", "\n".join(lines))

    # ------------------------------------------------------------ 2. výsledky

    def _build_results_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.pages["results"] = page
        self._title(page, "Hotové klipy",
                    "Klipy seřazené podle hodnocení. Pro každý klip vidíš skóre, popis a hashtagy.")

        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", pady=(0, 14))
        self.result_choice = ctk.CTkOptionMenu(
            top, values=["—"], width=520, height=36, corner_radius=9, fg_color=INPUT,
            button_color=BORDER, button_hover_color="#2A2E37", dropdown_fg_color=PANEL,
            text_color=TEXT, font=fnt(12), command=self.load_results)
        self.result_choice.pack(side="left")
        ctk.CTkButton(top, text="Obnovit", width=110, height=36, corner_radius=9,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=fnt(12),
                      command=self.refresh_results_list).pack(side="left", padx=(10, 0))

        self.results_frame = ctk.CTkScrollableFrame(page, fg_color=BG, corner_radius=0)
        self.results_frame.pack(fill="both", expand=True)
        self._result_folders: dict[str, Path] = {}

    def _output_root(self) -> Path:
        return ROOT / self.cfg["output"]["folder"]

    def refresh_results_list(self) -> None:
        root = self._output_root()
        folders = []
        if root.exists():
            folders = [d for d in root.iterdir() if (d / "clips.json").exists()]
        folders.sort(key=lambda d: (d / "clips.json").stat().st_mtime, reverse=True)
        self._result_folders = {d.name: d for d in folders}
        if not folders:
            self.result_choice.configure(values=["—"])
            self.result_choice.set("—")
            self._clear_results()
            ctk.CTkLabel(self.results_frame, text="Zatím nejsou žádné klipy. Vytvoř je na první stránce.",
                         font=fnt(12), text_color=MUTED).pack(anchor="w", pady=20)
            return
        names = list(self._result_folders.keys())
        self.result_choice.configure(values=names)
        current = self.result_choice.get()
        target = current if current in names else names[0]
        self.result_choice.set(target)
        self.load_results(target)

    def _clear_results(self) -> None:
        for w in self.results_frame.winfo_children():
            w.destroy()

    def load_results(self, name: str) -> None:
        self._clear_results()
        folder = self._result_folders.get(name)
        if not folder:
            return
        data = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
        clips = sorted(data.get("clips", []), key=lambda c: c.get("score", 0), reverse=True)
        if not clips:
            ctk.CTkLabel(self.results_frame, text="Žádný klip nedosáhl prahu hodnocení.",
                         font=fnt(12), text_color=MUTED).pack(anchor="w", pady=20)
            return
        for clip in clips:
            self._result_card(folder, clip)

    def _result_card(self, folder: Path, clip: dict) -> None:
        card = self._card(self.results_frame)
        card.pack(fill="x", pady=6, padx=2)
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=16)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=clip.get("title", "klip"), font=fnt(15, True), text_color=TEXT,
                     anchor="w", justify="left", wraplength=640).pack(anchor="w")
        length = clip["end"] - clip["start"]
        ctk.CTkLabel(left, text=f"Ve streamu {clip['start']:.0f}s – {clip['end']:.0f}s  ·  "
                                f"{length:.0f} s  ·  {clip.get('file', '')}",
                     font=fnt(11), text_color=MUTED, anchor="w").pack(anchor="w", pady=(2, 8))
        if clip.get("description"):
            ctk.CTkLabel(left, text=clip["description"], font=fnt(12), text_color="#B7BBC3",
                         anchor="w", justify="left", wraplength=640).pack(anchor="w")
        if clip.get("hashtags"):
            ctk.CTkLabel(left, text=" ".join(clip["hashtags"]), font=fnt(11), text_color=ORANGE_LIGHT,
                         anchor="w", justify="left", wraplength=640).pack(anchor="w", pady=(6, 0))

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="right", padx=(16, 0))
        score = float(clip.get("score", 0))
        ctk.CTkLabel(right, text=f"{score:.0f}", font=fnt(30, True), text_color=score_color(score)
                     ).pack(anchor="e")
        ctk.CTkLabel(right, text="/ 100 hodnocení", font=fnt(10), text_color=MUTED).pack(anchor="e")

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.pack(anchor="e", pady=(10, 0))
        file_path = folder / clip.get("file", "")
        ctk.CTkButton(btns, text="Přehrát", width=90, height=30, corner_radius=8, fg_color=ORANGE,
                      hover_color=ORANGE_LIGHT, font=fnt(11, True),
                      command=lambda p=file_path: open_path(p)).pack(side="left")
        ctk.CTkButton(btns, text="Složka", width=80, height=30, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=fnt(11),
                      command=lambda p=folder: open_path(p)).pack(side="left", padx=(6, 0))
        ctk.CTkButton(btns, text="Kopírovat", width=90, height=30, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=fnt(11),
                      command=lambda c=clip: self._copy_meta(c)).pack(side="left", padx=(6, 0))
        ctk.CTkButton(btns, text="Upravit", width=90, height=30, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=ORANGE_LIGHT, font=fnt(11, True),
                      command=lambda f=folder, n=clip.get("file", ""): self.open_editor(f, n)
                      ).pack(side="left", padx=(6, 0))

        # Hodnocení pro učení AI (👍 / 👎)
        fb = ctk.CTkFrame(right, fg_color="transparent")
        fb.pack(anchor="e", pady=(8, 0))
        ctk.CTkButton(fb, text="👍 Líbí se", width=90, height=28, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=GREEN, font=fnt(11),
                      command=lambda c=clip, f=folder, r=fb: self._feedback(f, c, True, r)
                      ).pack(side="left")
        ctk.CTkButton(fb, text="👎 Nelíbí", width=90, height=28, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=RED, font=fnt(11),
                      command=lambda c=clip, f=folder, r=fb: self._feedback(f, c, False, r)
                      ).pack(side="left", padx=(6, 0))

    def _copy_meta(self, clip: dict) -> None:
        text = f"{clip.get('title', '')}\n\n{clip.get('description', '')}\n\n{' '.join(clip.get('hashtags', []))}"
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="Titulek, popis a hashtagy zkopírovány.", text_color=GREEN)

    # ------------------------------------------------------------ 3. nastavení

    def _build_settings_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.pages["settings"] = page
        self._title(page, "Nastavení",
                    "Všechno, co ovlivňuje výběr, střih a titulky. Každé nastavení má popis. "
                    "Po uložení se projeví při dalším zpracování.")

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(bar, text="Uložit nastavení", height=36, corner_radius=9, fg_color=ORANGE,
                      hover_color=ORANGE_LIGHT, font=fnt(12, True), command=self.save_settings
                      ).pack(side="left")
        ctk.CTkButton(bar, text="Obnovit výchozí", height=36, corner_radius=9, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=fnt(12),
                      command=self.reset_settings).pack(side="left", padx=(10, 0))
        self.settings_status = ctk.CTkLabel(bar, text="", font=fnt(11), text_color=MUTED)
        self.settings_status.pack(side="left", padx=16)

        scroll = ctk.CTkScrollableFrame(page, fg_color=BG, corner_radius=0)
        scroll.pack(fill="both", expand=True)

        for sec, title, fields in SECTIONS:
            ctk.CTkLabel(scroll, text=title.upper(), font=fnt(12, True), text_color=ORANGE
                         ).pack(anchor="w", pady=(18, 6), padx=4)
            for f in fields:
                if f.show:
                    self._setting_row(scroll, sec, f)

        yt_card = self._card(scroll)
        yt_card.pack(fill="x", pady=(18, 4), padx=2)
        ctk.CTkLabel(yt_card, text="Účet YouTube", font=fnt(12, True), text_color=TEXT
                     ).pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(yt_card, text="Nejdřív vlož soubor client_secret a ulož nastavení. "
                                   "Pak připoj účet. Token se ukládá jen do této složky.",
                     font=fnt(10), text_color=MUTED, wraplength=760, justify="left"
                     ).pack(anchor="w", padx=16, pady=(2, 8))
        yt_row = ctk.CTkFrame(yt_card, fg_color="transparent")
        yt_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(yt_row, text="Připojit účet", height=34, corner_radius=8, fg_color=ORANGE,
                      hover_color=ORANGE_LIGHT, text_color="white", font=fnt(12, True),
                      command=self.connect_youtube).pack(side="left")
        ctk.CTkButton(yt_row, text="Odpojit", height=34, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=fnt(12),
                      command=self.disconnect_youtube).pack(side="left", padx=8)
        self.yt_status = ctk.CTkLabel(
            yt_row, text="Připojeno" if youtube.is_connected(ROOT) else "Nepřipojeno",
            font=fnt(11), text_color=MUTED)
        self.yt_status.pack(side="left", padx=12)

        self._populate_settings(self.cfg)

    def _setting_row(self, parent, sec: str, f) -> None:
        row = self._card(parent)
        row.pack(fill="x", pady=4, padx=2)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        text_col = ctk.CTkFrame(inner, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=f.label, font=fnt(12, True), text_color=TEXT,
                     anchor="w").pack(anchor="w")
        if f.desc:
            ctk.CTkLabel(text_col, text=f.desc, font=fnt(10), text_color=MUTED, anchor="w",
                         justify="left", wraplength=620).pack(anchor="w", pady=(2, 0))

        ctrl = ctk.CTkFrame(inner, fg_color="transparent")
        ctrl.pack(side="right", padx=(16, 0))

        if f.kind == "bool":
            var = ctk.BooleanVar()
            ctk.CTkSwitch(ctrl, text="", variable=var, progress_color=ORANGE, width=46
                          ).pack()
            self.setting_widgets[(sec, f.key)] = ("bool", var)
        elif f.kind == "choice":
            om = ctk.CTkOptionMenu(ctrl, values=f.options, width=200, height=32, corner_radius=8,
                                   fg_color=INPUT, button_color=BORDER,
                                   button_hover_color="#2A2E37", dropdown_fg_color=PANEL,
                                   text_color=TEXT, font=fnt(12))
            om.pack()
            self.setting_widgets[(sec, f.key)] = ("choice", om)
        elif f.kind == "path":
            var = ctk.StringVar()
            entry = ctk.CTkEntry(ctrl, textvariable=var, width=260, height=32, corner_radius=8,
                                 fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=fnt(11))
            entry.pack(side="left")
            ctk.CTkButton(ctrl, text="…", width=34, height=32, corner_radius=8, fg_color=INPUT,
                          hover_color=BORDER, text_color=TEXT, font=fnt(12),
                          command=lambda v=var, k=f.key: self._browse(v, k)).pack(side="left", padx=(6, 0))
            self.setting_widgets[(sec, f.key)] = ("path", var)
        else:
            var = ctk.StringVar()
            width = 200 if f.kind in ("int", "float") else 280
            ctk.CTkEntry(ctrl, textvariable=var, width=width, height=32, corner_radius=8,
                         fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=fnt(12),
                         justify="right" if f.kind in ("int", "float") else "left").pack()
            self.setting_widgets[(sec, f.key)] = (f.kind, var)

    def _browse(self, var: ctk.StringVar, key: str) -> None:
        if "dir" in key or "folder" in key:
            path = filedialog.askdirectory(initialdir=str(ROOT))
        else:
            path = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("Vše", "*.*")])
        if path:
            var.set(path)

    def _populate_settings(self, values: dict) -> None:
        for sec, _title, fields in SECTIONS:
            for f in fields:
                if (sec, f.key) not in self.setting_widgets:
                    continue
                kind, widget = self.setting_widgets[(sec, f.key)]
                value = values[sec][f.key]
                if kind == "bool":
                    widget.set(bool(value))
                elif kind == "choice":
                    widget.set(str(value))
                else:
                    widget.set(str(value))

    def save_settings(self) -> None:
        new = copy.deepcopy(self.cfg)  # skrytá (automatická) nastavení zůstanou beze změny
        for sec, _title, fields in SECTIONS:
            for f in fields:
                if (sec, f.key) not in self.setting_widgets:
                    continue
                kind, widget = self.setting_widgets[(sec, f.key)]
                raw = widget.get() if kind != "bool" else widget.get()
                try:
                    new[sec][f.key] = _coerce(f, raw)
                except (TypeError, ValueError):
                    self.settings_status.configure(
                        text=f"Chybná hodnota: {f.label}", text_color=RED)
                    return
        save(new)
        self.cfg = new
        self.captions_var.set(bool(new["captions"]["enabled"]))
        self.settings_status.configure(text="Uloženo", text_color=GREEN)

    def reset_settings(self) -> None:
        if messagebox.askyesno("Obnovit výchozí", "Vrátit všechna nastavení na výchozí hodnoty?"):
            self._populate_settings(default_settings())
            self.settings_status.configure(text="Výchozí hodnoty načteny, zkontroluj a ulož.",
                                           text_color=YELLOW)

    # ------------------------------------------------------------ 4. cache

    def _build_cache_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.pages["cache"] = page
        self._title(page, "Cache a úklid",
                    "Stažená videa, přepisy a výběry AI se ukládají do pracovní složky. "
                    "Tady je můžeš vyčistit, nebo nechat úklid běžet podle nastavení.")

        card = self._card(page)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        self.cache_labels: dict[str, ctk.CTkLabel] = {}
        for key, label in [("downloads", "Stažená videa"), ("transcripts", "Přepisy"),
                           ("selections", "Výběr AI a klipy"), ("total", "Celkem")]:
            row = ctk.CTkFrame(inner, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label, font=fnt(12, key == "total"), text_color=TEXT,
                         width=260, anchor="w").pack(side="left")
            lbl = ctk.CTkLabel(row, text="…", font=fnt(12, key == "total"), text_color=ORANGE_LIGHT)
            lbl.pack(side="left")
            self.cache_labels[key] = lbl

        self.cache_limit_label = ctk.CTkLabel(inner, text="", font=fnt(11), text_color=MUTED,
                                              anchor="w")
        self.cache_limit_label.pack(anchor="w", pady=(8, 0))

        buttons = ctk.CTkFrame(page, fg_color="transparent")
        buttons.pack(fill="x", pady=16)
        actions = [
            ("Vyčistit stažená videa", "downloads", INPUT),
            ("Vyčistit přepisy", "transcripts", INPUT),
            ("Vyčistit výběr AI", "selections", INPUT),
            ("Vyčistit vše v cache", "all", "#3A1717"),
        ]
        for text, what, color in actions:
            ctk.CTkButton(buttons, text=text, height=38, corner_radius=9, fg_color=color,
                          hover_color=BORDER, text_color=TEXT, font=fnt(12),
                          command=lambda w=what: self.clean(w)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(buttons, text="Spustit úklid podle nastavení", height=38, corner_radius=9,
                      fg_color=ORANGE, hover_color=ORANGE_LIGHT, font=fnt(12, True),
                      command=self.run_auto_clean).pack(side="left", padx=(8, 0))

        self.cache_status = ctk.CTkLabel(page, text="", font=fnt(11), text_color=MUTED, anchor="w")
        self.cache_status.pack(fill="x")

    def refresh_cache(self) -> None:
        rep = cache_report(self.cfg)
        for key, lbl in self.cache_labels.items():
            lbl.configure(text=fmt_size(rep[key]))
        c = self.cfg["cache"]
        self.cache_limit_label.configure(
            text=f"Limit cache: {c['max_cache_gb']} GB · mazat starší než {c['auto_clean_days']} dní "
                 f"(0 = nemazat)")

    def clean(self, what: str) -> None:
        names = {"downloads": "stažená videa", "transcripts": "přepisy",
                 "selections": "výběr AI", "all": "všechnu cache"}
        if not messagebox.askyesno("Vyčistit", f"Opravdu smazat {names[what]}?"):
            return
        freed = clean_cache(self.cfg, what, Reporter(log=lambda m: None))
        self.cache_status.configure(text=f"Uvolněno {fmt_size(freed)}", text_color=GREEN)
        self.refresh_cache()

    def run_auto_clean(self) -> None:
        logs: list[str] = []
        auto_clean(self.cfg, Reporter(log=logs.append))
        self.cache_status.configure(
            text=(logs[-1] if logs else "Nic nebylo potřeba mazat."), text_color=GREEN)
        self.refresh_cache()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()

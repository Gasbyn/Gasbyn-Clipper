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
from core import (Reporter, Cancelled, run_job, clean_cache, cache_report,
                  auto_clean, check_environment, load_or_default, save, ROOT)
from schema import SECTIONS, default_settings, _coerce

# barvy z GasbynOptimizeru (MainWindow.xaml)
BG = "#08090B"
PANEL = "#121419"
INPUT = "#17191E"
BORDER = "#24272E"
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

        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True, padx=28, pady=24)

        self._build_create_page()
        self._build_results_page()
        self._build_settings_page()
        self._build_cache_page()

        self.show("create")
        self.after(100, self._poll_events)

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

        card = self._card(page)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=20)

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.url_var = ctk.StringVar(value=self.cfg["source"]["url"])
        ctk.CTkEntry(row, textvariable=self.url_var, height=40, corner_radius=9,
                     fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=fnt(12),
                     placeholder_text="https://kick.com/…/videos/…  nebo  C:\\videa\\stream.mp4"
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

        self.progress = ctk.CTkProgressBar(inner, progress_color=ORANGE, fg_color=INPUT,
                                           height=8, corner_radius=4)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(18, 6))
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
        src = self.url_var.get().strip()
        if not src:
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
                  "captions_override": bool(self.captions_var.get())}
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress.set(0)
        self.status.configure(text="Spouštím…", text_color=MUTED)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._work, args=(src, cfg, rep, kwargs),
                                       daemon=True)
        self.worker.start()

    def _work(self, src: str, cfg: dict, rep: Reporter, kwargs: dict) -> None:
        try:
            result = run_job(src, cfg, rep, **kwargs)
            self.events.put(("done", result))
        except Cancelled as exc:
            self.events.put(("cancelled", str(exc)))
        except Exception as exc:  # noqa: BLE001 - chceme ukázat chybu uživateli
            self.events.put(("error", f"{exc}"))
            self.events.put(("log", traceback.format_exc()))

    def cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            self.status.configure(text="Ruším…", text_color=YELLOW)

    def _finish_worker_ui(self) -> None:
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self._append_log(ev[1])
                elif kind == "progress":
                    self.progress.set(ev[1])
                    if ev[2]:
                        self.status.configure(text=ev[2], text_color=MUTED)
                elif kind == "done":
                    self._finish_worker_ui()
                    result = ev[1]
                    n = len(result["clips"])
                    self.progress.set(1)
                    self.status.configure(text=f"Hotovo: {n} klipů", text_color=GREEN)
                    self._selected_folder = result["out_dir"]
                    if self.cfg["output"]["open_folder_after"]:
                        open_path(result["out_dir"])
                elif kind == "cancelled":
                    self._finish_worker_ui()
                    self.status.configure(text=ev[1], text_color=YELLOW)
                elif kind == "error":
                    self._finish_worker_ui()
                    self.status.configure(text=f"Chyba: {ev[1]}", text_color=RED)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

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
                self._setting_row(scroll, sec, f)

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
                kind, widget = self.setting_widgets[(sec, f.key)]
                value = values[sec][f.key]
                if kind == "bool":
                    widget.set(bool(value))
                elif kind == "choice":
                    widget.set(str(value))
                else:
                    widget.set(str(value))

    def save_settings(self) -> None:
        new = copy.deepcopy(default_settings())
        for sec, _title, fields in SECTIONS:
            for f in fields:
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

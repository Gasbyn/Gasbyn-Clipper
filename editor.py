"""Klipový editor v duchu CapCutu: časová osa s uchyty pro oříznutí, úprava titulků,
přerenderování a nahrání na YouTube.

Omezení této verze: náhled se přehraje ve výchozím přehrávači (ne uvnitř aplikace),
oříznout jde jen zkrátit, ne prodloužit nad původní okno klipu.
"""

from __future__ import annotations

import copy
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable

import customtkinter as ctk

import youtube
from core import (Reporter, Cancelled, ROOT, get_source, parse_srt, render_clip)

BG = "#08090B"
PANEL = "#121419"
INPUT = "#17191E"
BORDER = "#24272E"
TEXT = "#F4F4F5"
MUTED = "#858A94"
ORANGE = "#FF6A00"
ORANGE_LIGHT = "#FF9A52"
ORANGE_SOFT = "#21150E"
GREEN = "#48D597"
RED = "#F87171"
BLOCK = "#2A2E37"
FONT = "Segoe UI"

PAD = 14          # vnitřní okraj časové osy v px
TRACK_H = 92


def _fnt(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


class EditorPage(ctk.CTkFrame):
    HANDLE_PX = 9
    MIN_LEN = 1.0

    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.folder: Path | None = None
        self.file_name: str = ""
        self.manifest: dict = {}
        self.clip: dict | None = None
        self.items: list[dict] = []
        self.L = 1.0
        self.tr_start = 0.0
        self.tr_end = 1.0
        self.selected: int | None = None
        self.drag: str | None = None
        self.canvas_w = 800
        self.busy = False
        self.rows: list[dict] = []
        self.q: queue.Queue = queue.Queue()
        self._build()
        self.after(100, self._poll)

    # ------------------------------------------------------------ rozložení

    def _build(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(top, text="← Zpět na klipy", width=140, height=36, corner_radius=9,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=_fnt(12),
                      command=lambda: self.app.show("results")).pack(side="left")
        self.heading = ctk.CTkLabel(top, text="Editor klipu", font=_fnt(18, True), text_color=TEXT)
        self.heading.pack(side="left", padx=18)
        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.pack(side="right")
        ctk.CTkButton(btns, text="Přehrát", width=90, height=36, corner_radius=9, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=_fnt(12),
                      command=self.play).pack(side="left")
        ctk.CTkButton(btns, text="Nahrát na YouTube", width=150, height=36, corner_radius=9,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=_fnt(12),
                      command=self.upload_youtube).pack(side="left", padx=(8, 0))
        ctk.CTkButton(btns, text="Uložit a přerenderovat", width=190, height=36, corner_radius=9,
                      fg_color=ORANGE, hover_color=ORANGE_LIGHT, text_color="white",
                      font=_fnt(12, True), command=self.save_and_render).pack(side="left", padx=(8, 0))

        self.status = ctk.CTkLabel(self, text="", font=_fnt(11), text_color=MUTED, anchor="w")
        self.status.pack(fill="x")
        self.progress = ctk.CTkProgressBar(self, progress_color=ORANGE, fg_color=INPUT, height=6,
                                           corner_radius=3)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(4, 12))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)

        # levý sloupec: metadata
        left = ctk.CTkFrame(body, fg_color=PANEL, border_color=BORDER, border_width=1,
                            corner_radius=14, width=320)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        inner = ctk.CTkFrame(left, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(inner, text="Název", font=_fnt(11, True), text_color=MUTED).pack(anchor="w")
        self.title_var = ctk.StringVar()
        ctk.CTkEntry(inner, textvariable=self.title_var, height=34, corner_radius=8,
                     fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=_fnt(12)
                     ).pack(fill="x", pady=(4, 12))
        ctk.CTkLabel(inner, text="Popis", font=_fnt(11, True), text_color=MUTED).pack(anchor="w")
        self.desc_box = ctk.CTkTextbox(inner, height=120, corner_radius=8, fg_color=INPUT,
                                       border_color=BORDER, border_width=1, text_color=TEXT,
                                       font=_fnt(12))
        self.desc_box.pack(fill="x", pady=(4, 12))
        ctk.CTkLabel(inner, text="Hashtagy (oddělené mezerou)", font=_fnt(11, True),
                     text_color=MUTED).pack(anchor="w")
        self.tags_var = ctk.StringVar()
        ctk.CTkEntry(inner, textvariable=self.tags_var, height=34, corner_radius=8,
                     fg_color=INPUT, border_color=BORDER, text_color=TEXT, font=_fnt(12)
                     ).pack(fill="x", pady=(4, 14))
        self.trim_label = ctk.CTkLabel(inner, text="", font=_fnt(11), text_color=ORANGE_LIGHT,
                                       justify="left", anchor="w")
        self.trim_label.pack(anchor="w")
        ctk.CTkButton(inner, text="Vrátit původní délku", height=32, corner_radius=8,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=_fnt(11),
                      command=self.reset_trim).pack(fill="x", pady=(10, 0))

        # pravý sloupec: časová osa a titulky
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        track_card = ctk.CTkFrame(right, fg_color=PANEL, border_color=BORDER, border_width=1,
                                  corner_radius=14)
        track_card.pack(fill="x")
        ctk.CTkLabel(track_card, text="Časová osa  (táhni oranžové uchyty pro oříznutí, "
                                      "klikni na titulek pro úpravu)",
                     font=_fnt(11), text_color=MUTED).pack(anchor="w", padx=14, pady=(10, 4))
        self.canvas = tk.Canvas(track_card, height=TRACK_H, bg=PANEL, highlightthickness=0,
                                cursor="hand2")
        self.canvas.pack(fill="x", padx=14, pady=(0, 12))
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        caps_head = ctk.CTkFrame(right, fg_color="transparent")
        caps_head.pack(fill="x", pady=(14, 6))
        ctk.CTkLabel(caps_head, text="TITULKY", font=_fnt(12, True), text_color=ORANGE
                     ).pack(side="left")
        ctk.CTkButton(caps_head, text="+ Přidat titulek", height=30, width=140, corner_radius=8,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=_fnt(11),
                      command=self.add_caption).pack(side="right")

        self.rows_frame = ctk.CTkScrollableFrame(right, fg_color=BG, corner_radius=0)
        self.rows_frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------ načtení

    def load(self, folder: Path, file_name: str) -> bool:
        data = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
        clip = next((c for c in data.get("clips", []) if c.get("file") == file_name), None)
        if clip is None:
            self.status.configure(text="Klip se v souboru clips.json nenašel.", text_color=RED)
            return False
        self.folder, self.file_name, self.manifest, self.clip = folder, file_name, data, clip
        self.L = max(self.MIN_LEN, float(clip["end"]) - float(clip["start"]))
        self.tr_start, self.tr_end = 0.0, self.L
        self.items = [{"start": a, "end": b, "text": t}
                      for a, b, t in parse_srt(folder / (Path(file_name).stem + ".srt"))]
        self.heading.configure(text=f"Editor: {clip.get('title', 'klip')}")
        self.title_var.set(clip.get("title", ""))
        self.desc_box.delete("1.0", "end")
        self.desc_box.insert("1.0", clip.get("description", ""))
        self.tags_var.set(" ".join(clip.get("hashtags", [])))
        self.selected = None
        self._rebuild_rows()
        self._redraw()
        self.status.configure(text="Uprav a ulož. Přerenderování chvíli trvá.", text_color=MUTED)
        return True

    # ------------------------------------------------------------ časová osa

    def _on_resize(self, event) -> None:
        self.canvas_w = max(200, event.width)
        self._redraw()

    def _x(self, t: float) -> float:
        usable = self.canvas_w - 2 * PAD
        return PAD + (t / self.L) * usable

    def _t(self, x: float) -> float:
        usable = max(1, self.canvas_w - 2 * PAD)
        return max(0.0, min(self.L, (x - PAD) / usable * self.L))

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        top, bottom = 10, TRACK_H - 26
        # celé okno klipu
        c.create_rectangle(PAD, top, self.canvas_w - PAD, bottom, fill=INPUT, outline=BORDER)
        # zahozená část (mimo oříznutí)
        xs, xe = self._x(self.tr_start), self._x(self.tr_end)
        c.create_rectangle(PAD, top, xs, bottom, fill="#0D0F13", outline="")
        c.create_rectangle(xe, top, self.canvas_w - PAD, bottom, fill="#0D0F13", outline="")
        # aktivní část
        c.create_rectangle(xs, top, xe, bottom, fill=ORANGE_SOFT, outline=ORANGE)
        # titulky jako bloky
        for i, it in enumerate(self.items):
            x1, x2 = self._x(it["start"]), self._x(it["end"])
            sel = i == self.selected
            c.create_rectangle(x1, top + 6, max(x1 + 2, x2), bottom - 6,
                               fill=ORANGE if sel else BLOCK, outline="")
            label = it["text"][:18]
            if x2 - x1 > 60:
                c.create_text(x1 + 6, (top + bottom) / 2, text=label, anchor="w",
                              fill="white" if sel else TEXT, font=(FONT, 9))
        # uchyty
        for x in (xs, xe):
            c.create_rectangle(x - 4, top - 4, x + 4, bottom + 4, fill=ORANGE, outline="")
        # časová stupnice
        c.create_text(PAD, TRACK_H - 10, text="0 s", anchor="w", fill=MUTED, font=(FONT, 9))
        c.create_text(self.canvas_w - PAD, TRACK_H - 10, text=f"{self.L:.0f} s", anchor="e",
                      fill=MUTED, font=(FONT, 9))
        self._update_trim_label()

    def _update_trim_label(self) -> None:
        if self.clip is None:
            return
        dur = self.tr_end - self.tr_start
        self.trim_label.configure(
            text=f"Začátek: {self.tr_start:.1f} s   Konec: {self.tr_end:.1f} s\n"
                 f"Délka po oříznutí: {dur:.1f} s")

    def _on_press(self, e) -> None:
        if self.clip is None:
            return
        if abs(e.x - self._x(self.tr_start)) <= self.HANDLE_PX:
            self.drag = "start"
        elif abs(e.x - self._x(self.tr_end)) <= self.HANDLE_PX:
            self.drag = "end"
        else:
            self.drag = None
            self.selected = self._item_at(e.x)
            self._redraw()
            self._highlight_row()

    def _on_drag(self, e) -> None:
        if self.drag is None:
            return
        t = self._t(e.x)
        if self.drag == "start":
            self.tr_start = max(0.0, min(t, self.tr_end - self.MIN_LEN))
        else:
            self.tr_end = min(self.L, max(t, self.tr_start + self.MIN_LEN))
        self._redraw()

    def _on_release(self, _e) -> None:
        self.drag = None

    def _item_at(self, x: float) -> int | None:
        t = self._t(x)
        for i, it in enumerate(self.items):
            if it["start"] <= t <= it["end"]:
                return i
        return None

    def reset_trim(self) -> None:
        self.tr_start, self.tr_end = 0.0, self.L
        self._redraw()

    # ------------------------------------------------------------ řádky titulků

    def _rebuild_rows(self) -> None:
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.rows = []
        for idx, it in enumerate(self.items):
            self._add_row(idx, it)
        if not self.items:
            ctk.CTkLabel(self.rows_frame, text="Tento klip nemá titulky.", font=_fnt(12),
                         text_color=MUTED).pack(anchor="w", pady=10)

    def _add_row(self, idx: int, it: dict) -> None:
        row = ctk.CTkFrame(self.rows_frame, fg_color=PANEL, border_color=BORDER, border_width=1,
                           corner_radius=10)
        row.pack(fill="x", pady=3, padx=2)
        s_var = ctk.StringVar(value=f"{it['start']:.2f}")
        e_var = ctk.StringVar(value=f"{it['end']:.2f}")
        t_var = ctk.StringVar(value=it["text"])
        ctk.CTkEntry(row, textvariable=s_var, width=70, height=30, corner_radius=7, fg_color=INPUT,
                     border_color=BORDER, text_color=TEXT, font=_fnt(11), justify="right"
                     ).pack(side="left", padx=(10, 4), pady=8)
        ctk.CTkLabel(row, text="–", text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row, textvariable=e_var, width=70, height=30, corner_radius=7, fg_color=INPUT,
                     border_color=BORDER, text_color=TEXT, font=_fnt(11), justify="right"
                     ).pack(side="left", padx=(4, 8), pady=8)
        ctk.CTkEntry(row, textvariable=t_var, height=30, corner_radius=7, fg_color=INPUT,
                     border_color=BORDER, text_color=TEXT, font=_fnt(12)
                     ).pack(side="left", fill="x", expand=True, padx=4, pady=8)
        ctk.CTkButton(row, text="✕", width=30, height=30, corner_radius=7, fg_color=INPUT,
                      hover_color="#3A1717", text_color=RED, font=_fnt(12),
                      command=lambda i=idx: self._delete_row(i)).pack(side="left", padx=(4, 10))
        self.rows.append({"start": s_var, "end": e_var, "text": t_var, "frame": row})

    def _highlight_row(self) -> None:
        for i, r in enumerate(self.rows):
            r["frame"].configure(border_color=ORANGE if i == self.selected else BORDER)

    def _collect_items(self) -> list[dict]:
        out = []
        for i, r in enumerate(self.rows, 1):
            try:
                a = float(r["start"].get().replace(",", "."))
                b = float(r["end"].get().replace(",", "."))
            except ValueError as exc:
                raise ValueError(f"Titulek {i}: čas musí být číslo.") from exc
            text = r["text"].get().strip()
            if not text:
                continue
            if b <= a:
                raise ValueError(f"Titulek {i}: konec musí být po začátku.")
            out.append({"start": a, "end": b, "text": text})
        return out

    def _delete_row(self, idx: int) -> None:
        try:
            current = self._collect_items()
        except ValueError:
            current = self.items
        self.items = [it for j, it in enumerate(current) if j != idx]
        self.selected = None
        self._rebuild_rows()
        self._redraw()

    def add_caption(self) -> None:
        if self.clip is None:
            return
        try:
            self.items = self._collect_items()
        except ValueError as exc:
            self._set_status(str(exc), RED)
            return
        start = self.tr_start
        self.items.append({"start": round(start, 2), "end": round(min(self.tr_end, start + 2.0), 2),
                           "text": "Nový titulek"})
        self.items.sort(key=lambda it: it["start"])
        self._rebuild_rows()
        self._redraw()

    # ------------------------------------------------------------ stav a úlohy

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self.status.configure(text=text, text_color=color)

    def play(self) -> None:
        if self.folder and self.file_name:
            path = self.folder / self.file_name
            if path.exists():
                self.app.open_path(path)
            else:
                self._set_status("Soubor klipu neexistuje.", RED)

    def _run(self, fn: Callable, label: str, on_done: Callable) -> None:
        if self.busy:
            return
        self.busy = True
        self.progress.set(0)
        self._set_status(label, MUTED)

        def target() -> None:
            rep = Reporter(log=lambda m: self.q.put(("log", m)),
                           progress=lambda f, t: self.q.put(("progress", f, t)))
            try:
                result = fn(rep)
                self.q.put(("done", result, on_done))
            except Cancelled:
                self.q.put(("error", "Zrušeno."))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", str(exc)))

        threading.Thread(target=target, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                ev = self.q.get_nowait()
                if ev[0] == "log":
                    self._set_status(ev[1], MUTED)
                elif ev[0] == "progress":
                    self.progress.set(ev[1])
                    if ev[2]:
                        self._set_status(ev[2], MUTED)
                elif ev[0] == "done":
                    self.busy = False
                    self.progress.set(1)
                    ev[2](ev[1])
                elif ev[0] == "error":
                    self.busy = False
                    self._set_status(f"Chyba: {ev[1]}", RED)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ------------------------------------------------------------ uložení a přerenderování

    def save_and_render(self) -> None:
        if self.clip is None:
            return
        try:
            rows = self._collect_items()
        except ValueError as exc:
            self._set_status(str(exc), RED)
            return

        ts, te = self.tr_start, self.tr_end
        items = []
        for it in rows:
            a, b = max(it["start"], ts), min(it["end"], te)
            if b - a >= 0.2:
                items.append((a - ts, b - ts, it["text"]))

        tags = [t if t.startswith("#") else f"#{t}" for t in self.tags_var.get().split() if t]
        new_clip = dict(self.clip)
        new_clip.update({
            "start": round(float(self.clip["start"]) + ts, 2),
            "end": round(float(self.clip["start"]) + te, 2),
            "title": self.title_var.get().strip() or self.clip.get("title", "klip"),
            "description": self.desc_box.get("1.0", "end").strip(),
            "hashtags": tags,
        })
        cfg = copy.deepcopy(self.app.cfg)
        folder, file_name, source = self.folder, self.file_name, self.manifest.get("source", "")

        def job(rep: Reporter) -> dict:
            video, _vid, downloaded = get_source(source, cfg, rep)
            render_clip(video, [], new_clip, folder, cfg, 0, rep,
                        items_override=items, name_override=Path(file_name).stem)
            data = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
            for c in data.get("clips", []):
                if c.get("file") == file_name:
                    c.update({k: new_clip[k] for k in
                              ("start", "end", "title", "description", "hashtags")})
            (folder / "clips.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
            if downloaded and not cfg["download"]["keep_source"]:
                (ROOT / cfg["cache"]["work_dir"] / "downloads" / f"{_vid}.mp4").unlink(missing_ok=True)
            return new_clip

        def done(result: dict) -> None:
            self.load(folder, file_name)
            self._set_status("Klip je přerenderovaný.", GREEN)

        self._run(job, "Přerenderovávám klip…", done)

    def upload_youtube(self) -> None:
        if self.clip is None:
            return
        cfg = self.app.cfg["youtube"]
        secret = Path(cfg["client_secret_file"]) if cfg["client_secret_file"] else None
        if not secret or not secret.exists():
            self._set_status("Nejdřív v Nastavení vyber soubor client_secret (YouTube).", RED)
            return
        creds = youtube.load_credentials(secret, ROOT)
        if creds is None:
            self._set_status("Účet YouTube není připojený. Připoj ho v Nastavení.", RED)
            return
        path = self.folder / self.file_name
        title = self.title_var.get().strip() or self.clip.get("title", "klip")
        desc = self.desc_box.get("1.0", "end").strip()
        tags = [t for t in self.tags_var.get().split() if t]
        privacy = cfg["default_privacy"]

        def job(rep: Reporter) -> str:
            rep.log(f"Nahrávám na YouTube ({privacy})…")
            vid = youtube.upload(path, title, desc, tags, privacy, creds,
                                 progress=lambda p: rep.progress(p, "Nahrávám na YouTube"))
            return f"https://youtu.be/{vid}"

        def done(url: str) -> None:
            self._set_status(f"Nahráno: {url}", GREEN)
            self.app.clipboard_clear()
            self.app.clipboard_append(url)

        self._run(job, "Nahrávám na YouTube…", done)

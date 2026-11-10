"""Loadout pro 9:16: z jednoho snímku VODu vyřízneš až 5 záběrů (kamera, hra, ...),
každý přesuneš a zvětšíš na místo ve vertikálním klipu, můžeš přidat fotky a animace.

Loadouty se ukládají do knihovny a poslední použitý se nabídne u dalšího VODu.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageTk

from core import (EFFECT_KINDS, LOADOUT_MAX_VIEWS, clean_loadout, clean_subtitles, list_loadouts,
                  load_loadout, save_loadout)

BG = "#08090B"
PANEL = "#121419"
INPUT = "#17191E"
BORDER = "#24272E"
TEXT = "#F4F4F5"
MUTED = "#858A94"
ORANGE = "#FF6A00"
ORANGE_LIGHT = "#FF9A52"
GREEN = "#48D597"
RED = "#F87171"
BLOCK = "#2A2E37"
FONT = "Segoe UI"

VIEW_COLORS = ["#FF6A00", "#48D597", "#60A5FA", "#FBBF24", "#F472B6"]
PHOTO_COLOR = "#E879F9"
SUBTITLE_SAMPLE = "Ukázka titulků"
ANIM_LABELS = {"none": "Žádná", "fade": "Fade in", "unblur": "Unblur in",
               "shake": "Třes na začátku"}
ANIM_KEYS = {v: k for k, v in ANIM_LABELS.items()}
RESAMPLE = Image.Resampling.LANCZOS


def _fnt(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _inside(rect: list[float], fx: float, fy: float) -> bool:
    return rect[0] <= fx <= rect[0] + rect[2] and rect[1] <= fy <= rect[1] + rect[3]


class LoadoutPage(ctk.CTkFrame):
    FW, FH = 480, 270   # náhled rámce z videa (16:9)
    PW, PH = 240, 427   # výsledek 9:16

    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.prep: dict | None = None
        self.frame_img: Image.Image | None = None
        self._frame_photo = None
        self._prev_photo = None
        self._photo_cache: dict[str, Image.Image | None] = {}
        self.lo: dict = {"name": "nový", "background": "#000000", "views": [], "photos": [],
                             "subtitles": {"x": 0.5, "y": 0.8, "size": 60}}
        self.sel: tuple[str, int] | None = None
        self.drag: tuple | None = None
        self._loading = False
        self._layer_map: dict[str, tuple[str, int]] = {}
        self.sliders: dict[str, ctk.CTkSlider] = {}
        self.vars: dict[str, ctk.DoubleVar] = {}
        self._fmts: dict[str, object] = {}
        self._build()

    # ------------------------------------------------------------ rozložení

    def _build(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        head = ctk.CTkFrame(top, fg_color="transparent")
        head.pack(side="left")
        ctk.CTkLabel(head, text="Loadout 9:16", font=_fnt(22, True), text_color=TEXT).pack(anchor="w")
        self.sub = ctk.CTkLabel(head, text="", font=_fnt(12), text_color=MUTED)
        self.sub.pack(anchor="w")
        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.pack(side="right")
        ctk.CTkButton(btns, text="Zpět", height=36, corner_radius=9, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=_fnt(12),
                      command=lambda: self.app.show("create")).pack(side="left")
        ctk.CTkButton(btns, text="Použít pro toto video", height=36, corner_radius=9,
                      fg_color=ORANGE, hover_color=ORANGE_LIGHT, text_color="white",
                      font=_fnt(12, True), command=self._apply).pack(side="left", padx=(8, 0))

        self.note = ctk.CTkLabel(self, text="", font=_fnt(11), text_color=ORANGE_LIGHT, anchor="w")
        self.note.pack(fill="x", pady=(0, 8))

        # celá stránka se posouvá, takže se vejde i do menšího okna
        body = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", anchor="n")

        left = ctk.CTkFrame(row, fg_color=PANEL, border_color=BORDER, border_width=1, corner_radius=18)
        left.pack(side="left", anchor="n", padx=(0, 16))
        ctk.CTkLabel(left, text="Snímek z videa, táhni rámeček záběru", font=_fnt(11, True),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(12, 6))
        self.frame_cv = tk.Canvas(left, width=self.FW, height=self.FH, bg="#000000",
                                  highlightthickness=0)
        self.frame_cv.pack(padx=14, pady=(0, 14))
        self.frame_cv.bind("<ButtonPress-1>", lambda e: self._press(e, "frame"))
        self.frame_cv.bind("<B1-Motion>", lambda e: self._motion(e, "frame"))
        self.frame_cv.bind("<ButtonRelease-1>", lambda e: self._release())

        mid = ctk.CTkFrame(row, fg_color=PANEL, border_color=BORDER, border_width=1, corner_radius=18)
        mid.pack(side="left", anchor="n", padx=(0, 16))
        ctk.CTkLabel(mid, text="Výsledek 9:16, táhni vrstvu", font=_fnt(11, True),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(12, 6))
        self.prev_cv = tk.Canvas(mid, width=self.PW, height=self.PH, bg="#000000",
                                 highlightthickness=0)
        self.prev_cv.pack(padx=14, pady=(0, 14))
        self.prev_cv.bind("<ButtonPress-1>", lambda e: self._press(e, "prev"))
        self.prev_cv.bind("<B1-Motion>", lambda e: self._motion(e, "prev"))
        self.prev_cv.bind("<ButtonRelease-1>", lambda e: self._release())

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.pack(fill="x", anchor="n", pady=(16, 0))
        self._build_controls(controls)

    def _build_controls(self, parent) -> None:
        col1 = ctk.CTkFrame(parent, fg_color=PANEL, border_color=BORDER, border_width=1, corner_radius=18)
        col1.pack(side="left", anchor="n", padx=(0, 16), ipadx=6, ipady=6)
        col2 = ctk.CTkFrame(parent, fg_color=PANEL, border_color=BORDER, border_width=1, corner_radius=18)
        col2.pack(side="left", anchor="n", ipadx=6, ipady=6)
        parent = col1
        ctk.CTkLabel(parent, text="Vrstvy", font=_fnt(11, True), text_color=MUTED
                     ).pack(anchor="w", padx=14, pady=(12, 4))
        self.layer_var = ctk.StringVar(value="—")
        self.layer_menu = ctk.CTkOptionMenu(parent, variable=self.layer_var, values=["—"],
                                            height=32, corner_radius=8, fg_color=INPUT,
                                            button_color=BORDER, button_hover_color=BLOCK,
                                            dropdown_fg_color=PANEL, text_color=TEXT,
                                            font=_fnt(11), command=self._select_layer)
        self.layer_menu.pack(fill="x", padx=14)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 0))
        self.add_view_btn = ctk.CTkButton(row, text="+ Záběr", height=30, corner_radius=8,
                                          fg_color=INPUT, hover_color=BORDER, text_color=TEXT,
                                          font=_fnt(11), command=self._add_view)
        self.add_view_btn.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="+ Fotka", height=30, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=TEXT, font=_fnt(11),
                      command=self._add_photo).pack(side="left", fill="x", expand=True, padx=(6, 0))
        ctk.CTkButton(row, text="Smazat", width=70, height=30, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=RED, font=_fnt(11),
                      command=self._delete).pack(side="left", padx=(6, 0))

        self._section(parent, "Výřez z rámce (jen záběr)")
        self._slider(parent, "cx", "Od leva", 0, 1)
        self._slider(parent, "cy", "Od shora", 0, 1)
        self._slider(parent, "cw", "Šířka výřezu", 0.05, 1)
        self._slider(parent, "ch", "Výška výřezu", 0.05, 1)

        self._section(parent, "Místo ve 9:16")
        self._slider(parent, "px", "Poloha X", 0, 1)
        self._slider(parent, "py", "Poloha Y", 0, 1)
        self._slider(parent, "pw", "Šířka", 0.05, 1)
        self._slider(parent, "ph", "Výška", 0.05, 1)

        self._section(parent, "Titulky (táhni text v náhledu nebo šipkami)")
        self._slider(parent, "sx", "Poloha X titulků", 0, 1)
        self._slider(parent, "sy", "Poloha Y titulků", 0, 1)
        self._slider(parent, "ssize", "Velikost písma", 16, 200, fmt=lambda v: f"{v:.0f} px")

        parent = col2
        self._section(parent, "Animace na začátku")
        self.anim_var = ctk.StringVar(value=ANIM_LABELS["none"])
        ctk.CTkOptionMenu(parent, variable=self.anim_var, values=list(ANIM_LABELS.values()),
                          height=32, corner_radius=8, fg_color=INPUT, button_color=BORDER,
                          button_hover_color=BLOCK, dropdown_fg_color=PANEL, text_color=TEXT,
                          font=_fnt(11), command=self._set_anim).pack(fill="x", padx=14)
        self.secs_var = ctk.StringVar(value="0.6")
        self._entry_row(parent, "Délka animace (s)", self.secs_var)

        self._section(parent, "Fotka: kdy se ukazuje")
        self.from_var = ctk.StringVar(value="0")
        self.to_var = ctk.StringVar(value="0")
        self._entry_row(parent, "Od (s)", self.from_var)
        self._entry_row(parent, "Do (s, 0 = konec)", self.to_var)

        self._section(parent, "Knihovna loadoutů")
        self.name_var = ctk.StringVar(value="")
        self._entry_row(parent, "Název", self.name_var)
        ctk.CTkButton(parent, text="Uložit do knihovny", height=32, corner_radius=8,
                      fg_color=INPUT, hover_color=BORDER, text_color=TEXT, font=_fnt(11),
                      command=self._save_library).pack(fill="x", padx=14, pady=(6, 0))
        self.lib_var = ctk.StringVar(value="—")
        self.lib_menu = ctk.CTkOptionMenu(parent, variable=self.lib_var, values=["—"], height=32,
                                          corner_radius=8, fg_color=INPUT, button_color=BORDER,
                                          button_hover_color=BLOCK, dropdown_fg_color=PANEL,
                                          text_color=TEXT, font=_fnt(11))
        self.lib_menu.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkButton(parent, text="Načíst z knihovny", height=32, corner_radius=8, fg_color=INPUT,
                      hover_color=BORDER, text_color=ORANGE_LIGHT, font=_fnt(11, True),
                      command=self._load_library).pack(fill="x", padx=14, pady=(6, 14))

    def _section(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=_fnt(11, True), text_color=MUTED
                     ).pack(anchor="w", padx=14, pady=(16, 2))

    def _slider(self, parent, key: str, label: str, lo: float, hi: float, fmt=None) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(6, 0))
        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text=label, font=_fnt(11), text_color=MUTED).pack(side="left")
        shown = ctk.CTkLabel(head, text="", font=_fnt(11), text_color=TEXT)
        shown.pack(side="right")
        var = ctk.DoubleVar(value=0.0)
        self.vars[key] = var
        self._fmts[key] = fmt or (lambda v: f"{v * 100:.0f} %")
        slider = ctk.CTkSlider(row, from_=lo, to=hi, variable=var, height=14, button_color=ORANGE,
                               button_hover_color=ORANGE_LIGHT, progress_color=ORANGE,
                               fg_color=INPUT)
        slider.pack(fill="x")
        self.sliders[key] = slider
        slider.kb = (lo, hi, var)  # šipky na klávesnici posouvají tenhle posuvník
        slider.bind("<Button-1>", lambda e, s=slider: s.focus_set(), add="+")
        var.trace_add("write", lambda *_: self._on_slider(key, shown))

    def _entry_row(self, parent, label: str, var: ctk.StringVar) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(6, 0))
        ctk.CTkLabel(row, text=label, font=_fnt(11), text_color=MUTED).pack(side="left")
        ctk.CTkEntry(row, textvariable=var, width=150, height=28, corner_radius=8, fg_color=INPUT,
                     border_color=BORDER, text_color=TEXT, font=_fnt(11)).pack(side="right")
        var.trace_add("write", lambda *_: self._on_entry())

    # ------------------------------------------------------------ otevření a stav

    def open(self, prep: dict, lo: dict) -> None:
        """prep = {video_id, probe, frame}; lo = výchozí loadout pro toto video."""
        self.prep = prep
        probe = prep["probe"]
        self.sub.configure(text=f"Video {probe['width']}x{probe['height']}, {probe['duration'] / 60:.0f} min")
        if self.app.format_seg.get() == "Long-form":
            self.note.configure(text="Loadout se použije jen pro short-form (9:16). "
                                     "Teď je v Nastavení zvolený long-form.")
        else:
            self.note.configure(text="")
        self.frame_img = Image.open(prep["frame"]).convert("RGB")
        self._frame_photo = ImageTk.PhotoImage(self.frame_img.resize((self.FW, self.FH)))
        self._photo_cache.clear()
        self.lo = clean_loadout(lo)
        self.sel = ("v", 0) if self.lo["views"] else (("p", 0) if self.lo["photos"] else None)
        self._refresh_library()
        self._refresh_layers()
        self._load_controls()
        self._redraw()

    def _layers(self) -> list[tuple[str, tuple[str, int]]]:
        names = []
        for i in range(len(self.lo["views"])):
            names.append((f"Záběr {i + 1}", ("v", i)))
        for j in range(len(self.lo["photos"])):
            names.append((f"Fotka {j + 1}", ("p", j)))
        names.append(("Titulky", ("s", 0)))
        return names

    def _refresh_layers(self) -> None:
        items = self._layers()
        self._layer_map = {name: key for name, key in items}
        names = [name for name, _ in items] or ["—"]
        self.layer_menu.configure(values=names)
        current = next((name for name, key in items if key == self.sel), names[0])
        self.layer_var.set(current)
        self.add_view_btn.configure(state="normal" if len(self.lo["views"]) < LOADOUT_MAX_VIEWS
                                    else "disabled")

    def _layer(self) -> dict | None:
        if not self.sel or self.sel[0] == "s":  # titulky nejsou vrstva s rámečkem
            return None
        kind, i = self.sel
        items = self.lo["views"] if kind == "v" else self.lo["photos"]
        return items[i] if i < len(items) else None

    def _select_layer(self, name: str) -> None:
        if name in self._layer_map:
            self.sel = self._layer_map[name]
            self._load_controls()
            self._redraw()

    def _load_controls(self) -> None:
        layer = self._layer()
        self._loading = True
        try:
            sub = self.lo["subtitles"]
            self.vars["sx"].set(sub["x"])
            self.vars["sy"].set(sub["y"])
            self.vars["ssize"].set(sub["size"])
            is_view = bool(self.sel and self.sel[0] == "v")
            for key in ("cx", "cy", "cw", "ch"):
                self.sliders[key].configure(state="normal" if is_view else "disabled")
            if layer is None:
                for key in ("cx", "cy", "cw", "ch", "px", "py", "pw", "ph"):
                    self.vars[key].set(0.0)
                self.anim_var.set(ANIM_LABELS["none"])
                self.secs_var.set("0.6")
                return
            if is_view:
                for key, val in zip(("cx", "cy", "cw", "ch"), layer["crop"]):
                    self.vars[key].set(val)
            for key, val in zip(("px", "py", "pw", "ph"), layer["place"]):
                self.vars[key].set(val)
            self.anim_var.set(ANIM_LABELS.get(layer.get("anim", "none"), ANIM_LABELS["none"]))
            self.secs_var.set(str(layer.get("anim_seconds", 0.6)))
            if not is_view:
                self.from_var.set(str(layer.get("start", 0)))
                self.to_var.set(str(layer.get("end", 0)))
        finally:
            self._loading = False

    def _on_slider(self, key: str, shown) -> None:
        val = self.vars[key].get()
        shown.configure(text=self._fmts[key](val))
        if self._loading:
            return
        if key in ("sx", "sy", "ssize"):
            sub = self.lo["subtitles"]
            if key == "sx":
                sub["x"] = _clamp(val)
            elif key == "sy":
                sub["y"] = _clamp(val)
            else:
                sub["size"] = int(max(16, min(200, round(val))))
            self._redraw()
            return
        layer = self._layer()
        if layer is None:
            return
        rect = layer["crop"] if key in ("cx", "cy", "cw", "ch") else layer["place"]
        if key in ("cx", "px"):
            rect[0] = _clamp(val, 0.0, 1.0 - rect[2])
        elif key in ("cy", "py"):
            rect[1] = _clamp(val, 0.0, 1.0 - rect[3])
        elif key in ("cw", "pw"):
            rect[2] = _clamp(val, 0.05, 1.0 - rect[0])
        else:
            rect[3] = _clamp(val, 0.05, 1.0 - rect[1])
        self._redraw()

    def _on_entry(self) -> None:
        if self._loading:
            return
        layer = self._layer()
        if layer is None:
            return
        try:
            layer["anim_seconds"] = max(0.1, min(3.0, float(self.secs_var.get().replace(",", "."))))
            if self.sel and self.sel[0] == "p":
                layer["start"] = max(0.0, float(self.from_var.get().replace(",", ".")))
                layer["end"] = max(0.0, float(self.to_var.get().replace(",", ".")))
        except ValueError:
            pass  # rozepsaná hodnota, počká se na další znak

    def _set_anim(self, label: str) -> None:
        layer = self._layer()
        if layer is not None:
            layer["anim"] = ANIM_KEYS.get(label, "none")
            self._redraw()

    # ------------------------------------------------------------ úpravy vrstev

    def _add_view(self) -> None:
        if len(self.lo["views"]) >= LOADOUT_MAX_VIEWS:
            self.app.status.configure(text=f"Víc než {LOADOUT_MAX_VIEWS} záběrů nejde.", text_color=RED)
            return
        self.lo["views"].append({"crop": [0.25, 0.0, 0.5, 1.0], "place": [0.0, 0.0, 1.0, 0.5],
                                 "anim": "none", "anim_seconds": 0.6})
        self.sel = ("v", len(self.lo["views"]) - 1)
        self._refresh_layers()
        self._load_controls()
        self._redraw()

    def _add_photo(self) -> None:
        path = filedialog.askopenfilename(
            title="Vyber fotku",
            filetypes=[("Obrázky", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Všechny soubory", "*.*")])
        if not path:
            return
        self.lo["photos"].append({"path": path, "place": [0.3, 0.3, 0.4, 0.2], "anim": "none",
                                  "anim_seconds": 0.6, "start": 0.0, "end": 0.0})
        self.sel = ("p", len(self.lo["photos"]) - 1)
        self._refresh_layers()
        self._load_controls()
        self._redraw()

    def _delete(self) -> None:
        if not self.sel or self.sel[0] == "s":
            return
        kind, i = self.sel
        items = self.lo["views"] if kind == "v" else self.lo["photos"]
        if i < len(items):
            del items[i]
        self.sel = ("v", 0) if self.lo["views"] else (("p", 0) if self.lo["photos"] else None)
        self._refresh_layers()
        self._load_controls()
        self._redraw()

    # ------------------------------------------------------------ myš

    def _press(self, e, where: str) -> None:
        if where == "frame":
            fx, fy = e.x / self.FW, e.y / self.FH
            cands = [(("v", i), v["crop"]) for i, v in enumerate(self.lo["views"])]
        else:
            fx, fy = e.x / self.PW, e.y / self.PH
            sub = self.lo["subtitles"]
            if abs(fx - sub["x"]) < 0.25 and abs(fy - sub["y"]) < 0.06:
                self.sel = ("s", 0)
                self._refresh_layers()
                self._load_controls()
                self.drag = ("sub", fx - sub["x"], fy - sub["y"])
                self._redraw()
                return
            cands = [(("v", i), v["place"]) for i, v in enumerate(self.lo["views"])]
            cands += [(("p", j), p["place"]) for j, p in enumerate(self.lo["photos"])]
        hit = next((key for key, rect in reversed(cands) if _inside(rect, fx, fy)), None)
        if hit is None:
            return
        if hit != self.sel:
            self.sel = hit
            self._refresh_layers()
            self._load_controls()
        layer = self._layer()
        rect = layer["crop"] if where == "frame" else layer["place"]
        self.drag = (where, fx - rect[0], fy - rect[1])
        self._redraw()

    def _motion(self, e, where: str) -> None:
        if not self.drag or self.drag[0] not in (where, "sub"):
            return
        if self.drag[0] == "sub":
            sub = self.lo["subtitles"]
            sub["x"] = _clamp(e.x / self.PW - self.drag[1])
            sub["y"] = _clamp(e.y / self.PH - self.drag[2])
            self._load_controls()
            self._redraw()
            return
        layer = self._layer()
        if layer is None or (where == "frame" and self.sel[0] != "v"):
            return
        fx = e.x / (self.FW if where == "frame" else self.PW)
        fy = e.y / (self.FH if where == "frame" else self.PH)
        rect = layer["crop"] if where == "frame" else layer["place"]
        rect[0] = _clamp(fx - self.drag[1], 0.0, 1.0 - rect[2])
        rect[1] = _clamp(fy - self.drag[2], 0.0, 1.0 - rect[3])
        self._load_controls()
        self._redraw()

    # ------------------------------------------------------------ klávesnice

    def handle_key(self, e) -> bool:
        """Šipky posouvají vybranou vrstvu (Shift = větší krok, Ctrl = výřez záběru),
        +/- mění velikost, [ a ] přepínají vrstvy, Delete maže, Esc zpět. Vrací True, když klávesu použil."""
        key = e.keysym
        shift = bool(e.state & 0x1)
        ctrl = bool(e.state & 0x4)
        if key == "Escape":
            self.app.show("create")
            return True
        if key in ("bracketleft", "bracketright"):
            self._cycle(-1 if key == "bracketleft" else 1)
            return True
        if key in ("Delete", "BackSpace") and self.sel and self.sel[0] in ("v", "p"):
            self._delete()
            return True
        if key in ("plus", "equal", "KP_Add", "minus", "KP_Subtract") and self.sel:
            self._resize(1 if key in ("plus", "equal", "KP_Add") else -1)
            return True
        step = 0.05 if shift else 0.01
        dx = {"Left": -step, "Right": step}.get(key, 0.0)
        dy = {"Up": -step, "Down": step}.get(key, 0.0)
        if (dx or dy) and self.sel:
            self._nudge(dx, dy, ctrl)
            return True
        return False

    def _cycle(self, step: int) -> None:
        keys = [key for _, key in self._layers()]
        if not keys:
            return
        idx = keys.index(self.sel) if self.sel in keys else -1
        self.sel = keys[(idx + step) % len(keys)]
        self._refresh_layers()
        self._load_controls()
        self._redraw()

    def _nudge(self, dx: float, dy: float, crop: bool) -> None:
        if self.sel[0] == "s":
            sub = self.lo["subtitles"]
            sub["x"] = _clamp(sub["x"] + dx)
            sub["y"] = _clamp(sub["y"] + dy)
        else:
            layer = self._layer()
            if layer is None:
                return
            rect = layer["crop"] if (crop and self.sel[0] == "v") else layer["place"]
            rect[0] = _clamp(rect[0] + dx, 0.0, 1.0 - rect[2])
            rect[1] = _clamp(rect[1] + dy, 0.0, 1.0 - rect[3])
        self._load_controls()
        self._redraw()

    def _resize(self, sign: int) -> None:
        if self.sel[0] == "s":
            sub = self.lo["subtitles"]
            sub["size"] = int(max(16, min(200, sub["size"] + sign * 4)))
        else:
            layer = self._layer()
            if layer is None:
                return
            rect = layer["place"]
            rect[2] = _clamp(rect[2] + sign * 0.02, 0.05, 1.0 - rect[0])
            rect[3] = _clamp(rect[3] + sign * 0.02, 0.05, 1.0 - rect[1])
        self._load_controls()
        self._redraw()

    def _release(self) -> None:
        self.drag = None

    # ------------------------------------------------------------ kreslení

    def _redraw(self) -> None:
        self._draw_frame()
        self._draw_preview()

    def _draw_frame(self) -> None:
        cv = self.frame_cv
        cv.delete("all")
        if self._frame_photo is not None:
            cv.create_image(0, 0, anchor="nw", image=self._frame_photo)
        for i, v in enumerate(self.lo["views"]):
            x, y, w, h = v["crop"]
            color = VIEW_COLORS[i % len(VIEW_COLORS)]
            selected = self.sel == ("v", i)
            cv.create_rectangle(x * self.FW, y * self.FH, (x + w) * self.FW, (y + h) * self.FH,
                                outline=color, width=3 if selected else 1)
            cv.create_text(x * self.FW + 6, y * self.FH + 6, text=str(i + 1), anchor="nw",
                           fill=color, font=_fnt(12, True))

    def _load_photo(self, path: str) -> Image.Image | None:
        if path not in self._photo_cache:
            try:
                self._photo_cache[path] = Image.open(path).convert("RGBA")
            except OSError:
                self._photo_cache[path] = None
        return self._photo_cache[path]

    def _draw_preview(self) -> None:
        img = Image.new("RGB", (self.PW, self.PH), (0, 0, 0))
        if self.frame_img is not None:
            fw, fh = self.frame_img.size
            for v in self.lo["views"]:
                cx, cy, cw, ch = v["crop"]
                part = self.frame_img.crop((int(cx * fw), int(cy * fh),
                                            max(int(cx * fw) + 1, int((cx + cw) * fw)),
                                            max(int(cy * fh) + 1, int((cy + ch) * fh))))
                bx, by, bw, bh = v["place"]
                tw, th = max(1, int(bw * self.PW)), max(1, int(bh * self.PH))
                s = max(tw / part.width, th / part.height)
                part = part.resize((max(1, round(part.width * s)), max(1, round(part.height * s))),
                                   RESAMPLE)
                left, top = (part.width - tw) // 2, (part.height - th) // 2
                img.paste(part.crop((left, top, left + tw, top + th)), (int(bx * self.PW), int(by * self.PH)))
        for p in self.lo["photos"]:
            pic = self._load_photo(p["path"])
            if pic is None:
                continue
            bx, by, bw, bh = p["place"]
            tw, th = max(1, int(bw * self.PW)), max(1, int(bh * self.PH))
            s = min(tw / pic.width, th / pic.height)
            pic2 = pic.resize((max(1, round(pic.width * s)), max(1, round(pic.height * s))), RESAMPLE)
            img.paste(pic2, (int(bx * self.PW) + (tw - pic2.width) // 2,
                             int(by * self.PH) + (th - pic2.height) // 2), pic2)

        self._prev_photo = ImageTk.PhotoImage(img)
        cv = self.prev_cv
        cv.delete("all")
        cv.create_image(0, 0, anchor="nw", image=self._prev_photo)
        for i, v in enumerate(self.lo["views"]):
            x, y, w, h = v["place"]
            self._outline(cv, x * self.PW, y * self.PH, (x + w) * self.PW, (y + h) * self.PH,
                          VIEW_COLORS[i % len(VIEW_COLORS)], self.sel == ("v", i), str(i + 1))
        for j, p in enumerate(self.lo["photos"]):
            x, y, w, h = p["place"]
            self._outline(cv, x * self.PW, y * self.PH, (x + w) * self.PW, (y + h) * self.PH,
                          PHOTO_COLOR, self.sel == ("p", j), f"F{j + 1}")
        self._draw_subtitles(cv)

    def _draw_subtitles(self, cv) -> None:
        sub = self.lo["subtitles"]
        size = max(8, int(round(sub["size"] * self.PW / 1080)))  # 1080 px je šířka výstupu
        x, y = sub["x"] * self.PW, sub["y"] * self.PH
        font = ("Segoe UI", -size, "bold")
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            cv.create_text(x + dx, y + dy, text=SUBTITLE_SAMPLE, fill="#000000", font=font)
        cv.create_text(x, y, text=SUBTITLE_SAMPLE, fill="#FFFFFF", font=font)
        if self.sel == ("s", 0):
            half = len(SUBTITLE_SAMPLE) * size * 0.3
            cv.create_rectangle(x - half, y - size * 0.7, x + half, y + size * 0.7,
                                outline=ORANGE, width=2, dash=(3, 2))

    @staticmethod
    def _outline(cv, x0, y0, x1, y1, color, selected, label) -> None:
        cv.create_rectangle(x0, y0, x1, y1, outline=color, width=3 if selected else 1)
        cv.create_text(x0 + 6, y0 + 6, text=label, anchor="nw", fill=color, font=_fnt(11, True))

    # ------------------------------------------------------------ knihovna a použití

    def _refresh_library(self) -> None:
        names = list_loadouts(self.app.cfg) or ["—"]
        self.lib_menu.configure(values=names)
        self.lib_var.set(names[0])

    def _save_library(self) -> None:
        name = self.name_var.get().strip() or "loadout"
        self.lo["name"] = name
        saved = save_loadout(self.app.cfg, self.lo)
        self._refresh_library()
        self.app.status.configure(text=f"Loadout uložen do knihovny jako „{saved}“.", text_color=GREEN)

    def _load_library(self) -> None:
        lo = load_loadout(self.app.cfg, self.lib_var.get())
        if lo is None:
            self.app.status.configure(text="Tenhle loadout v knihovně není.", text_color=RED)
            return
        self.lo = lo
        self.name_var.set(lo["name"])
        self.sel = ("v", 0) if self.lo["views"] else (("p", 0) if self.lo["photos"] else None)
        self._refresh_layers()
        self._load_controls()
        self._redraw()

    def _apply(self) -> None:
        self.lo["name"] = self.name_var.get().strip() or self.lo.get("name", "loadout")
        self.app.apply_loadout(clean_loadout(self.lo))

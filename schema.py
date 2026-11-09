"""Jediný zdroj pravdy pro nastavení.

Každé nastavení je popsané tady: typ, výchozí hodnota, popis. Podle toho se:
  - generuje settings.yaml s komentáři,
  - vykreslí stránka Nastavení v GUI,
  - načítají a validují hodnoty.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class F:
    key: str
    default: Any
    kind: str                      # bool | int | float | str | choice | path
    label: str
    desc: str = ""
    options: list[str] = field(default_factory=list)
    min: float | None = None
    max: float | None = None
    show: bool = True              # False = nastavuje se automaticky podle VODu, v GUI se neukazuje


SECTIONS: list[tuple[str, str, list[F]]] = [
    ("source", "Zdroj", [
        F("url", "", "str", "URL nebo cesta",
          "URL VODu (Kick, YouTube) nebo cesta k lokálnímu videu. Vyplní se do hlavní obrazovky.", show=False),
    ]),

    ("download", "Stahování", [
        F("max_height", 1080, "int", "Nejvyšší výška videa (px)",
          "Vyšší kvalita = větší stahování a déle trvá. Pro vertikální klipy stačí 720 až 1080.",
          min=240, max=2160, show=False),
        F("cookies_file", "", "path", "Soubor cookies.txt",
          "Volitelné. Když Kick nebo YouTube stahování blokují, exportuj cookies z prohlížeče a vlož cestu sem."),
        F("retries", 5, "int", "Počet pokusů stahování",
          "Kolikrát se zkusí stažení znovu při výpadku sítě.", min=0, max=20, show=False),
        F("keep_source", False, "bool", "Nechat stažené video",
          "Po zpracování nemazat stažený soubor. Zabere hodně místa, ale šetří opětovné stahování."),
    ]),

    ("clips", "Vytvořit klipy", [
        F("format", "short", "choice", "Formát klipů",
          "short = vertikální klipy 9:16 do 60 s (podle loadoutu). long = delší klipy 16:9 od 60 s, "
          "délku nastavíš níže.", options=["short", "long"]),
        F("max_seconds", 60, "int", "Nejdelší short-form klip (s)",
          "Platí jen pro short-form. Shorts a Reels mají limit 60 s.", min=20, max=60),
        F("long_minutes", 15, "int", "Délka long-form klipu (min)",
          "Platí jen pro long-form. Nejdelší klip, který AI smí vybrat. Nejkratší je 1 minuta.",
          min=1, max=60),
        F("count_per_hour", 6, "float", "Klipů na hodinu materiálu",
          "Zhruba kolik klipů chceš na hodinu streamu. AI může vrátit méně, když nic dobrého není.",
          min=0.5, max=60),
        F("min_score", 0, "int", "Minimální hodnocení (nepoužívá se)",
          "Skóre je informativní odhad potenciálu views. Žádný moment se kvůli nízkému skóre automaticky nevyřadí.",
          min=0, max=100),
        F("min_seconds", 20, "int", "Nejkratší klip (s)", "Interní hodnota.", min=5, max=180, show=False),
        F("max_overlap_percent", 25, "int", "Povolené překrytí klipů (%)", "Interní hodnota.",
          min=0, max=100, show=False),
    ]),

    ("scoring", "Hodnocení kvality (automaticky)", [
        F("weight_hook", 25, "int", "Váha: začátek (hook)",
          "Jak moc počítat, že klip zaujme hned v prvních sekundách.", min=0, max=100, show=False),
        F("weight_emotion", 20, "int", "Váha: emoce",
          "Smích, šok, napětí, nadšení, hádka. Silné emoce bývají sdílené.", min=0, max=100, show=False),
        F("weight_standalone", 15, "int", "Váha: srozumitelnost bez kontextu",
          "Jak dobře klip pochopí divák, který nezná celý stream.", min=0, max=100, show=False),
        F("weight_payoff", 15, "int", "Váha: pointa na konci",
          "Vyvrcholení, vtip nebo vyřešení na konci klipu.", min=0, max=100, show=False),
        F("weight_humor", 10, "int", "Váha: humor",
          "Vtipné momenty a hlášky.", min=0, max=100, show=False),
        F("weight_pacing", 15, "int", "Váha: tempo řeči",
          "Heuristika z přepisu. Ideální je asi 2 až 3,2 slova za sekundu.", min=0, max=100, show=False),
    ]),

    ("ai", "AI", [
        F("speed_mode", "vyvážené", "choice", "Priorita rychlosti",
          "rychlé = nejrychlejší zpracování (menší přepis a kratší odezva AI, o něco nižší přesnost). "
          "vyvážené = výchozí. kvalitní = nejpřesnější, nejpomalejší.",
          options=["rychlé", "vyvážené", "kvalitní"]),
        F("provider", "ollama", "choice", "Poskytovatel AI",
          "ollama = běží lokálně a zdarma. openrouter = cloud, platíš za použití.",
          options=["ollama", "openrouter"]),
        F("chunk_minutes", 30, "int", "Délka části přepisu (min)",
          "Přepis se AI posílá po kouscích. Kratší části = přesnější, ale víc požadavků.", min=5, max=120, show=False),
        F("temperature", 0.3, "float", "Teplota modelu",
          "Nižší = konzistentnější hodnocení. Doporučeno 0,2 až 0,5.", min=0, max=1, show=False),
        F("max_retries", 2, "int", "Pokusy při chybě AI",
          "Kolikrát se zopakuje požadavek na AI, když selže.", min=0, max=10, show=False),
        F("timeout_s", 900, "int", "Časový limit AI (s)",
          "Jak dlouho čekat na odpověď jedné části.", min=30, max=3600, show=False),
        F("channel_context", "", "str", "Popis kanálu",
          "Čím se kanál zabývá, kdo v něm hraje, jaký je humor. AI díky tomu rozumí kontextu."),
        F("extra_instructions", "", "str", "Vlastní pokyny pro AI",
          "Co chceš, aby AI dělala nebo nedělala. Např. nevybírej momenty s nadávkami."),
        F("ollama_url", "http://localhost:11434", "str", "Ollama URL",
          "Adresa lokální Ollamy.", show=False),
        F("ollama_model", "gemma3:12b", "str", "Ollama model",
          "Model stažený přes ollama pull. Např. gemma3:12b, gemma3:27b, qwen3:14b."),
        F("ollama_num_ctx", 16384, "int", "Velikost kontextu (tokeny)",
          "Víc = větší části přepisu, ale víc paměti. Pro 12 GB GPU necháme 16384.",
          min=2048, max=131072, show=False),
        F("openrouter_api_key_env", "OPENROUTER_API_KEY", "str", "Název proměnné s klíčem",
          "Název proměnné prostředí, ve které je klíč OpenRouter. Klíč se nikam neukládá."),
        F("openrouter_model", "google/gemma-3-27b-it", "str", "OpenRouter model",
          "Model na OpenRouteru, např. anthropic/claude-3.5-haiku nebo google/gemini-2.0-flash-001."),
    ]),

    ("transcription", "Přepis řeči", [
        F("model", "large-v3-turbo", "choice", "Model přepisu",
          "Větší model = přesnější, ale pomalejší. large-v3-turbo je dobrý kompromis.",
          options=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]),
        F("device", "auto", "choice", "Zařízení",
          "auto = GPU, když je dostupná, jinak procesor.", options=["auto", "cuda", "cpu"], show=False),
        F("compute_type", "auto", "choice", "Přesnost výpočtu",
          "auto = float16 na GPU, int8 na procesoru. Pro GPU s málo pamětí zvol int8.",
          options=["auto", "float16", "int8", "float32"], show=False),
        F("language", "auto", "str", "Jazyk řeči",
          "auto, nebo kód jazyka: cs, en, de, ..."),
        F("vad_filter", True, "bool", "Přeskakovat ticho",
          "Ignoruje dlouhé pauzy a hudbu. Zrychluje přepis a snižuje halucinace.", show=False),
        F("beam_size", 5, "int", "Beam size",
          "Vyšší = přesnější a pomalejší. 1 je nejrychlejší.", min=1, max=10, show=False),
        F("initial_prompt", "", "str", "Slovník pro přepis",
          "Jména, hry a zkratky, které se mají přepsat správně. Např. názvy her a jména hostů.", show=False),
    ]),

    ("captions", "Titulky", [
        F("enabled", True, "bool", "Zapálit titulky",
          "Vypnuté = klipy bez titulků."),
        F("font", "Arial", "str", "Písmo", "Název písma nainstalovaného ve Windows.", show=False),
        F("font_size", 60, "int", "Velikost písma",
          "Při výšce videa 1920 px. Typicky 50 až 70.", min=20, max=150),
        F("text_color", "&H00FFFFFF", "str", "Barva textu",
          "Formát ASS: &HAABBGGRR. &H00FFFFFF = bílá, &H0000FFFF = žlutá."),
        F("outline_color", "&H00000000", "str", "Barva obrysu",
          "Formát ASS. &H00000000 = černá.", show=False),
        F("outline_width", 4, "int", "Tloušťka obrysu",
          "Obrys zlepšuje čitelnost. 3 až 5.", min=0, max=12, show=False),
        F("shadow", 0, "int", "Stín", "Velikost stínu pod písmem.", min=0, max=8, show=False),
        F("bold", True, "bool", "Tučné písmo", "Tučný text bývá čitelnější na mobilu."),
        F("uppercase", False, "bool", "Velká písmena",
          "Titulky celé velkými písmeny."),
        F("position", "bottom", "choice", "Pozice",
          "Kde titulky na videu jsou.", options=["bottom", "middle", "top"]),
        F("margin_v", 350, "int", "Odsazení od okraje (px)",
          "Vzdálenost od spodního nebo horního okraje.", min=0, max=1000, show=False),
        F("words_per_caption", 4, "int", "Slov v jednom titulku",
          "Méně slov = rychlejší střídání titulků.", min=1, max=12),
    ]),

    ("output", "Výstup", [
        F("width", 1080, "int", "Šířka (px)", "Standard 9:16 je 1080 × 1920.", min=240, max=4320, show=False),
        F("height", 1920, "int", "Výška (px)", "", min=240, max=7680, show=False),
        F("fps", 30, "int", "Snímky za sekundu", "30 je běžné, 60 plynulejší ale větší soubor.",
          min=15, max=60, show=False),
        F("crf", 20, "int", "Kvalita (CRF)",
          "Nižší = lepší kvalita a větší soubor. 18 až 23 je rozumné.", min=0, max=51, show=False),
        F("preset", "veryfast", "choice", "Rychlost kódování",
          "Pomalejší = menší soubor a lepší kvalita při stejném CRF.",
          options=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"], show=False),
        F("audio_bitrate", "160k", "str", "Bitrate zvuku", "Např. 128k, 160k, 192k.", show=False),
        F("folder", "output", "path", "Složka pro klipy",
          "Kam se ukládají hotové klipy."),
        F("file_pattern", "klip_{index:02d}", "str", "Vzor názvu souboru",
          "Proměnné: {index} = pořadí, {score} = hodnocení, {title} = název klipu.", show=False),
        F("write_txt", True, "bool", "Ukládat .txt s popisem",
          "Vedle každého klipu uloží titulek, popis, hashtagy a důvod výběru."),
        F("open_folder_after", True, "bool", "Otevřít složku po dokončení",
          "Po skončení se otevře složka s klipy v Průzkumníku."),
    ]),

    ("cache", "Cache a úklid", [
        F("work_dir", "work", "path", "Pracovní složka",
          "Stažená videa, přepisy a výběry klipů. Zde se hromadí místo.", show=False),
        F("keep_transcripts", True, "bool", "Ukládat přepisy",
          "Přepis je nejdražší část. Uložený přepis se při dalším zpracování nepřepisuje.", show=False),
        F("keep_selections", True, "bool", "Ukládat výběr AI",
          "Uloží hodnocení AI. Změna prahu nebo vah pak neznamená nové volání AI.", show=False),
        F("auto_clean_days", 14, "int", "Mazat starší než (dní)",
          "Pracovní složky starší než tento počet dní se po zpracování smažou. 0 = nikdy.",
          min=0, max=3650),
        F("max_cache_gb", 20.0, "float", "Maximální velikost cache (GB)",
          "Když cache přeroste, nejdřív se smažou nejstarší stažená videa.", min=0.5, max=2000),
    ]),

    ("learning", "Učení z hodnocení", [
        F("enabled", True, "bool", "Učit se z tvých hodnocení",
          "Klipy označené 👍 nebo 👎 se uloží a AI podle nich příště lépe pozná, co se ti líbí."),
        F("examples", 6, "int", "Počet příkladů v promptu",
          "Kolik nedávných dobrých a špatných klipů se pošle AI jako příklad.", min=0, max=30, show=False),
    ]),

    ("youtube", "YouTube", [
        F("client_secret_file", "", "path", "Soubor client_secret (JSON)",
          "OAuth klíč typu Desktop app z Google Cloud Console. Postup je v README. Bez něj nejde nahrávat."),
        F("default_privacy", "private", "choice", "Výchozí viditelnost",
          "private = jen ty, unlisted = přes odkaz, public = všichni. Nový projekt bez auditu nahraje vždy jako private.",
          options=["private", "unlisted", "public"]),
    ]),

    ("updates", "Aktualizace", [
        F("auto_check", True, "bool", "Kontrolovat aktualizace při startu",
          "Aplikace se podívá na GitHub, jestli není novější verze. Jen u sestavené .exe."),
        F("auto_install", False, "bool", "Instalovat automaticky",
          "Když je nová verze, stáhne a nainstaluje ji sama a restartuje aplikaci. Vypnuté = jen zobrazí tlačítko."),
    ]),
]


def default_settings() -> dict:
    return {sec: {f.key: copy.deepcopy(f.default) for f in fields}
            for sec, _title, fields in SECTIONS}


def _coerce(f: F, value: Any) -> Any:
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "ano", "yes", "on")
    if f.kind == "int":
        v = int(float(value))
    elif f.kind == "float":
        v = float(value)
    elif f.kind == "choice":
        v = str(value)
        if f.options and v not in f.options:
            v = str(f.default)
        return v
    else:
        return "" if value is None else str(value)
    if f.min is not None and v < f.min:
        v = type(v)(f.min)
    if f.max is not None and v > f.max:
        v = type(v)(f.max)
    return v


def load_settings(path: Path) -> dict:
    """Načte nastavení a doplní chybějící klíče výchozími hodnotami."""
    values = default_settings()
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        for sec, _title, fields in SECTIONS:
            for f in fields:
                try:
                    if sec in data and f.key in data[sec]:
                        values[sec][f.key] = _coerce(f, data[sec][f.key])
                except (TypeError, ValueError):
                    pass  # chybnou hodnotu nahradí výchozí
    return values


def write_settings(path: Path, values: dict) -> None:
    """Zapíše settings.yaml s komentářem u každého nastavení."""
    lines = [
        "# Gasbyn Clipper - nastavení.",
        "# Hodnoty jde měnit i přímo v tomto souboru, nebo přes stránku Nastavení v aplikaci.",
        "",
    ]
    for sec, title, fields in SECTIONS:
        lines.append(f"# ===== {title} =====")
        lines.append(f"{sec}:")
        for f in fields:
            if not f.show:
                continue  # automatická nastavení se do YAML nezapisují
            hint = f.desc
            if f.kind == "choice" and f.options:
                hint = (hint + " " if hint else "") + f"Možnosti: {', '.join(f.options)}."
            if f.min is not None or f.max is not None:
                hint = (hint + " " if hint else "") + f"Rozsah: {f.min}-{f.max}."
            for part in filter(None, hint.split("\n")):
                lines.append(f"  # {part}")
            lines.append(f"  {f.key}: {json.dumps(values[sec][f.key], ensure_ascii=False)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    # python schema.py -> vygeneruje výchozí settings.yaml
    here = Path(__file__).resolve().parent
    write_settings(here / "settings.yaml", default_settings())
    print("settings.yaml vygenerován.")

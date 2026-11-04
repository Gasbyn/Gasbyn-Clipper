# Gasbyn Clipper

AI klipovač pro Windows. Vezme VOD z Kicku (nebo YouTube, nebo lokální video), AI najde momenty, každému dá **hodnocení 0 až 100** a vystřihne vertikální klipy 9:16 s titulky. Klipy pod nastaveným prahem se nevytvoří.

## Instalace (Windows 10/11)

1. Otevři stránku **Releases** a stáhni `Setup.exe`.
2. Spusť ho a projdi průvodce. Instaluje se jen pro tebe, správce není potřeba.
3. Spusť **Gasbyn Clipper** ze zástupce.

V instalaci je ffmpeg. Při prvním přepisu se stáhne model Whisper, takže je potřeba internet.

Pro výběr klipů potřebuješ jedno z toho:
- **Ollama** (zdarma, běží lokálně): nainstaluj z ollama.com a spusť `ollama pull gemma3:12b`
- **OpenRouter** (cloud, platíš za použití): vytvoř klíč a nastav proměnnou prostředí `OPENROUTER_API_KEY`

Doporučeno: NVIDIA GPU (RTX 3060 12 GB a lepší). Přepis je pak výrazně rychlejší.

Windows může při prvním spuštění ukázat varování SmartScreen, protože aplikace není podepsaná certifikátem. Klikni na *Více informací → Přesto spustit*.

## Použití

1. Vlož URL VODu nebo cestu k lokálnímu videu.
2. Stiskni **Spustit AI Clipper**.
3. Hotové klipy najdeš na stránce **Hotové klipy**: skóre, titulek, popis, hashtagy, tlačítka Přehrát, Složka a Kopírovat.

Běh má fáze: stažení, přepis, hodnocení AI, střih. Průběh je vidět v logu a v ukazateli. Běh jde kdykoli zrušit.

## Hodnocení kvality

Každý navržený klip dostane skóre 0 až 100 jako vážený průměr těchto kritérií:

| Kritérium | Co měří |
|-----------|---------|
| Hook | Zaujme hned v prvních sekundách? |
| Emoce | Smích, šok, napětí, nadšení |
| Srozumitelnost | Pochopí ho divák bez znalosti streamu? |
| Pointa | Končí vtipem nebo vyvrcholením? |
| Humor | Jak je vtipný? |
| Tempo | Heuristika z přepisu, ideál 2 až 3,2 slova za sekundu |

Váhy jde nastavit v sekci **Hodnocení kvality**. Práh **Minimální hodnocení** určuje, které klipy se vůbec nevytvoří.

Hodnocení AI se ukládá do cache. Když později změníš práh nebo váhy, výběr se přepočítá bez nového volání AI. Novou AI analýzu vynutíš zaškrtnutím *Znovu zavolat AI*.

## Nastavení

Všechno je na stránce **Nastavení**, každé pole má popis. Stejné hodnoty jsou v `settings.yaml` s komentáři. Hlavní oblasti:

- **Výběr klipů**: počet na hodinu, délka, práh hodnocení, povolené překrytí
- **Hodnocení kvality**: váhy jednotlivých kritérií
- **AI**: Ollama nebo OpenRouter, modely, teplota, kontext, popis kanálu, vlastní pokyny pro AI
- **Přepis řeči**: model Whisper, zařízení, jazyk, slovník jmen a her
- **Titulky**: písmo, velikost, barvy, obrys, pozice, velká písmena
- **Výstup**: rozlišení, FPS, kvalita, složka, název souborů
- **Cache a úklid**: pracovní složka, co ukládat, automatické mazání, limit velikosti

## Cache a úklid

Stažená videa, přepisy a výběry AI jsou v pracovní složce `work`. Na stránce **Cache a úklid** vidíš, kolik místa zabírají, a můžeš je vyčistit po částech. Tlačítko *Spustit úklid podle nastavení* smaže staré položky a hlídá limit velikosti.

## Příkazová řádka (pro pokročilé)

```
python clipper.py "https://kick.com/.../videos/..."
python clipper.py stream.mp4 --no-captions --min-score 70
python clipper.py --check
python clipper.py --clean downloads
```

## Spuštění ze zdrojáků

```
install.bat          # vytvoří .venv a nainstaluje závislosti
run.bat              # spustí GUI
```

Potřebuješ Python 3.10+ a ffmpeg v PATH. Výchozí nastavení se znovu vygeneruje příkazem `python schema.py`.

## Známá omezení

- Oříznutí 9:16 bere střed záběru. Sledování obličeje zatím není, takže u streamů s kamerou v rohu nebo s více lidmi vedle sebe může být výřez špatně.
- AI vybírá podle řeči a obrazu jen přes přepis. Vtipy, které jsou jen vizuální a nikdo je nekomentuje, nenajde.
- Publikování na YouTube a TikTok zatím není. Klipy a popisy jsou připravené ke ručnímu nahrání.
- Stahování z Kicku závisí na yt-dlp. Když přestane fungovat, zkus aktualizaci yt-dlp, nebo vlož cookies v nastavení.
- Hodnocení AI je odhad. Skóre 0 až 100 neznamená, že klip bude mít úspěch. Nejlepší výsledky dává ladění vah a pokynů pro AI podle vlastních výsledků.

## Aktualizace

Nové verze přijdou jako nová Release se `Setup.exe`. Stará verze se přepíše instalací nové.

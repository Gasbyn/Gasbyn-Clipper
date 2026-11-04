# Gasbyn Clipper

Vlastní nástroj pro Windows: vezme VOD z Kicku (nebo YouTube, nebo lokální video), AI najde nejlepší momenty a vystřihne z nich vertikální klipy 9:16, volitelně s titulky.

## Nejjednodušší instalace (Windows 10/11)

1. Otevři stránku **Releases** tohoto repozitáře a stáhni `Setup.exe`.
2. Spusť ho a projdi průvodce. Instaluje se jen pro tebe, správce není potřeba.
3. Spusť **Gasbyn Clipper** ze zástupce, vlož URL VODu a potvrď Enter.

Součástí instalace je ffmpeg. Přepis (Whisper) si při prvním spuštění stáhne model, takže je potřeba internet. Pro výběr klipů potřebuješ ještě Ollamu, nebo OpenRouter klíč (viz níže).

Windows může při prvním spuštění ukázat varování SmartScreen (aplikace není podepsaná certifikátem). Klikni na *Více informací → Přesto spustit*.

## Co potřebuješ (když spouštíš ze zdrojáků)

- Windows 10/11
- **Python 3.10+** (při instalaci zaškrtni "Add Python to PATH")
- **ffmpeg** v PATH (např. build z gyan.dev, musí obsahovat libass kvůli titulkům)
- Jedno z toho pro výběr klipů:
  - **Ollama** (zdarma, lokálně): nainstaluj z ollama.com a spusť `ollama pull gemma3:12b`
  - **OpenRouter** (cloud, placené podle použití): vytvoř klíč a nastav proměnnou prostředí `OPENROUTER_API_KEY`
- Doporučeno: NVIDIA GPU (RTX 3060 12 GB a lepší), přepis je pak rychlejší

## Instalace

1. Dvakrát klikni na `install.bat`.
2. Spusť `run.bat --check`. Ukáže, co chybí (ffmpeg, GPU, Ollama, klíč).

## Použití

```
run.bat https://kick.com/.../videos/...        # klipy z VODu s titulky
run.bat "C:\videa\stream.mp4"                  # lokální soubor
run.bat --no-captions                          # bez titulků, URL vezme ze settings.yaml
run.bat --count 10                             # 10 klipů na hodinu materiálu
```

Nebo vyplň `source.url` v `settings.yaml` a spusť `run.bat` bez argumentů.

Výsledek je ve složce `output\<id-videa>\`:
- `klip_01.mp4`, `klip_02.mp4`, ... (nejlepší je první)
- `klip_01.srt` (titulky, pokud jsou zapnuté)
- `klip_01.txt` (titulek, čas ve streamu, skóre, proč AI klip vybrala)

Přepis a výběr klipů se ukládají do `work\`, takže opakované spuštění na stejném videu je rychlé. Chceš-li nový výběr AI, smaž `work\<id>\clips.json`.

## Nastavení

Všechno je v `settings.yaml` s komentáři u každé položky: délka klipů, počet klipů na hodinu, velikost a barva titulků, model přepisu, Ollama nebo OpenRouter, kvalita videa.

## Známá omezení

- Oříznutí 9:16 bere střed záběru. U streamů s kamerou v rohu nebo u dvou lidí vedle sebe může být výřez špatně. Sledování obličeje zatím není.
- AI vybírá podle řeči. Vtipy, které jsou jen vizuální a nikdo je nekomentuje, nenajde.
- Stahování z Kicku závisí na yt-dlp. Když přestane fungovat, zkus `pip install -U yt-dlp` (spusť v prostředí `.venv`).
- Titulky jsou po slovních skupinách podle času segmentů, ne přesně po jednotlivých slovech.

## Aktualizace

Tento nástroj se neaktualizuje sám. Nové verze přijdou tím, že se upraví kód v repozitáři (např. přes Claude) a stáhneš je přes `git pull`.

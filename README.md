# Gasbyn Clipper

**Verze 1.2.0** — kvalitnější a rychlejší AI klipovač pro Windows.

Vezme VOD z Kicku (nebo YouTube, nebo lokální video), AI najde momenty, každému dá **hodnocení 0 až 100** (odhadovaný potenciál views) a vystřihne vertikální klipy 9:16 s titulky. Nízké skóre samo o sobě moment nevyřadí; všechny vhodné momenty dostanou skóre 0–100.

## Co je nové v 1.2.0

- **Robustnější automatické aktualizace** (více pokusů, kontrola velikosti, bezpečnější instalace, inspirace Gasbyn Optimizerem).
- Lepší odolnost při stahování a chybách sítě.
- Výchozí nastavení optimalizovaná pro rychlost + kvalitu.
- Stabilnější pipeline a čistší progress reporting.
- Zachována plná kompatibilita s loadouty, učením z 👍/👎 a YouTube uploadem.

## Instalace (Windows 10/11)

1. Otevři stránku **Releases** a stáhni `Setup.exe`.
2. Spusť ho a projdi průvodce. Instaluje se jen pro tebe, správce není potřeba.
3. Spusť **Gasbyn Clipper** ze zástupce.

### Co je v Setup.exe a co chybí (Ready to Use)

Instalace obsahuje aplikaci, ffmpeg a všechny knihovny Pythonu. **Nevkládá** tyto tři věci, protože jsou velké a patří k tvému počítači:

| Co | Jak se to získá | Kde to vidíš |
|----|-----------------|--------------|
| Ollama (AI běžící lokálně) | Aplikace ji nabídne stažením z ollama.com | Karta **Připravenost** na první stránce |
| Model AI (`gemma3:12b`, několik GB) | Tlačítko **Stáhnout model** v kartě | Karta **Připravenost** |
| Přepisovací model Whisper (stovky MB až ~1,6 GB) | Tlačítko **Stáhnout Whisper**, jinak se stáhne při prvním přepisu | Karta **Připravenost** |

Po stažení Setup.exe tedy otevři aplikaci, na první stránce projdi kartu **Připravenost** a klikni na chybějící kroky. Když jsou všechny zelené, je hotovo. Potřebuješ internet a jednorázově pár GB místa.

Alternativa místo Ollamy: **OpenRouter** (cloud, platíš za použití). Vytvoř klíč a nastav proměnnou prostředí `OPENROUTER_API_KEY`, pak v Nastavení vyber poskytovatele *openrouter*.

Doporučeno: NVIDIA GPU (RTX 3060 12 GB a lepší). Přepis je pak výrazně rychlejší.

## Kde jsou data

Nastavení, klipy, cache, loadouty a YouTube přihlášení jsou ve složce `%APPDATA%\GasbynClipper`. Aktualizace instalátorem je nepřepisují, takže nastavení zůstane po každé aktualizaci.

## Použití

1. Vlož URL VODu nebo cestu k lokálnímu videu. Více zdrojů oddělíš středníkem `;`, zpracují se jeden po druhém.
2. Stiskni **Spustit AI Clipper**.
3. Sleduj ukazatele: **Celkem %** přes celou frontu, **Odhad** zbývajícího času a řádek **Právě** s procenty aktuálního kroku (stahování, přepis, hodnocení AI, střih).
4. Hotové klipy najdeš na stránce **Hotové klipy**: skóre, titulek, popis, hashtagy.
   Tlačítko **Upravit** otevře editor, **Přehrát** otevře klip ve výchozím přehrávači.
   Pod každým klipem jsou tlačítka **👍 Líbí se** a **👎 Nelíbí**, ze kterých se AI učí (viz níže).

### Video, typ, kategorie a loadout

Na stránce **Vytvořit klipy** vlož URL VODu (nebo cestu k souboru). Nad tlačítky najdeš:
- **Typ**: *Short-form (9:16)* nebo *Long-form*. Vybráním jednoho se druhý vypne. Short-form dělá vertikální klipy do 60 s, long-form delší klipy (délku určí AI podle VODu).
- **Kategorie** streamu: Gaming, Vlog, IRL, Reakce, Tutorial, Podcast, Sport, Hudba, Ostatní. AI podle ní hledá typické momenty.
- **Jazyk řeči**: čeština, slovenština nebo angličtina.
- **Titulky**: zapnout/vypnout.

Tlačítko **Načíst video a nastavit loadout** stáhne video, vybere vhodný snímek z celého VODu a otevře **Loadout 9:16**. Výběr snímku běží bez AI, takže je rychlý a nic se nevolá v Ollamě.
- Až 5 **záběrů** z jednoho snímku (např. kamera nahoře, hra dole). Každý táhni v náhledu rámce, nastav výřez a místo ve 9:16 (posuvníky, tažením myší nebo klávesnicí).
- **Titulky**: poloha (X, Y) a velikost písma. Text v náhledu můžeš táhnout myší.
- **Fotky** z disku, s časem, kdy se mají ukazovat.
- **Animace na začátku** pro každý záběr i fotku: Fade in, Unblur in, Třes (jen na začátku).
- **Knihovna**: loadout se uloží pod názvem a jde načíst u dalšího VODu. Poslední použitý se nabídne automaticky.

Loadout platí jen pro short-form. Pro long-form se bere celý rámec, titulky se ale nastavují stejně.

### Klávesnice

- **Ctrl + 1 až 4**: přepnutí mezi stránkami (Vytvořit klipy, Hotové klipy, Nastavení, Cache).
- **Esc**: zpět z loadoutu na Vytvořit klipy.
- **Šipky** v loadoutu posouvají vybranou vrstvu (nebo titulky), **Shift + šipka** jde po větších krocích, **Ctrl + šipka** posouvá výřez záběru.
- **+ / -** mění velikost vrstvy (nebo písma titulků), **[** a **]** přepínají vrstvy, **Delete** smaže vybranou vrstvu.
- **Šipky** na posuvníku ho posunou o krok, po kliknutí na posuvník.
- **Tab** přepíná mezi políčky. Tlačítka a přepínače jsou myší.

### Průběh a odhad

Při stahování se ukazuje **kolik GB z kolika** se stáhlo. Pod ukazatelem jsou odhady: kdy bude hotové stažení, přepis, hodnocení a celé zpracování. Aplikace při zapnutí spustí **Ollamu na pozadí**, pokud je nainstalovaná.

### Učení z hodnocení

Každý klip označený 👍 nebo 👎 se uloží do `work/learning.json`. Při dalším hodnocení AI dostane několik nedávných příkladů (počet nastavíš v sekci **Učení z hodnocení**), takže se příště trefuje do tvého stylu. Učení můžeš vypnout v Nastavení.

## Hodnocení kvality

Každý navržený klip dostane skóre 0 až 100 jako orientační potenciál zhlédnutí. Vyšší číslo znamená vyšší odhadovaný výkon. Nízké skóre moment automaticky nevyřazuje. Kritéria jsou:

| Kritérium | Co měří |
|-----------|---------|
| Hook | Zaujme hned v prvních sekundách? |
| Emoce | Smích, šok, napětí, nadšení |
| Srozumitelnost | Pochopí ho divák bez znalosti streamu? |
| Pointa | Končí vtipem nebo vyvrcholením? |
| Humor | Jak je vtipný? |
| Tempo | Heuristika z přepisu, ideál 2 až 3,2 slova za sekundu |

Váhy kritérií se nastavují automaticky podle formátu (short-form, long-form).

Hodnocení AI se ukládá do cache. Když později změníš práh nebo váhy, výběr se přepočítá bez nového volání AI. Novou AI analýzu vynutíš zaškrtnutím *Znovu zavolat AI*.

## Editor klipu

Na stránce **Hotové klipy** klikni na **Upravit**. Editor obsahuje:

- **Časovou osu**: táhni oranžové uchyty a zkrať klip zleva i zprava.
- **Seznam titulků**: uprav čas a text, smaž, nebo přidej nový titulek.
- **Název, popis a hashtagy**: upravíš je před nahráním.
- **Animace na začátku**: *Fade in*, *Unblur in* nebo *Třes*.
- **Fotka**: vlož obrázek, nastav polohu, velikost a čas zobrazení.
- **Rozložení**: otevře loadout pro existující klip.
- **Uložit a přerenderovat**: vytvoří klip znovu se změnami.

## Nahrání na YouTube

YouTube se připojuje přes oficiální YouTube Data API. Postup je v sekci Nastavení aplikace.

## Automatické aktualizace

Při startu sestavené aplikace se kontroluje nejnovější Release na GitHubu. Když je novější verze, objeví se v levém panelu oranžové tlačítko **Aktualizovat**. V Nastavení můžeš zapnout **Instalovat automaticky**.

Verze 1.2.0 má výrazně robustnější updater (opakované pokusy, kontrola velikosti, bezpečnější PowerShell skript).

## Antivirus a SmartScreen

Aplikace je zabalená z Pythonu (PyInstaller). Antiviry a Windows SmartScreen mohou u nových nebo nepodepsaných aplikací zobrazit varování. **Nezaručím, že se to nestane.**

- Build se podepisuje certifikátem, jakmile je v repozitáři secret `CODESIGN_PFX_BASE64`.
- SmartScreen: *Více informací → Přesto spustit*.

## Platformy

| Platforma | Stav |
|-----------|------|
| YouTube | Hotovo (nahrání z editoru, vyžaduje vlastní OAuth klíč) |
| TikTok / Instagram / Kick | Ruční nahrání z Průzkumníku |

## Příkazová řádka

```
python clipper.py "https://kick.com/.../videos/..."
python clipper.py stream.mp4 --no-captions
python clipper.py --check
python clipper.py --clean downloads
```

## Spuštění ze zdrojáků

```
install.bat          # vytvoří .venv a nainstaluje závislosti
run.bat              # spustí GUI
```

Potřebuješ Python 3.10+ a ffmpeg v PATH.

## Známá omezení

- Oříznutí 9:16 bere střed záběru (sledování obličeje zatím není).
- AI vybírá podle přepisu řeči – čistě vizuální vtipy nenajde.
- Stahování z Kicku závisí na yt-dlp.
- Hodnocení AI je odhad, ne záruka views.
- Editor nemá vestavěný náhled videa.

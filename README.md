# Gasbyn Clipper

AI klipovač pro Windows. Vezme VOD z Kicku (nebo YouTube, nebo lokální video), AI najde momenty, každému dá **hodnocení 0 až 100** a vystřihne vertikální klipy 9:16 s titulky. Nízké skóre samo o sobě moment nevyřadí; všechny vhodné momenty dostanou skóre 0–100.

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

Váhy kritérií se nastavují automaticky podle formátu (short-form, long-form). Odhad views se v této verzi připravuje z vlastních statistik YouTube po opětovném připojení účtu s oprávněním ke čtení.

Hodnocení AI se ukládá do cache. Když později změníš práh nebo váhy, výběr se přepočítá bez nového volání AI. Novou AI analýzu vynutíš zaškrtnutím *Znovu zavolat AI*.

## Editor klipu

Na stránce **Hotové klipy** klikni na **Upravit**. Editor obsahuje:

- **Časovou osu**: táhni oranžové uchyty a zkrať klip zleva i zprava. Klikni na titulek a zvýrazní se.
- **Seznam titulků**: uprav čas a text, smaž, nebo přidej nový titulek.
- **Název, popis a hashtagy**: upravíš je před nahráním.
- **Animace na začátku**: *Fade in*, *Unblur in* (rozostřený začátek, který se vyostří) nebo *Třes* (otřes jen na začátku, pak klid). Délku nastavíš v sekundách.
- **Fotka**: vlož obrázek (PNG, JPG, WebP), nastav polohu X a Y, velikost a v jakém čase se má zobrazovat (od–do, 0 = do konce klipu).
- **Uložit a přerenderovat**: vytvoří klip znovu se změnami. Když zdrojové video zmizelo z cache, stáhne se znovu.

Editor je jednodušší než CapCut. Náhled se přehraje v systémovém přehrávači (ne uvnitř aplikace), klip jde jen zkrátit a animace se dají dát jen na začátek.

## Nahrání na YouTube

YouTube se připojuje přes oficiální YouTube Data API. Zdarma, ale potřebuješ vlastní klíč:

1. Google Cloud Console → vytvoř projekt → zapni **YouTube Data API v3**.
2. Nastav **OAuth consent screen** a přidej svůj účet jako testovacího uživatele.
3. Vytvoř **Credentials → OAuth client ID → typ Desktop app**, stáhni JSON.
4. V Nastavení vyber ten JSON v poli *Soubor client_secret*, ulož nastavení.
5. Na stránce Nastavení klikni na **Připojit účet** a přihlas se v prohlížeči.

Pak v editoru klikni na **Nahrát na YouTube**. Po instalaci verze s personalizovaným odhadem klikni v Nastavení znovu na **Připojit účet** a potvrď nové oprávnění pro čtení statistik kanálu. Výchozí viditelnost je `private`.

**Limity, které musíš znát:**
- Denní kvóta je obvykle 10 000 jednotek a jedno nahrání stojí přibližně 1 600. Vyjde to zhruba na 6 nahrání za den.
- Dokud projekt neprojde auditem YouTube, videa se nahrají jako soukromá, bez ohledu na nastavení. Audit žádáš přes formulář v dokumentaci YouTube API.

## Automatické aktualizace

Při startu sestavené aplikace se kontroluje nejnovější Release na GitHubu. Když je novější verze, objeví se v levém panelu oranžové tlačítko **Aktualizovat**. V Nastavení můžeš zapnout **Instalovat automaticky**, pak se nová verze stáhne a nainstaluje sama a aplikace se restartuje.

## Antivirus a SmartScreen

Aplikace je zabalená z Pythonu (PyInstaller). EXE i instalátor obsahují metadata výrobce **Gasbyn**, název produktu **Gasbyn Clipper**, popis, verzi a copyright; build navíc ověřuje, že metadata v EXE odpovídají projektu. UPX komprese je vypnutá a build používá čisté sestavení bez zbytků předchozích buildů. Tato metadata nejsou digitální podpis a sama o sobě nezaručí odstranění varování. Antiviry a Windows SmartScreen mohou u nových nebo nepodepsaných aplikací stále zobrazit varování. **Nezaručím, že se to nestane.** Co se dělá:

- Build se podepisuje certifikátem, jakmile je v repozitáři secret `CODESIGN_PFX_BASE64`. Podepsaná aplikace dostává méně varování. Certifikát stojí peníze, nebo jej lze získat zdarma přes SignPath Foundation pro open source.
- Když se objeví falešný poplach, pošli soubor na analýzu: microsoft.com/wdsi (Microsoft Defender) a virustotal.com (kontrola několika antivirů).
- SmartScreen: *Více informací → Přesto spustit*.

## Platformy

| Platforma | Stav |
|-----------|------|
| YouTube | Hotovo (nahrání z editoru, vyžaduje vlastní OAuth klíč) |
| TikTok | Není hotovo. Oficiální upload API vyžaduje schválení aplikace. |
| Instagram | Není hotovo. Vyžaduje účet typu Business nebo Creator a schválení aplikace u Mety. |
| Kick | Není hotovo. Kick nemá veřejné API pro nahrávání videa. |

Klipy a popisy můžeš nahrát na TikTok, Instagram a Kick ručně z Průzkumníku.

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
- AI vybírá podle přepisu řeči. Vtipy, které jsou jen vizuální a nikdo je nekomentuje, nenajde.
- Stahování z Kicku závisí na yt-dlp. Když přestane fungovat, zkus aktualizaci yt-dlp, nebo vlož cookies v nastavení.
- Hodnocení AI je odhad. Skóre 0 až 100 neznamená, že klip bude mít úspěch.
- Editor nemá vestavěný náhled videa a nelze v něm klip prodloužit.
- Loadout zatím neotáčí záběry a nepřidává přechody mezi nimi. Náhled je statický, animace uvidíš až ve výsledném klipu.
- Vyhledávání videí na Kicku bylo odstraněno, protože neoficiální API nefungovalo spolehlivě. Video vlož přes URL (zkopíruj adresu VODu z Kicku).
- Ollama a model AI instalační program nezabalí. Stahují se z oficiálních zdrojů až při prvním spuštění, takže bez internetu nejde klipovat.
- Odhad času je jen odhad z dosavadního tempa a při prvním běhu (stahování modelů) bývá méně přesný.

# Deszkavízió napi digest

Minden reggel automatikusan összegyűjti a [deszkavizio.hu](https://deszkavizio.hu)
előző napon megjelent cikkeit, a cikk borítóképét, címét, szerzőjét és rovatát
beilleszti a megadott sablonba, majd e-mailben elküldi a képeket a cikkek
linkjeivel együtt - egyszerre több címzettnek is.

## Hogyan működik

```
scraper.py     -> lekéri a tegnapi cikkeket (WordPress REST API, HTML-fallback)
renderer.py    -> minden cikkhez legyárt egy sablonba illesztett képet (Pillow)
image_host.py  -> a képeket a repóba menti (images/latest/), mert a Brevo
                  csak nyilvános URL-ről tud képet betölteni, cid-et nem
emailer.py     -> összeállítja és elküldi az e-mailt (Brevo)
main.py        -> "render" és "send" alparancs - a kettő közé a workflow
                  egy git push-t iktat be, hogy a képek linkje már éljen,
                  mire az e-mail kimegy
```

## 1. Első beüzemelés

### 1.1 Brevo fiók és API kulcs

Miért Brevo és nem Resend/SendGrid/MailerSend? Mert nincs saját domained -
a Brevónál nem kell egész domaint hitelesíteni, elég egyetlen feladó
e-mail címet (akár egy sima Gmail-cím is jó), és utána bármelyik
címzettnek küldhetsz vele, nem csak magadnak.

1. Regisztrálj a [brevo.com](https://www.brevo.com) oldalon (ingyenes
   csomag: napi 300 e-mail - a napi 1 digestnél ez bőven elég, nem kell
   bankkártya).
2. **Settings → Senders, Domains & Dedicated IPs → Senders → Add a
   Sender**: add meg azt az e-mail címet, ahonnan a digest menne (ez lehet
   a saját, meglévő e-mail címed is). Brevo küld rá egy megerősítő linket
   - kattints rá.
3. **Settings → API Keys → Generate a new API key**: hozz létre egy
   kulcsot. **Ezt csak egyszer mutatja meg**, másold ki azonnal.

### 1.2 A repó feltöltése GitHubra - FONTOS: legyen PUBLIKUS

Töltsd fel ezt a mappát egy **publikus** GitHub repóba. A struktúra
maradjon, ahogy van (`src/`, `templates/`, `fonts/`, `images/`,
`.github/workflows/`).

A repónak azért kell publikusnak lennie, mert a generált képeket a
`raw.githubusercontent.com`-on keresztül hivatkozzuk be az e-mailben (ez
váltja ki a Brevo hiányzó cid-támogatását) - egy privát repóból ezek a
linkek jelszó/token nélkül nem töltődnének be a címzettek levelezőjében,
így csak törött-kép ikont látnának.

Ha ez neked nem elfogadható (pl. nem szeretnéd, hogy a cikkcímek/szerzők
egy publikus repóban látszódjanak a képekben), szólj, és átállítjuk másik
megoldásra (pl. vissza egy domain-alapú, valódi cid-et támogató
szolgáltatóra).

### 1.3 GitHub Secrets beállítása

A repóban: **Settings → Secrets and variables → Actions → New repository secret**,
és vedd fel az alábbi hármat:

| Secret neve         | Érték                                                                 |
|----------------------|------------------------------------------------------------------------|
| `BREVO_API_KEY`      | az 1.1-ben létrehozott API kulcs                                       |
| `DIGEST_EMAIL_FROM`  | az 1.1-ben hitelesített feladó e-mail cím                              |
| `DIGEST_EMAIL_TO`    | a címzettek, **vesszővel elválasztva** (pl. `en@pelda.hu, baratom@pelda.hu, harmadik@pelda.hu`) |

Ezeket **soha ne írd bele kódba vagy a repóba** — a workflow env változóként
olvassa be a secretekből (lásd `.github/workflows/daily-digest.yml`).

A `permissions: contents: write` már be van állítva a workflow-fájlban -
enélkül a képek commitolása/pusholása nem sikerülne.

### 1.4 Ütemezés

A workflow alapból minden nap **05:00 UTC**-kor fut, ami reggel **7:00**-nak
felel meg magyar nyári időszámítás szerint (kb. március vége - október
vége - az év nagy részében), és 6:00-nak télen, mert a GitHub cron mindig
UTC-ben számol, és nem igazodik a magyar óraátállításhoz. Ha ez a kb. 1
órás téli csúszás zavaró, a
`.github/workflows/daily-digest.yml` fájlban a `cron` sort módosítsd.

Kézi indítás teszthez: a repó **Actions** fülén → *Napi Deszkavízió digest* →
**Run workflow** (itt meg is adhatsz egy konkrét dátumot, ha nem a tegnapi
napra akarod lefuttatni).

## 2. Helyi tesztelés (mielőtt élesítenéd)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cd src

# 1) csak legenerálja a képeket lokálisan, nem nyúl a repóhoz, nem küld e-mailt:
python main.py render --dry-run --date 2026-09-15
# -> src/dry_run_output/ mappában megnézheted, mielőtt bármi e-mailt küldenél

# 2) éles teszt: renderelés a repóba mentve + tényleges e-mail küldés
export BREVO_API_KEY=...
export DIGEST_EMAIL_FROM=...
export DIGEST_EMAIL_TO=...
export GITHUB_REPOSITORY=felhasznalo/repo-nev   # ugyanaz, mint amit a GitHub-ra feltöltesz
export GITHUB_REF_NAME=main

python main.py render --date 2026-09-15
git add ../images/latest && git commit -m "teszt kép" && git push   # a repódnak léteznie/publikusnak kell lennie
python main.py send
```

Élesben a GitHub Actions workflow végzi el ugyanezt a három lépést
(render → push → send) automatikusan, minden nap.

## 3. A sablon: a Te 7 saját képed, változtatás nélkül

A `templates/` mappában van mind a hét sablonod egy az egyben
(`template_szinhaz.jpg`, `template_mozgokep.jpg`, `template_tanc.jpg`,
`template_opera.jpg`, `template_zene.jpg`, `template_kepzomuveszet.jpg`,
`template_konyv.jpg`). Futásidőben ezekhez **kizárólag két dolog** kerül
hozzá:
1. a cikk borítóképe a fotó-helyre (ugyanoda, ahova a mintaképeden a
   színes átmenetes placeholder van),
2. a szerző (dőlt) és a cikk címe (félkövér) a panel üres részén, a
   rovat-címke színéhez illő tónusban.

Minden más - a fejléc, a logó, a panel-textúra, a "liquid glass"
rovat-címke a benne lévő felirattal együtt - pontosan az marad, amit
küldtél, mert maga a JPEG kerül alapként felhasználásra.

### Ha frissítenéd valamelyik sablont

Cseréld le a megfelelő fájlt a `templates/` mappában **pontosan ugyanazzal
a névvel** (pl. `template_zene.jpg`), ugyanolyan 945×2048-as méretben, és
kész is - nincs más teendő. Ha a fotó-hely vagy a szöveg pozíciója is
máshol lenne az új változatban, azt a `src/config.py` tetején lévő
`LAYOUT` szótárban (`photo_box`, `author`, `title`) tudod pixelben
finomhangolni.

Ha egy vadonatúj rovathoz kapsz sablont, két helyen kell felvenned:
```python
# src/config.py
CATEGORY_TEMPLATE_FILES["Új rovat"] = os.path.join(TEMPLATE_DIR, "template_uj_rovat.jpg")
ACCENT_COLORS["Új rovat"] = (piros, zöld, kék)  # a cím/szerző szövegszíne
```

### Betűtípus: Urbanist

A cím **félkövér**, fehér; a szerző **dőlt**, szintén fehér, Urbanist
betűtípussal. A
tényleges betűtípus-fájlokat licenc okokból nem mellékeltem a csomagba -
ehelyett a `fonts/fetch_fonts.py` szkript tölti le hivatalos forrásból
(a Google Fonts `google/fonts` GitHub tárolójából), és ezt a GitHub
Actions workflow minden éles futás előtt automatikusan lefuttatja. Nincs
vele teendőd.

Ha mégis kézzel akarnád telepíteni (pl. helyi teszteléshez, mielőtt
felraknád a repót): futtasd le
```bash
python fonts/fetch_fonts.py
```
Ez internetkapcsolatot igényel. Ha bármiért nem sikerülne (pl. megváltozna
az elérési út a Google Fonts tárolójában), a rendszer automatikusan a
gépre/CI-be beépített **DejaVu Sans**-ra esik vissza - ez sosem állítja
meg a digest küldését, csak a betűtípus lesz kicsit más, amíg nem
javítod a linket vagy nem töltöd fel kézzel a fájlokat a `fonts/` mappába
`Urbanist-Regular.ttf`, `Urbanist-Bold.ttf`,
`Urbanist-Italic.ttf` néven.

## 4. Amit érdemes tudni / korlátok

- **Elsődlegesen a WordPress REST API-t használja** (`/wp-json/wp/v2/posts`),
  ez a legtöbb WordPress oldalon alapból be van kapcsolva, és egy hívásból
  megadja a címet, szerzőt, kategóriát és a borítóképet is.
- **HTML-fallback** akkor lép életbe, ha a REST API bármiért nem elérhető.
  Ezt nem tudtam éles hálózati kapcsolattal tesztelni (ez a fejlesztői
  környezet nem ér el külső oldalakat), ezért ha erre kerülne sor, előfordulhat,
  hogy a `scraper.py` `_fetch_via_html` részében a CSS-szelektorokat
  (`.author`, `.byline`, stb.) finomítani kell az oldal tényleges HTML
  szerkezetéhez. Első pár futtatásnál érdemes `--dry-run`-nal ellenőrizni,
  hogy tényleg a REST API-t használja-e (ezt logolja is: *"REST API-n
  keresztül X cikk"*).
- Ha egy adott napon nincs cikk, alapból küld egy rövid "nincs cikk" e-mailt
  (`SEND_EMPTY_DIGEST_NOTICE = True` a config.py-ban) — ha inkább néma
  maradjon ilyenkor, állítsd `False`-ra.
- A rendszer időzónája Europe/Budapest — a "tegnap" mindig ehhez képest
  értendő, függetlenül attól, hogy a GitHub szervere UTC-ben fut.
- **A képek linkje "él", nem statikus.** Mivel a Brevo nem tud valódi
  beágyazott (cid) képet kezelni, a képeket a repóból hosztoljuk, és a
  fájlneveket (`0.jpg`, `1.jpg`, ...) minden nap felülírjuk. Ha valaki egy
  régebbi digest-e-mailt nyit meg újra, ott már a közben felülírt, aznapi
  kép fog megjelenni - ha a digestet a beérkezése napján olvassátok el, ez
  nem probléma.
- **A repónak publikusnak kell lennie** (lásd 1.2), különben a
  raw.githubusercontent.com linkek nem töltődnek be a címzettek
  levelezőjében.
- Több címzett: a `DIGEST_EMAIL_TO` secret vesszővel elválasztva
  tetszőleges számú e-mail címet tartalmazhat (Brevón egy tranzakciós
  e-mailnél 99 címzettig, ez bőven elég).

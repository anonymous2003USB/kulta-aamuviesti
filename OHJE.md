# Kullan aamuviesti Telegramiin – käyttöönotto

Tämä lähettää sinulle joka arkiaamu noin klo 8.15 (talviaikaan 7.15) viestin, jossa on:

- tuleeko kullasta tänään iso vai rauhallinen päivä
- tämän päivän isot USD-julkaisut Suomen ajassa (esim. työllisyysraportti klo 15.30)
- todennäköisyys, että hinta karkaa 30 $, 50 $ tai 100 $ johonkin suuntaan
- kuinka kaukana stopin kannattaa vähintään olla, ja paljonko pienin kauppa voi hävitä

Viesti ei kerro suuntaa. Se on tarkoitettu siihen, että tiedät aamulla, millainen päivä on tulossa.

Käyttöönotto vie noin 20 minuuttia. Tarvitset Telegramin ja tietokoneen selaimen.

---

## Osa 1: Tee Telegram-botti (5 min)

1. Avaa Telegram ja kirjoita hakuun **@BotFather**. Valitse se, jonka nimen vieressä on sininen merkki.
2. Paina **Start**. Kirjoita `/newbot` ja lähetä.
3. BotFather kysyy nimeä. Kirjoita esimerkiksi `Kulta aamuviesti`.
4. Se kysyy käyttäjänimeä, jonka pitää loppua sanaan `bot`. Kirjoita esimerkiksi `gjv_kulta_bot`.
   Jos nimi on varattu, kokeile toista.
5. BotFather antaa pitkän koodin, joka näyttää tältä: `123456789:ABCdefGhIJKlmNoPQRstuVWXyz`.
   **Tämä on botin salasana (token).** Kopioi se talteen. Älä näytä sitä kenellekään.
6. BotFatherin viestissä on linkki uuteen bottiisi (`t.me/...`). Avaa se ja paina **Start**.
   Kirjoita botille vaikka `hei`. Tämä on pakollista, muuten botti ei saa lähettää sinulle viestejä.

## Osa 2: Hae oma chat-numerosi (2 min)

1. Kirjoita selaimen osoiteriville tämä, mutta vaihda `TOKEN` tilalle osan 1 koodi:
   `https://api.telegram.org/botTOKEN/getUpdates`
   Esimerkki: `https://api.telegram.org/bot123456789:ABCdefGhIJ/getUpdates`
2. Sivulla näkyy tekstiä. Etsi kohta `"chat":{"id":` ja sen perässä oleva numero, esim. `"chat":{"id":987654321`.
   **Tämä numero on chat-numerosi.** Kopioi se talteen.
3. Jos sivulla lukee vain `"result":[]`, lähetä botille uusi viesti Telegramissa ja päivitä sivu.

## Osa 3: Tee GitHub-tili ja kansio (5 min)

1. Mene osoitteeseen **github.com** ja paina **Sign up**. Tee ilmainen tili.
2. Kun olet kirjautunut, paina oikeasta yläkulmasta **+** ja valitse **New repository**.
3. Kirjoita kohtaan *Repository name*: `kulta-aamuviesti`.
4. Valitse **Private** (yksityinen). Muuta ei tarvitse muuttaa.
5. Paina **Create repository**.

## Osa 4: Lataa tiedostot GitHubiin (3 min)

1. Pura `kulta-aamuviesti.zip` omalle koneellesi. Saat kansion `kulta-aamuviesti`.
2. GitHubin uudella sivulla paina linkkiä **uploading an existing file**.
3. Avaa purettu kansio tiedostoselaimessa. Valitse kaikki sen sisällä olevat tiedostot ja kansiot
   (myös kansio `.github`) ja raahaa ne GitHubin sivulle.
4. Paina alhaalta **Commit changes**.
5. Tarkista, että sivulla näkyvät: `.github`, `aamuviesti.py`, `isoliike.py`, `liikekartta.py`,
   `requirements.txt` ja `OHJE.md`.

**Jos `.github`-kansio puuttuu** (joskus raahaus jättää sen pois):
paina **Add file → Create new file**, kirjoita nimeksi `.github/workflows/aamuviesti.yml`,
liitä tekstikenttään tiedoston `aamuviesti.yml` sisältö (avaa se Muistiolla) ja paina **Commit changes**.

## Osa 5: Anna GitHubille Telegram-tiedot (3 min)

1. Paina GitHub-kansiosi yläpalkista **Settings**.
2. Vasemmalta **Secrets and variables → Actions**.
3. Paina **New repository secret**:
   - Name: `TELEGRAM_TOKEN`
   - Secret: osan 1 koodi
   - Paina **Add secret**.
4. Paina uudelleen **New repository secret**:
   - Name: `TELEGRAM_CHAT_ID`
   - Secret: osan 2 numero
   - Paina **Add secret**.

## Osa 6: Kokeile heti (2 min)

1. Paina yläpalkista **Actions**. Jos GitHub kysyy, paina vihreää nappia, joka sallii työnkulut.
2. Valitse vasemmalta **Aamuviesti**.
3. Paina oikealta **Run workflow** ja sitten vihreää **Run workflow**.
4. Odota noin minuutti. Viesti tulee Telegramiin.
5. Jos tulee punainen rasti ❌, paina sitä, sitten **viesti**, ja ota kuvakaappaus Claudelle.

Valmis. Tästä eteenpäin viesti tulee joka arkiaamu itsestään.

---

## Omat asetukset (vapaaehtoinen)

Oletuksena viesti laskee kauppakoon 1 000 $:n tilille 1 %:n riskillä ja näyttää rajat 30, 50 ja 100 $.
Muuttaaksesi: **Settings → Secrets and variables → Actions → Variables → New repository variable**:

| Name | Esimerkki | Mitä tekee |
|---|---|---|
| `TILI` | `2500` | tilisi koko dollareina |
| `RISKI` | `0.5` | montako prosenttia tilistä saa hävitä yhdessä kaupassa |
| `RAJAT` | `30,50,100` | liikerajat dollareina (asetettu suoraan tiedostoon `.github/workflows/aamuviesti.yml`, muuttuja ei vaikuta) |

## Hyvä tietää

- **Myöhästyminen:** GitHub voi ruuhka-aikoina ajaa ajastetun työn jonkin verran myöhässä.
- **Hinta** tulee Yahoosta (kultafutuuri GC=F) noin 10 minuutin viiveellä. Ennuste käyttää edellisten
  päivien valmista dataa, joten viive ei vaikuta siihen.
- **Kauppakoko** olettaa, että 1 lotti on 100 unssia. Tarkista välittäjältäsi.
- **Jos Yahoo tai kalenteri ei vastaa,** viesti tulee silti ja kertoo, mikä puuttuu.
- **Ilmainen:** yksityisessä kansiossa GitHub antaa ilmaisia ajominuutteja kuukaudessa. Yksi ajo vie noin
  minuutin, joten noin 22 ajoa kuukaudessa mahtuu niihin hyvin.
- **Lopettaminen:** Actions → Aamuviesti → oikealta **…** → **Disable workflow**.

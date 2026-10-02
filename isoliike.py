"""Iso liike -testi.

Kysymys 1: Tiedämmekö aamulla etukäteen, tuleeko päivästä iso (hinta liikkuu vähintään 1,25 %
           yhteen suuntaan)?
Kysymys 2: Jos iso päivä on tulossa, saammeko suunnan kiinni yksinkertaisella murtumasäännöllä,
           ja jääkö kulujen jälkeen voittoa?

Käyttö:
    python isoliike.py                                               # kulta (GC=F)
    python isoliike.py --tunnus SI=F --spread 0.03 --liukuma 0.01    # toistotesti hopealla

SÄÄNNÖT ON LUKITTU ENNEN TESTIÄ (2.10.2026). Niitä ei muuteta tulosten näkemisen jälkeen.
"""
import argparse
import json
import math
import sys
import time

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Lukitut säännöt (kaikki ajat UTC)
# ---------------------------------------------------------------------------
ISO = 0.0125            # iso päivä: hinta liikkuu klo 07–21 vähintään 1,25 % klo 07 hinnasta yhteen suuntaan
ERITTAIN_ISO = 0.025    # erittäin iso päivä: 2,5 %
AASIA = range(0, 7)     # Aasian sessio klo 00–07: tämän ylin ja alin hinta ovat murtumatasot
KAUPPA = range(7, 21)   # kaupankäyntiaika klo 07–21 (viimeinen tuntikynttilä alkaa 20:00)
VIIMEINEN_AVAUS = 17    # uusi kauppa vain kynttilässä, joka alkaa ennen klo 17
EWMA_PAIVAT = 20        # ennuste = edellisten päivien liikkeiden painotettu keskiarvo (20 päivää)
VERTAILU_PAIVAT = 250   # "iso päivä" -ennuste = ennuste on yli edellisten 250 päivän mediaanin
MIN_HISTORIA = 40       # ennustetta ei käytetä ennen kuin vertailuhistoriaa on 40 päivää
MIN_STOPPI = 0.003      # stopin etäisyys vähintään 0,3 % hinnasta
TAVOITE = ISO           # tavoite: 1,25 % sisäänmenohinnasta

RISKIT = [0.01, 0.02, 0.05]


# ---------------------------------------------------------------------------
# Muotoilu
# ---------------------------------------------------------------------------
def luku(x, d=2):
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def pros(x, d=1):
    return luku(x * 100, d) + " %"


def etu(x, d=2):
    return ("+" if x >= 0 else "") + luku(x, d)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def hae(tunnus):
    import yfinance as yf

    raaka, virhe = None, None
    for yritys in range(3):
        try:
            raaka = yf.Ticker(tunnus).history(interval="60m", period="729d", auto_adjust=False)
            if raaka is not None and not raaka.empty:
                break
        except Exception as e:  # Yahoo hylkää välillä pyyntöjä hetkeksi
            virhe = e
        if yritys < 2:
            print("Yahoo ei vastannut, yritetään uudelleen 30 sekunnin päästä...", flush=True)
            time.sleep(30)
    if raaka is None or raaka.empty:
        raise RuntimeError(f"Yahoo ei antanut dataa ({virhe}). Kokeile 10 minuutin päästä uudelleen.")

    df = raaka.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    df.index = df.index.tz_convert("UTC").tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[(df["high"] >= df["low"]) & (df["close"] > 0)]


def paivat(df):
    """Yksi rivi per kauppapäivä: Aasian session ylin ja alin, klo 07 hinta, päivän liike ja kynttilät."""
    nyt = pd.Timestamp.now(tz="UTC").tz_localize(None)
    tanaan = nyt.normalize()
    # Tämä päivä on valmis, kun kaupankäyntiaika on päättynyt ja Yahoon viive (noin 10 min) on kulunut.
    tanaan_valmis = nyt >= tanaan + pd.Timedelta(hours=KAUPPA.stop, minutes=30)
    rivit = []
    for paiva, d in df.groupby(df.index.normalize()):
        if paiva.weekday() >= 5 or paiva > tanaan or (paiva == tanaan and not tanaan_valmis):
            continue
        tunnit = d.index.hour
        a = d[np.isin(tunnit, list(AASIA))]
        k = d[np.isin(tunnit, list(KAUPPA))]
        if len(a) < 5 or len(k) < 10 or k.index[0].hour != 7:
            continue
        p0 = float(k["open"].iloc[0])
        liike = max(float(k["high"].max()) - p0, p0 - float(k["low"].min())) / p0
        rivit.append({
            "paiva": paiva,
            "p0": p0,
            "yla": float(a["high"].max()),
            "ala": float(a["low"].min()),
            "liike": liike,
            "kynttilat": k.assign(tunti=k.index.hour).reset_index(drop=True),
        })
    if not rivit:
        raise RuntimeError("Datasta ei saatu yhtään kelvollista kauppapäivää.")
    return pd.DataFrame(rivit).set_index("paiva")


def ennusta(p):
    """Lisää ennusteen. Jokainen arvo lasketaan vain päivää edeltävästä tiedosta."""
    p = p.copy()
    p["ennuste"] = p["liike"].shift(1).ewm(span=EWMA_PAIVAT, adjust=False, min_periods=EWMA_PAIVAT).mean()
    raja = p["ennuste"].shift(1).rolling(VERTAILU_PAIVAT, min_periods=MIN_HISTORIA).median()
    p["iso_paiva"] = p["ennuste"] >= raja
    return p[raja.notna() & p["ennuste"].notna()]


# ---------------------------------------------------------------------------
# Kauppasimulaatio
# ---------------------------------------------------------------------------
def kauppa(rivi, spread, liukuma):
    """Aasian session murtuminen. Palauttaa sanakirjan tai None, jos kauppaa ei tullut.

    Varovaiset oletukset, kun tuntikynttilä ei kerro järjestystä:
      - jos sama kynttilä ylittää ylärajan JA alittaa alarajan ennen kauppaa -> tappio (-1 R)
      - jos kauppakynttilä tai myöhempi kynttilä koskettaa sekä stoppia että tavoitetta -> tappio
    """
    yla, ala, p0 = rivi["yla"], rivi["ala"], rivi["p0"]
    if (yla - ala) / p0 >= TAVOITE:
        return {"tila": "ohitettu"}  # liike tapahtui jo yöllä

    suunta = None
    for _, b in rivi["kynttilat"].iterrows():
        if suunta is None:
            if b["tunti"] >= VIIMEINEN_AVAUS:
                return None
            ylos, alas = b["high"] >= yla, b["low"] <= ala
            if not (ylos or alas):
                continue
            suunta = 1 if ylos else -1
            if suunta == 1:
                sisaan = max(yla, b["open"]) + liukuma
                etaisyys = max(sisaan - ala, MIN_STOPPI * p0)
            else:
                sisaan = min(ala, b["open"]) - liukuma
                etaisyys = max(yla - sisaan, MIN_STOPPI * p0)
            stoppi = sisaan - suunta * etaisyys
            tavoite = sisaan + suunta * TAVOITE * p0
            riski = etaisyys + liukuma + spread  # tappio unssia kohden, jos stoppi osuu
            if ylos and alas:
                return _tulos(suunta, sisaan, stoppi - suunta * liukuma, spread, riski, "molemmat samassa")
        osui_stoppi = b["low"] <= stoppi if suunta == 1 else b["high"] >= stoppi
        osui_tavoite = b["high"] >= tavoite if suunta == 1 else b["low"] <= tavoite
        if osui_stoppi:
            return _tulos(suunta, sisaan, stoppi - suunta * liukuma, spread, riski, "stoppi")
        if osui_tavoite:
            return _tulos(suunta, sisaan, tavoite, spread, riski, "tavoite")
    if suunta is None:
        return None
    return _tulos(suunta, sisaan, float(rivi["kynttilat"]["close"].iloc[-1]), spread, riski, "aika")


def _tulos(suunta, sisaan, ulos, spread, riski, syy):
    usd = suunta * (ulos - sisaan) - spread
    return {"tila": "kauppa", "suunta": suunta, "usd": usd, "R": usd / riski, "poistuminen": syy}


# ---------------------------------------------------------------------------
# Tilastot
# ---------------------------------------------------------------------------
def osuusvali(k, n):
    p = k / n
    v = 1.96 * math.sqrt(max(p * (1 - p), 1e-12) / n)
    return p, p - v, p + v


def keskiarvovali(x):
    x = np.asarray(x, float)
    if len(x) < 2:
        return float("nan"), float("nan"), float("nan")
    m = x.mean()
    v = 1.96 * x.std(ddof=1) / math.sqrt(len(x))
    return m, m - v, m + v


def ero_vali(a, b):
    """Ison päivän osuuksien ero ryhmien a ja b välillä (a - b) ja sen 95 %:n väli."""
    pa, pb = a.mean(), b.mean()
    v = 1.96 * math.sqrt(pa * (1 - pa) / len(a) + pb * (1 - pb) / len(b))
    return pa - pb, pa - pb - v, pa - pb + v


def puoliskot(p):
    puoli = len(p) // 2
    return p.iloc[:puoli], p.iloc[puoli:]


def pisin_putki(r):
    paras = nyt = 0
    for x in r:
        nyt = nyt + 1 if x <= 0 else 0
        paras = max(paras, nyt)
    return paras


def pudotus_R(r):
    kum = np.r_[0.0, np.cumsum(r)]
    return float((kum - np.maximum.accumulate(kum)).min())


def pudotus_tili(r, riski):
    tili = np.cumprod(1 + riski * np.asarray(r, float))
    huippu = np.maximum.accumulate(np.r_[1.0, tili])[1:]
    return float((tili / huippu - 1).min()), float(tili[-1] - 1)


# ---------------------------------------------------------------------------
# Raportti
# ---------------------------------------------------------------------------
def osa1(p, hinta):
    iso = (p["liike"] >= ISO).astype(float)
    eiso = (p["liike"] >= ERITTAIN_ISO).astype(float)
    kyl, ei = p["iso_paiva"], ~p["iso_paiva"]

    print("OSA 1: TIEDÄMMEKÖ AAMULLA, TULEEKO ISO LIIKE?")
    print(f"  Iso liike = hinta liikkuu klo 07–21 UTC vähintään {pros(ISO, 2)} yhteen suuntaan "
          f"(nykyhinnalla noin {luku(ISO * hinta, 0)} $).")
    print(f"  Ennuste aamulla: edellisten päivien liikkeiden keskiarvo. \"Iso päivä\" = ennuste yli normaalin.")
    print()
    print(f"  {'':<38}{'Iso liike':>12}{'Erittäin iso':>15}{'Päiviä':>9}")
    for nimi, m in [("Kaikki päivät", slice(None)), ("Ennuste: \"iso päivä\"", kyl), ("Ennuste: \"rauhallinen\"", ei)]:
        print(f"  {nimi:<38}{pros(iso[m].mean()):>12}{pros(eiso[m].mean()):>15}{int(iso[m].count()):>9}")
    ero, ala, yla = ero_vali(iso[kyl], iso[ei])
    print(f"  Ero (iso päivä − rauhallinen):        {etu(ero * 100, 1)} %-yks.   (95 % väli {etu(ala * 100, 1)} … {etu(yla * 100, 1)})")

    erot = []
    for nimi, osa in zip(["Alkupuolisko", "Loppupuolisko"], puoliskot(p)):
        i = (osa["liike"] >= ISO).astype(float)
        e = i[osa["iso_paiva"]].mean() - i[~osa["iso_paiva"]].mean()
        erot.append(e)
        print(f"  {nimi:<38}ero {etu(e * 100, 1)} %-yks.   ({osa.index[0]:%d.%m.%Y} – {osa.index[-1]:%d.%m.%Y})")

    viidennes = pd.qcut(p["ennuste"].rank(method="first"), 5, labels=False)
    print("  Ennusteen viidennekset, rauhallisin → isoin (kuvaileva):  "
          + "  ".join(pros(iso[viidennes == q].mean(), 0) for q in range(5)))

    lapi = ala > 0 and all(e > 0 for e in erot)
    print(f"  OSA 1: {'LÄPI' if lapi else 'EI LÄPI'}")
    return lapi


def tilasto_rivit(nimi_a, ra, nimi_b, rb):
    def solu(r, f):
        return f(r) if len(r) else "–"

    rivit = [
        ("Kauppoja", lambda r: str(len(r))),
        ("Voitollisia", lambda r: pros(float((np.asarray(r) > 0).mean()), 0)),
        ("Keskitulos / kauppa (R)", lambda r: etu(keskiarvovali(r)[0])),
        ("  95 % väli", lambda r: f"{etu(keskiarvovali(r)[1])} … {etu(keskiarvovali(r)[2])}"),
        ("Pisin tappioputki", lambda r: f"{pisin_putki(r)} kauppaa"),
        ("Suurin pudotus (R)", lambda r: luku(pudotus_R(r), 1)),
    ]
    print(f"  {'':<28}{nimi_a:>22}{nimi_b:>26}")
    for nimi, f in rivit:
        print(f"  {nimi:<28}{solu(ra, f):>22}{solu(rb, f):>26}")


def osa2(p, spread, liukuma, hinta):
    tulokset = {}
    for paiva, rivi in p.iterrows():
        t = kauppa(rivi, spread, liukuma)
        if t is not None:
            tulokset[paiva] = t
    k = pd.DataFrame.from_dict(tulokset, orient="index")
    ohitettu = int((k["tila"] == "ohitettu").sum()) if len(k) else 0
    k = k[k["tila"] == "kauppa"] if len(k) else k
    k = k.join(p[["iso_paiva"]])
    kaikki, iso = k, k[k["iso_paiva"]]

    print("OSA 2: SAADAANKO SUUNTA KIINNI? (Aasian session murtuminen)")
    print("  Osto, kun hinta ylittää klo 00–07 UTC ylimmän hinnan. Myynti, kun se alittaa alimman.")
    print(f"  Stoppi vastakkaisella reunalla (vähintään {pros(MIN_STOPPI, 1)}), tavoite {pros(TAVOITE, 2)}, "
          "kauppa kiinni viimeistään klo 21 UTC.")
    print(f"  Kulut: spread {luku(spread)} $ + liukuma {luku(liukuma)} $ jokaisessa stop-toimeksiannossa.")
    print(f"  R = summa, jonka häviät, jos stoppi osuu. +0,20 R = keskimäärin 20 % siitä takaisin voittona per kauppa.")
    print(f"  Ohitettuja päiviä (Aasian sessiossa jo yli {pros(TAVOITE, 2)} liike): {ohitettu}")
    print()
    tilasto_rivit("Kaikki päivät", kaikki["R"].to_numpy(), "Vain \"iso päivä\" -päivät", iso["R"].to_numpy())

    if len(iso):
        jakauma = iso["poistuminen"].value_counts()
        print("  Poistumiset (iso päivä): " + ", ".join(f"{a} {b}" for a, b in jakauma.items()))
        usd = iso["usd"].mean()
        print(f"  Keskitulos unssia kohden (iso päivä): {etu(usd)} $")

    puoli_m = []
    for nimi, osa in zip(["Alkupuolisko", "Loppupuolisko"], puoliskot(iso)):
        m = osa["R"].mean() if len(osa) else float("nan")
        puoli_m.append(m)
        print(f"  {nimi:<28}keskitulos {etu(m)} R   (n = {len(osa)})")

    m, ala, _ = keskiarvovali(iso["R"].to_numpy()) if len(iso) >= 2 else (float("nan"),) * 3
    lapi = len(iso) >= 30 and ala > 0 and all(x > 0 for x in puoli_m)
    print(f"  OSA 2: {'LÄPI' if lapi else 'EI LÄPI'}")

    if len(iso) >= 2:
        print()
        print("MITÄ VIPU TEKEE (\"iso päivä\" -kaupat tässä järjestyksessä)")
        for r in RISKIT:
            dd, loppu = pudotus_tili(iso["R"].to_numpy(), r)
            print(f"  Riski {pros(r, 0):>5} tilistä per kauppa  →  pahin pudotus {pros(dd, 0):>7}   lopputulos {etu(loppu * 100, 0)} %")
    return lapi, (m, ala)


def main():
    j = argparse.ArgumentParser(description="Iso liike -testi")
    j.add_argument("--tunnus", default="GC=F")
    j.add_argument("--spread", type=float, default=0.50, help="spread dollareina")
    j.add_argument("--liukuma", type=float, default=0.20, help="liukuma per stop-toimeksianto dollareina")
    a = j.parse_args()

    df = hae(a.tunnus)
    p = ennusta(paivat(df))
    if len(p) < 100:
        raise RuntimeError(f"Liian vähän testipäiviä ({len(p)}).")
    hinta = float(df["close"].iloc[-1])

    print("=" * 76)
    print(f"  ISO LIIKE -TESTI – {a.tunnus}, 1 h kynttilät")
    print(f"  Testijakso: {p.index[0]:%d.%m.%Y} – {p.index[-1]:%d.%m.%Y}, {len(p)} kauppapäivää")
    print("=" * 76)
    l1 = osa1(p, hinta)
    print()
    l2, _ = osa2(p, a.spread, a.liukuma, hinta)
    print()
    print("JOHTOPÄÄTÖS")
    if l1 and l2:
        print("  Molemmat osat läpi. Seuraavaksi sama sääntö muuttamattomana toisella markkinalla (toistotesti).")
    elif l1:
        print("  Ison liikkeen tulon voi ennustaa, mutta murtumasääntö ei saa suuntaa kiinni kulujen jälkeen.")
        print("  Älä käy kauppaa tällä säännöllä. Ennustetta voi silti käyttää kauppakoon pienentämiseen.")
    else:
        print("  Ison liikkeen tuloa ei voinut ennustaa tällä menetelmällä. Älä käy kauppaa tällä säännöllä.")
    print("  Huom: Yahoon GC=F on kultafutuuri, ei välittäjäsi XAUUSD. Tuntikynttilöissä epäselvät tilanteet")
    print("  on laskettu tappioiksi, joten todellinen tulos voi olla hieman parempi, ei paljon.")
    print("=" * 76)

    with open(f"tulos_{a.tunnus}.json", "w", encoding="utf-8") as f:
        json.dump({"tunnus": a.tunnus, "osa1": bool(l1), "osa2": bool(l2)}, f)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        main()
    except RuntimeError as e:
        print(f"\nVirhe: {e}", file=sys.stderr)
        sys.exit(1)

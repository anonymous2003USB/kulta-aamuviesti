"""Aamuviesti: kullan päivän liike-ennuste ja talouskalenteri Telegramiin.

GitHub Actions ajaa tämän joka arkiaamu. Omalla koneella:
    python aamuviesti.py        # tulostaa viestin; lähettää myös, jos Telegram-avaimet on asetettu

Ympäristömuuttujat:
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID   lähettämiseen (GitHubissa "Secrets")
    TILI    tilin koko dollareina, oletus 1000
    RISKI   riski prosentteina per kauppa, oletus 1
    RAJAT   liikerajat dollareina, oletus 17,50,100
"""
import html
import math
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import requests

import isoliike as I
import liikekartta as L

HKI = ZoneInfo("Europe/Helsinki")
KALENTERI_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
VIIKONPAIVAT = ["ma", "ti", "ke", "to", "pe", "la", "su"]
SOPIMUSKOKO = 100   # unssia yhdessä lotissa (useimmilla välittäjillä XAUUSD)
MIN_LOTTI = 0.01


def asetus(nimi, oletus):
    arvo = os.environ.get(nimi, "").strip()
    return arvo if arvo else oletus


# ---------------------------------------------------------------------------
# Tiedot
# ---------------------------------------------------------------------------
def kalenteri(paiva):
    """Päivän isot USD-julkaisut Suomen ajassa: ([(aika, otsikko), ...], virhe)."""
    try:
        vastaus = requests.get(KALENTERI_URL, timeout=20, headers={"User-Agent": "kulta-aamuviesti/1.0"})
        vastaus.raise_for_status()
        tapahtumat = vastaus.json()
    except Exception as e:
        return [], e.__class__.__name__
    rivit = []
    for t in tapahtumat:
        if t.get("country") != "USD" or t.get("impact") != "High":
            continue
        try:
            aika = datetime.fromisoformat(t["date"]).astimezone(HKI)
        except (KeyError, ValueError, TypeError):
            continue
        if aika.date() == paiva:
            rivit.append((aika, t.get("title", "?"), t.get("forecast") or "", t.get("previous") or ""))
    return sorted(rivit), None


# Mitä julkaisu tarkoittaa ja mistä virallinen luku löytyy. Ensimmäinen osuma otsikosta voittaa.
JULKAISUT = [
    ("Non-Farm Employment", "Uudet työpaikat (työllisyysraportti)", "https://www.bls.gov/news.release/empsit.toc.htm"),
    ("Unemployment Rate", "Työttömyysaste (työllisyysraportti)", "https://www.bls.gov/news.release/empsit.toc.htm"),
    ("Average Hourly Earnings", "Tuntipalkkojen muutos (työllisyysraportti)", "https://www.bls.gov/news.release/empsit.toc.htm"),
    ("Core PCE", "Ydininflaatio, PCE (Fedin seuraama mittari)", "https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    ("PCE", "Inflaatio, PCE", "https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    ("Core CPI", "Ydininflaatio (kuluttajahinnat ilman ruokaa ja energiaa)", "https://www.bls.gov/cpi/"),
    ("CPI", "Inflaatio (kuluttajahinnat)", "https://www.bls.gov/cpi/"),
    ("PPI", "Tuottajahinnat", "https://www.bls.gov/ppi/"),
    ("GDP", "Bruttokansantuote (talouskasvu)", "https://www.bea.gov/data/gdp/gross-domestic-product"),
    ("FOMC", "Fedin korkopäätös tai -tiedote", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    ("Federal Funds Rate", "Fedin korkopäätös", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    ("Fed Chair", "Fedin puheenjohtajan puhe", None),
    ("Unemployment Claims", "Viikoittaiset työttömyyskorvaushakemukset", None),
    ("JOLTS", "Avoimet työpaikat", None),
    ("Retail Sales", "Vähittäiskauppa", None),
    ("ISM", "Ostopäällikköindeksi (yritysten näkymät)", None),
]


def selitys(otsikko):
    for avain, suomeksi, linkki in JULKAISUT:
        if avain.lower() in otsikko.lower():
            return suomeksi, linkki
    return None, None


def kalenterilinkki(paiva):
    kuukaudet = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    return f"https://www.forexfactory.com/calendar?day={kuukaudet[paiva.month - 1]}{paiva.day}.{paiva.year}"


def seuraava_arkipaiva(paiva):
    paiva = paiva + timedelta(days=1)
    while paiva.weekday() >= 5:
        paiva += timedelta(days=1)
    return paiva


def ennuste(rajat_usd):
    """Liike-ennuste päivälle, jonka liike ei vielä ole datassa."""
    df = I.hae("GC=F")
    kaikki = I.paivat(df)
    p = I.ennusta(kaikki)
    hinta = float(df["close"].iloc[-1])
    odotettu, normaali, iso = L.seuraavan_paivan_ennuste(kaikki)
    ryhma = p[p["iso_paiva"] == iso]

    todennakoisyys = {
        usd: float(np.mean([L.ensimmainen_tunti(r, usd / hinta) is not None for _, r in ryhma.iterrows()]))
        for usd in rajat_usd
    }
    # Tavallinen 3 tunnin heilahdus: kuinka kauas hinta karkasi klo 07 UTC hinnasta kolmessa tunnissa (mediaani).
    kolme_tuntia = []
    for _, r in ryhma.iterrows():
        k = r["kynttilat"].iloc[:3]
        kolme_tuntia.append(max(k["high"].max() - r["p0"], r["p0"] - k["low"].min()) / r["p0"])
    return {
        "hinta": hinta,
        "odotettu": odotettu,
        "normaali": normaali,
        "iso": iso,
        "todennakoisyys": todennakoisyys,
        "heilahdus3h": float(np.median(kolme_tuntia)) * hinta,
        "paivia": len(ryhma),
        "kohdepaiva": seuraava_arkipaiva(kaikki.index[-1].date()),
    }


# ---------------------------------------------------------------------------
# Viesti
# ---------------------------------------------------------------------------
def kauppakoko_rivi(stoppi_usd, tili, riski):
    riski_rahaa = tili * riski / 100
    lotit = math.floor(riski_rahaa / (stoppi_usd * SOPIMUSKOKO) / MIN_LOTTI + 1e-9) * MIN_LOTTI
    if lotit >= MIN_LOTTI:
        return (f"<b>Kauppakoko:</b> {I.luku(riski, 1).rstrip('0').rstrip(',')} %:n riskillä {I.luku(tili, 0)} $:n tilillä "
                f"ja {I.luku(stoppi_usd, 0)} $:n stopilla enintään {I.luku(lotit, 2)} lottia.")
    tappio = stoppi_usd * SOPIMUSKOKO * MIN_LOTTI
    return (f"<b>Kauppakoko:</b> pieninkin kauppa ({I.luku(MIN_LOTTI, 2)} lottia) häviää {I.luku(stoppi_usd, 0)} $:n "
            f"stopilla noin {I.luku(tappio, 0)} $ eli {I.pros(tappio / tili, 1)} {I.luku(tili, 0)} $:n tilistä.")


def tee_viesti(e, tapahtumat, kalenteri_virhe, tili, riski, rajat_usd, ennuste_virhe=None):
    nyt = datetime.now(HKI)
    kohde = e["kohdepaiva"] if e else nyt.date()
    rivit = [f"<b>Kulta {VIIKONPAIVAT[kohde.weekday()]} {kohde.day}.{kohde.month}.</b>"]

    if e:
        tyyppi = "ISO PÄIVÄ" if e["iso"] else "RAUHALLINEN PÄIVÄ"
        rivit.append(f"Hinta {I.luku(e['hinta'], 0)} $ (kultafutuuri, noin 10 min viiveellä)")
        rivit.append("")
        rivit.append(f"<b>Ennuste: {tyyppi}</b>")
        rivit.append(f"odotettu liike {I.pros(e['odotettu'], 2)}, tavallinen {I.pros(e['normaali'], 2)}")
    else:
        rivit.append("")
        rivit.append(f"⚠️ Hintatietoa ei saatu tänään ({html.escape(ennuste_virhe or '?')}), joten liike-ennustetta ei ole.")

    rivit.append("")
    if kalenteri_virhe:
        rivit.append(f"⚠️ Talouskalenteria ei saatu ({html.escape(kalenteri_virhe)}). Tarkista itse forexfactory.com.")
    elif tapahtumat:
        rivit.append("⚠️ <b>Isot USD-julkaisut tänään</b> (ennuste ei huomioi näitä):")
        for aika, otsikko, ennuste_arvo, edellinen in tapahtumat:
            suomeksi, linkki = selitys(otsikko)
            nimi = html.escape(suomeksi or otsikko)
            nimi = f'<a href="{linkki}">{nimi}</a>' if linkki else nimi
            luvut = []
            if ennuste_arvo:
                luvut.append(f"odotus {html.escape(ennuste_arvo)}")
            if edellinen:
                luvut.append(f"edellinen {html.escape(edellinen)}")
            rivit.append(f"• klo {aika.strftime('%H.%M')} {nimi}" + (f" ({', '.join(luvut)})" if luvut else ""))
        rivit.append(f'<a href="{kalenterilinkki(kohde)}">Koko päivän kalenteri ja toteutuneet luvut</a>')
        rivit.append("Hinta voi liikkua julkaisun minuuteilla nopeasti kumpaan suuntaan tahansa ja hypätä stopin yli.")
    else:
        rivit.append("Ei isoja USD-julkaisuja tänään.")

    if e:
        rivit.append("")
        alku = datetime(kohde.year, kohde.month, kohde.day, 7, tzinfo=ZoneInfo("UTC")).astimezone(HKI).hour
        rivit.append(f"<b>Todennäköisyys, että hinta karkaa klo {alku}–{alku + 14} jompaankumpaan suuntaan:</b>")
        rivit.append("  ·  ".join(f"{I.luku(u, 0)} $: {I.pros(e['todennakoisyys'][u], 0)}" for u in rajat_usd))
        rivit.append(f"(kahden vuoden {e['paivia']} päivästä, joilla ennuste oli sama)")
        rivit.append("")
        rivit.append(f"<b>Stoppi:</b> puolena tällaisista päivistä hinta heilahti 3 tunnissa vähintään "
                     f"{I.luku(e['heilahdus3h'], 0)} $ johonkin suuntaan. Tätä lähempänä oleva stoppi osuu helposti "
                     "pelkästä tavallisesta heilunnasta.")
        rivit.append(kauppakoko_rivi(max(round(e["heilahdus3h"]), 1), tili, riski))

    rivit.append("")
    rivit.append("Suuntaa tämä ei kerro. Ei sijoitusneuvo.")
    return "\n".join(rivit)


def laheta(teksti):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("(Telegram-avaimia ei ole asetettu, viestiä ei lähetetty.)")
        return True
    vastaus = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat, "text": teksti, "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=20,
    )
    if vastaus.ok and vastaus.json().get("ok"):
        print("Viesti lähetetty Telegramiin.")
        return True
    print(f"Telegram-lähetys epäonnistui: {vastaus.status_code} {vastaus.text[:300]}", file=sys.stderr)
    return False


def main():
    tili = float(asetus("TILI", "1000"))
    riski = float(asetus("RISKI", "1"))
    rajat_usd = [float(x) for x in asetus("RAJAT", "17,50,100").split(",")]

    e, ennuste_virhe = None, None
    try:
        e = ennuste(rajat_usd)
    except Exception as virhe:  # viesti lähtee silti, jotta tiedät, ettei ennustetta tullut
        ennuste_virhe = f"{virhe.__class__.__name__}: {virhe}"[:200]
        print(f"Ennuste epäonnistui: {ennuste_virhe}", file=sys.stderr)

    kohde = e["kohdepaiva"] if e else datetime.now(HKI).date()
    tapahtumat, kalenteri_virhe = kalenteri(kohde)
    teksti = tee_viesti(e, tapahtumat, kalenteri_virhe, tili, riski, rajat_usd, ennuste_virhe)
    print(teksti)
    print()
    if not laheta(teksti):
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()

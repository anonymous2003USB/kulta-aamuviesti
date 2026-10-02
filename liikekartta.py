"""Liikekartta: kuinka usein ja kuinka nopeasti kulta karkaa 12 $, 50 $ ja 100 $ päivän aikana.

Tämä EI ole kaupankäyntistrategian testi, vaan kuvaus siitä, millaisia liikkeitä kullassa tapahtuu.
Lopussa on esikatselu aamuviestistä, jonka botti voisi lähettää joka päivä.

Käyttö:
    python liikekartta.py
    python liikekartta.py --rajat 17,25,50,100
"""
import argparse
import sys

import numpy as np

import isoliike as I


def ensimmainen_tunti(rivi, raja):
    """Monennenko tunnin aikana (klo 07 UTC jälkeen) hinta karkasi ensimmäisen kerran rajan verran. None = ei koskaan."""
    p0 = rivi["p0"]
    k = rivi["kynttilat"]
    karkaus = np.maximum((k["high"].to_numpy() - p0) / p0, (p0 - k["low"].to_numpy()) / p0)
    osui = karkaus >= raja
    return int(np.argmax(osui)) + 1 if osui.any() else None


def seuraavan_paivan_ennuste(kaikki):
    """Ennuste päivälle, jonka liike ei vielä ole datassa. Sama laskenta kuin isoliike.ennusta()."""
    liike = kaikki["liike"]
    ennuste = liike.ewm(span=I.EWMA_PAIVAT, adjust=False, min_periods=I.EWMA_PAIVAT).mean().iloc[-1]
    aiemmat = liike.shift(1).ewm(span=I.EWMA_PAIVAT, adjust=False, min_periods=I.EWMA_PAIVAT).mean()
    normaali = aiemmat.dropna().iloc[-I.VERTAILU_PAIVAT:].median()
    return float(ennuste), float(normaali), bool(ennuste >= normaali)


def main():
    j = argparse.ArgumentParser(description="Kullan liikekartta")
    j.add_argument("--tunnus", default="GC=F")
    j.add_argument("--rajat", default="17,50,100", help="rajat dollareina nykyhinnalla, pilkulla erotettuna")
    a = j.parse_args()
    rajat_usd = [float(x) for x in a.rajat.split(",")]

    df = I.hae(a.tunnus)
    kaikki = I.paivat(df)
    p = I.ennusta(kaikki)
    hinta = float(df["close"].iloc[-1])
    iso, rauh = p["iso_paiva"], ~p["iso_paiva"]

    print("=" * 84)
    print(f"  LIIKEKARTTA – {a.tunnus}, 1 h kynttilät")
    print(f"  Jakso: {p.index[0]:%d.%m.%Y} – {p.index[-1]:%d.%m.%Y}, {len(p)} kauppapäivää. Hinta nyt {I.luku(hinta)} $.")
    print("=" * 84)
    print("  Liike = kuinka kauas hinta karkaa klo 07 UTC hinnasta jompaankumpaan suuntaan klo 21 UTC mennessä.")
    print("  (Suomen aikaa klo 10–24 kesäaikana, 9–23 talviaikana.) Rajat on muutettu prosenteiksi nykyhinnasta,")
    print("  jotta vanhat päivät, jolloin kulta oli halvempi, ovat vertailukelpoisia.")
    print()
    print(f"  {'Raja':<22}{'1 tunnissa':>12}{'3 tunnissa':>12}{'Koko päivänä':>14}{'Rauhallinen':>13}{'Iso päivä':>11}")

    todennakoisyydet = {}
    for usd in rajat_usd:
        raja = usd / hinta
        tunnit = np.array([ensimmainen_tunti(r, raja) or 99 for _, r in p.iterrows()])
        osui = tunnit < 99
        todennakoisyydet[usd] = (osui[iso.to_numpy()].mean(), osui[rauh.to_numpy()].mean())
        nimi = f"{I.luku(usd, 0)} $ ({I.pros(raja, 2)})"
        print(f"  {nimi:<22}{I.pros((tunnit <= 1).mean(), 0):>12}{I.pros((tunnit <= 3).mean(), 0):>12}"
              f"{I.pros(osui.mean(), 0):>14}{I.pros(todennakoisyydet[usd][1], 0):>13}{I.pros(todennakoisyydet[usd][0], 0):>11}")

    print()
    print("  Miten luet: \"Koko päivänä 98 %\" = 98 päivänä sadasta hinta karkasi ainakin näin paljon johonkin suuntaan.")
    print("  \"Rauhallinen\" ja \"Iso päivä\" = sama luku eroteltuna sen mukaan, mitä aamun ennuste sanoi.")
    for usd in rajat_usd:
        kokopaiva = np.mean([ensimmainen_tunti(r, usd / hinta) is not None for _, r in p.iterrows()])
        if kokopaiva >= 0.9:
            print(f"  {I.luku(usd, 0)} $ ylittyy lähes joka päivä, joten aamun ennuste ei kerro siitä mitään.")

    # Kuun ensimmäinen perjantai: silloin julkaistaan yleensä USA:n työllisyysraportti (klo 15.30 Suomen aikaa).
    perjantai = np.array([d.weekday() == 4 and d.day <= 7 for d in p.index])
    print()
    print("TYÖLLISYYSRAPORTTIPÄIVÄT (kuun 1. perjantai, likiarvo: muutamana kuuna raportti tuli eri päivänä)")
    print(f"  {'Raja':<22}{'1. perjantai':>14}{'Muut päivät':>14}")
    for usd in rajat_usd:
        osui = np.array([ensimmainen_tunti(r, usd / hinta) is not None for _, r in p.iterrows()])
        print(f"  {I.luku(usd, 0) + ' $':<22}{I.pros(osui[perjantai].mean(), 0):>14}{I.pros(osui[~perjantai].mean(), 0):>14}")
    print(f"  (1. perjantaita: {int(perjantai.sum())}, muita päiviä: {int((~perjantai).sum())})")

    # Milloin päivän aikana kulta liikkuu eniten: tuntikynttilän keskimääräinen pituus Suomen ajassa.
    paikallinen = df.copy()
    paikallinen.index = paikallinen.index.tz_localize("UTC").tz_convert("Europe/Helsinki")
    paikallinen = paikallinen[paikallinen.index.weekday < 5]
    vaihtelu = (paikallinen["high"] - paikallinen["low"]) / paikallinen["close"] * hinta
    tunneittain = vaihtelu.groupby(paikallinen.index.hour).mean()
    suurin = tunneittain.max()
    print()
    print("MILLOIN KULTA LIIKKUU? Tuntikynttilän keskimääräinen pituus Suomen aikaa (nykyhinnalla)")
    for tunti, arvo in tunneittain.items():
        palkki = "█" * int(round(arvo / suurin * 30))
        print(f"  klo {tunti:02d}–{(tunti + 1) % 24:02d}  {I.luku(arvo, 1):>6} $  {palkki}")

    ennuste, normaali, iso_huomenna = seuraavan_paivan_ennuste(kaikki)
    print()
    print("AAMUVIESTIN ESIKATSELU (päivä, jonka liike ei vielä ole datassa)")
    print(f"  Kulta {I.luku(hinta, 0)} $. Ennuste: {'ISO PÄIVÄ' if iso_huomenna else 'RAUHALLINEN PÄIVÄ'}")
    print(f"  (odotettu liike {I.pros(ennuste, 2)}, tavallinen {I.pros(normaali, 2)})")
    print("  Todennäköisyys, että hinta karkaa päivän aikana jompaankumpaan suuntaan:")
    print("    " + "   ".join(f"{I.luku(u, 0)} $: {I.pros(todennakoisyydet[u][0 if iso_huomenna else 1], 0)}" for u in rajat_usd))
    print("  Suuntaa ennuste ei kerro.")
    print("=" * 84)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        main()
    except RuntimeError as e:
        print(f"\nVirhe: {e}", file=sys.stderr)
        sys.exit(1)

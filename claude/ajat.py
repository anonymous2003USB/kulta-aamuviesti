"""Päivän herätysajat (käyttäjän päätös 9.10.2026).

1) Käyttäjän luettelemat kellonajat Suomen aikaa.
2) Samat tapahtumat niiden omassa aikavyöhykkeessä (Lontoo, New York), jotta kellonsiirrot eivät sotke.
3) Aasian avaukset (Tokio, Shanghai): vain markkinan seuranta, ei kauppoja (käyttäjän sääntö: vältä klo 1–6).
Alle 20 minuutin päässä toisistaan olevat ajat yhdistetään yhdeksi herätykseksi.
Käyttö: python -I ajat.py [YYYY-MM-DD] [--aasia]   (--aasia: vain Aasian avaukset)
Tulostaa: Suomen aika, UTC-aika (send_later-työkalun at-kenttään), tyyppi ja kuvaus.
"""
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

HKI = ZoneInfo("Europe/Helsinki")
# (kuvaus, aikavyöhyke, tunti, minuutti, tyyppi)  tyyppi: kauppa = saa käydä kauppaa, seuranta = vain analyysi
HERATYKSET = [
    ("Aasia: Tokion avaus", "Asia/Tokyo", 9, 0, "seuranta"),
    ("Aasia: Shanghain kultapörssin ja Hongkongin avaus", "Asia/Shanghai", 9, 0, "seuranta"),
    ("London 8am", "Europe/Helsinki", 8, 0, "kauppa"),
    ("Lontoon avaus (8.00 Lontoon aikaa)", "Europe/London", 8, 0, "kauppa"),
    ("Lontoon aamun jatko (9.30 Lontoon aikaa)", "Europe/London", 9, 30, "kauppa"),
    ("1:30 major US economic data", "Europe/Helsinki", 13, 30, "kauppa"),
    ("2:30 NYC activity kicks in", "Europe/Helsinki", 14, 30, "kauppa"),
    ("3-4pm volatile time for gold", "Europe/Helsinki", 15, 0, "kauppa"),
    ("10 min USA:n talousdatan jälkeen (8.30 New Yorkin aikaa)", "America/New_York", 8, 40, "kauppa"),
    ("London open 4pm-6pm", "Europe/Helsinki", 16, 0, "kauppa"),
    ("New Yorkin avaus (9.30 New Yorkin aikaa)", "America/New_York", 9, 35, "kauppa"),
    ("Look forward to 5:30pm", "Europe/Helsinki", 17, 30, "kauppa"),
    ("Kullan vilkkain tunti (15.30 Lontoon aikaa)", "Europe/London", 15, 30, "kauppa"),
    ("Lontoo/NY-päällekkäisyyden loppu: MINIMI 2 KAUPPAA -tarkistus", "Europe/London", 16, 30, "kauppa"),
    ("NYC open 9pm-12am / London-NYC overlap 9pm-12pm", "Europe/Helsinki", 21, 0, "kauppa"),
    ("NYC open 9pm-12am / overlap: päivän viimeinen tarkistus", "Europe/Helsinki", 23, 0, "kauppa"),
]


def ajat(d, vain_aasia=False):
    raaka = []
    for kuvaus, tz, h, m, tyyppi in HERATYKSET:
        if vain_aasia != (tyyppi == "seuranta"):
            continue
        t = datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(tz)).astimezone(HKI)
        if t.date() != d:
            continue
        raaka.append([t, kuvaus, tyyppi])
    raaka.sort(key=lambda x: x[0])
    out = []
    for t, kuvaus, tyyppi in raaka:
        if out and (t - out[-1][0]).total_seconds() < 20 * 60:
            out[-1][1] += " + " + kuvaus
        else:
            out.append([t, kuvaus, tyyppi])
    return [(t, t.astimezone(timezone.utc), tyyppi, kuvaus) for t, kuvaus, tyyppi in out]


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    d = date.fromisoformat(a[0]) if a else datetime.now(HKI).date()
    for hki, utc, tyyppi, kuvaus in ajat(d, "--aasia" in sys.argv):
        print(f"{hki:%H:%M} Suomen aikaa  {utc:%Y-%m-%dT%H:%M:00Z}  [{tyyppi}]  {kuvaus}")

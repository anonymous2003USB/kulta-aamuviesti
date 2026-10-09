"""Päivän kauppatarkistusten ajat. Lasketaan tapahtumien omista aikavyöhykkeistä, joten kellojen siirrot
(EU ja USA eri päivinä) eivät sotke aikoja. Käyttö: python -I ajat.py [YYYY-MM-DD]
Tulostaa jokaisen ajan Suomen aikana ja UTC-aikana (send_later-työkalun at-kenttään)."""
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

HKI = ZoneInfo("Europe/Helsinki")
TAPAHTUMAT = [
    ("Lontoon avaus", "Europe/London", 8, 0),
    ("Lontoon aamun jatko", "Europe/London", 9, 30),
    ("10 min USA:n talousdatan jälkeen (8.30 NY)", "America/New_York", 8, 40),
    ("New Yorkin avaus", "America/New_York", 9, 35),
    ("Kullan vilkkain tunti (Lontoo 15-16)", "Europe/London", 15, 30),
    ("Lontoo/NY-päällekkäisyyden loppu, viimeinen tarkistus (minimi 2 kauppaa)", "Europe/London", 16, 30),
]


def ajat(d):
    out = []
    for nimi, tz, h, m in TAPAHTUMAT:
        t = datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(tz))
        out.append((t.astimezone(HKI), t.astimezone(timezone.utc), nimi))
    out.sort()
    for x, y in zip(out, out[1:]):  # varmistus: kaksi herätystä ei saa osua samaan aikaan
        assert (y[0] - x[0]).total_seconds() >= 20 * 60, f"liian lähekkäin: {x[2]} ja {y[2]}"
    return out


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(HKI).date()
    for hki, utc, nimi in ajat(d):
        print(f"{hki:%H:%M} Suomen aikaa  {utc:%Y-%m-%dT%H:%M:00Z}  {nimi}")

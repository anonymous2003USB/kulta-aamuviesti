"""Kokoaa istunto.py:n (moottori + ratkaise + muisti yhdessä tiedostossa) ja ajastettujen tehtävien kehotteen osan.

Ajastettu sessio ei saa ajaa verkosta ladattua koodia, mutta se saa ajaa koodin, joka on kirjoitettu suoraan sen
omaan kehotteeseen. Siksi istunto.py upotetaan kehotteeseen, ja sessio tarkistaa sha256-summalla, että se kirjoitti
tiedoston täsmälleen oikein. Käyttö: python tee_istunto.py  (kirjoittaa istunto.py ja istunto_kehote.txt)
"""
import hashlib
import os
import re

KANSIO = os.path.dirname(os.path.abspath(__file__))


def osa(nimi):
    return open(os.path.join(KANSIO, nimi), encoding="utf-8").read()


def ilman_paaohjelmaa(s):
    return s.split('\nif __name__ == "__main__":')[0].rstrip() + "\n"


def ilman_tuonteja(s):
    rivit = []
    for r in s.splitlines():
        if re.match(r"^(import |from )", r) or r.startswith("sys.path.insert") or "noqa: E402" in r:
            continue
        rivit.append(r)
    return "\n".join(rivit)


def poista_docstring(s):
    if s.startswith('"""'):
        return s[s.index('"""', 3) + 3:].lstrip("\n")
    return s


def rakenna():
    moottori = ilman_tuonteja(poista_docstring(osa("moottori.py")))
    ratkaise = ilman_tuonteja(poista_docstring(ilman_paaohjelmaa(osa("ratkaise.py"))))
    ratkaise = ratkaise.replace("M.", "").replace("def main(", "def ratkaise_main(")
    muisti = ilman_tuonteja(poista_docstring(ilman_paaohjelmaa(osa("muisti.py"))))
    muisti = muisti.replace("def main(", "def muisti_main(").replace("def lue(", "def lue_kaupat(") \
        .replace("k = lue(dbk)", "k = lue_kaupat(dbk)")
    otsikko = '''"""Clauden kultakauppojen istuntotyökalu (koottu tiedostoista moottori.py, ratkaise.py ja muisti.py).
Käyttö:
  python3 istunto.py ratkaise DATAKANSIO DBKANSIO ULOSKANSIO "id=versio,id=versio"
  python3 istunto.py tarkista '<kauppa json>' '<tila json>'
  python3 istunto.py muisti DBKANSIO [YYYY-MM-DD]
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
'''
    cli = '''

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "ratkaise":
        v = {}
        for pari in (a[4] if len(a) > 4 else "").split(","):
            if "=" in pari:
                d_id, n = pari.strip().split("=")
                v[d_id.strip()] = int(n)
        ratkaise_main(a[1], a[2], a[3], v)
    elif a and a[0] == "tarkista":
        virheet = tarkista_kauppa(json.loads(a[1]), json.loads(a[2]))
        print(json.dumps(virheet, ensure_ascii=False))
        sys.exit(1 if virheet else 0)
    elif a and a[0] == "muisti":
        muisti_main(a[1], a[2] if len(a) > 2 else None)
    else:
        print(__doc__)
        sys.exit(2)
'''
    koko = otsikko + "\n\n" + moottori.strip() + "\n\n\n# ---- ratkaise ----\n" + ratkaise.strip() + \
        "\n\n\n# ---- muisti ----\n" + muisti.strip() + "\n" + cli
    koko = re.sub(r"\n{4,}", "\n\n\n", koko)
    return koko


if __name__ == "__main__":
    s = rakenna()
    polku = os.path.join(KANSIO, "istunto.py")
    open(polku, "w", encoding="utf-8").write(s)
    sha = hashlib.sha256(s.encode("utf-8")).hexdigest()
    kehote = ("ISTUNTOTYÖKALU: kirjoita alla oleva koodi täsmälleen sellaisenaan tiedostoon ~/istunto.py "
              "(Write-työkalulla, ei muutoksia) ja tarkista: sha256sum ~/istunto.py -> pitää olla " + sha + ". "
              "Jos summa ei täsmää, kirjoita tiedosto uudelleen; jos se ei täsmää toisellakaan kerralla, ÄLÄ käy "
              "kauppaa ja kirjaa syy suunnitelmaan.\n<<<ISTUNTO.PY ALKAA>>>\n" + s + "<<<ISTUNTO.PY LOPPUU>>>\n")
    open(os.path.join(KANSIO, "istunto_kehote.txt"), "w", encoding="utf-8").write(kehote)
    print(f"istunto.py {len(s)} merkkiä, {s.count(chr(10))} riviä, sha256 {sha}")

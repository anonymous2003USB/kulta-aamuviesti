# Clauden kultakauppojen arkisto

Analyysi ja chartit sellaisina kuin ne olivat päätöshetkellä (ei jälkikäteen tulleita tietoja).

- `YYYY-MM-DD/HHMM/` = Suomen aika. Sisältää analyysi.txt, analyysi.json ja chartit d1, h4, h1, m15, m5, m1, s10 (64 värin PNG).
- Hintasyöte tallentaa tilannekuvan puolen tunnin välein klo 7.00–23.30 sekä kaikkina herätysaikoina (myös Aasian avaukset).
- `YYYY-MM-DD/hakemisto.txt` = päivän tilannekuvat.
- `kaupat.txt` = jokaisen kaupan päätös- ja sulkuhetken tilannekuva (kauppojen kenttä `kaaviot` päiväkirjassa).
- Ennen 14.10. tehtyjen kauppojen kuvat on piirretty jälkikäteen minuuttidatasta samalla ohjelmalla
  (`smc.py --aika`, ei tulevaisuuden tietoa). Niistä puuttuu sekuntichartti, ja 6.10. kuvissa on huomautus
  "H1- ja M1-data eivät mene päällekkäin", koska minuuttidata alkoi 5.10. illalla.

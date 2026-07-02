# Kontrol af virksomhedsmarkeringer og opgaver i Momentum

Kontrollerer alle virksomheder med Virksomhedsbank-markeringer i Momentum og sikrer, at de har korrekte ansvarlige sagsbehandlere, opgaver og markeringer.

## Hvad gør robotten?

1. Henter alle virksomheder med Virksomhedsbank-markeringer (Passiv, Kontakt, Partnerskab, Samarbejde) fra Momentum og fylder arbejdskøen.
2. For hvert kø-element hentes virksomhedsdetaljer, overblik, markeringer og opgaver fra Momentum.
3. Inaktive virksomheder: lukker alle markeringer og opgaver og fjerner porteføljeansvarlige fra overblik.
4. Kontrollerer at der er præcis én porteføljeansvarlig sagsbehandler — er der 0 eller flere sendes virksomheden til manuel rapport.
5. Virksomheder med en "Passiv - Virksomhedsbank"-markering: lukker porteføljeopfølgningsopgaver.
6. Virksomheder med én markering med slutdato: lukker porteføljeopfølgningsopgaver og fjerner porteføljeansvarlig.
7. Finder markeringer der mangler aktive porteføljeopfølgningsopgaver og opretter nye opgaver med beregnet falddato baseret på nyeste journalnotat (Partnerskab/Samarbejde: hver 3. måned, Kontakt/Passiv: hvert halvår).
8. Fejl i behandling rapporteres til manuel arbejdsliste med P-nummer, virksomhedsnavn og bemærkning.

## Forudsætninger

- Python ≥ 3.13
- [`uv`](https://docs.astral.sh/uv/) til pakkehåndtering
- Adgang til **Automation Server** (arbejdskø og credentials)
- Adgang til **Momentum** (produktion)
- Adgang til **Odense SQL Server**

## Installation

```sh
uv sync
```

## Konfiguration

Credentials registreres i Automation Server:
- `Odense SQL Server`
- `Momentum - produktion`

| Miljøvariabel | Beskrivelse |
|---|---|
| `ATS_URL` | URL til Automation Server API |
| `ATS_TOKEN` | Bearer token til autentificering mod Automation Server |
| `ATS_WORKQUEUE_OVERRIDE` | Tilsidesætter arbejdskø-ID (bruges til test) |

## Kørsel

```sh
uv run python main.py --queue   # Fyld arbejdskøen
uv run python main.py           # Behandl arbejdskøen
```

## Afhængigheder

| Pakke | Formål |
|---|---|
| `automation-server-client` | Klient til Automation Server – arbejdskø, credentials og arbejdsemner |
| `momentum-client` | Klient til Momentum sagsbehandlingssystem – virksomheder, markeringer, opgaver, journalnotater og taksonomier |
| `odk-tools` | Fælles ODK-værktøjer til aktivitetssporing (Tracker) og manuel rapportering |
| `python-dateutil` | Beregning af relative datoer (falddatoer for opgaver) |

## GDPR og sikkerhed

Processen behandler virksomhedsdata (CVR-numre, P-numre, virksomhedsnavne) samt sagsbehandler-ID'er tilknyttet virksomhederne i Momentum. Sagsbehandlerdata er medarbejderoplysninger og udgør persondata. Fejlrapporter med P-numre og virksomhedsnavne sendes til manuel arbejdsliste i Automation Server og er kun tilgængelige for brugere med adgang hertil.

# KuCoin-Paperbetrieb: reproduzierbarer Stand

Der erste integrierte Abnahmekandidat verwendet das Profil `config.5usdt.json`:
KuCoin, 5 virtuelle USDT und höchstens 2,5 USDT Einsatz. Die übrigen Profile
behalten ihre Börsen. Echte Konten und Echtgeldaktivierung sind davon getrennt.

## Installation und Start

Python 3.12; aus dem Repositoryverzeichnis eine eigene virtuelle Umgebung anlegen:

```text
python -m venv .venv
```

Unter Windows danach `.venv\Scripts\python.exe` statt `python` verwenden,
unter Linux `.venv/bin/python`. Die Umgebung nicht committen.

```text
python -m pip install -r jin_trading/requirements-live.txt
python scripts/jin_public_probe.py --seconds 30 --require-fresh
python -m jin_trading.server --feed websocket --config jin_trading/config.5usdt.json --db data/jin-paper-5.sqlite
```

Vor dem Serverstart muss der vorhandene lokale Dashboard-Schlüssel als
`JIN_DASHBOARD_TOKEN` verfügbar sein. Schlüssel nie als Befehlszeilenargument,
im Frontend-Quellcode oder im Repository speichern. `--feed rest` wählt ausdrücklich
den REST-Betrieb; alle Orderprüfungen behalten ihre Grenzen.

Windows benötigt `tzdata` für den Tageswechsel Europe/Berlin; diese Abhängigkeit
ist in den Anforderungen enthalten. Die Windows-Uhr muss synchronisiert sein:
Einstellungen → Zeit und Sprache → Datum und Uhrzeit → Jetzt synchronisieren.
Negative gemessene Kursalter weisen auf eine Uhrzeitabweichung hin. Die Prüfung
`0 <= Kursalter <= 3 Sekunden` wird nicht aufgeweicht.

## Status und Abnahme

`/healthz` bestätigt den HTTP-Dienst, `/readyz` die gemeinsame Bereitschaft.
Die authentifizierte Schnittstelle `/api/runtime` und `/api/state.runtime`
enthalten zusätzlich `bots[id]` mit `ready`, `reason`, `complete_routes`,
`missing_pairs`, `stale_pairs`, `last_route_at` und `route_age_seconds`.
Der Start prüft den ausgewählten Bot sowie gemeinsame Konto-/Risikosperren.
Ein vollständiger frischer Rundweg ist noch keine profitable oder finanzierbare Route.

`universe.venues[exchange]` beschreibt die tatsächliche Marktgruppe, eigene
Rotation, benötigte Bewertungspaare und aktive WebSocket-Abonnements. Die
globalen Felder `batch_count`, `batch_number` und `selected_pairs` sind jetzt
Mappings je Börse. Verbraucher müssen für einen Bot dessen Börse auswählen.

Die Sperrliste verhindert neue Trades auch über Märkte, die weiterhin zur
Bewertung vorhandener Bestände gelesen werden. Vollständige Dreiecke und
Bewertungspaare teilen sich maximal 20 Abonnements pro Börse; Kapazitätsmangel
wird angezeigt und blockiert neue Ausführungen.

Für Börsen mit ausschließlich Dreiecks-Bots rotiert der Dienst nur vollständige
Dreiecke und benötigte Bewertungspaare. Einzelne USDT-Märkte ohne Dreiecksroute
werden weiter im Katalog gezählt, beanspruchen aber keine Handelsrotation.
Bei gemischten Strategien bleibt die zusätzliche Einzelmarktplanung erhalten.
Auch ohne neue Kurse veröffentlicht der WebSocket-Verbraucher seinen Fehlerstatus
und entfernt abgelaufene Bücher; dabei werden keine Kurszeitstempel erneuert.

Nach dem öffentlichen Verbindungstest und der lokalen Testsuite den Paperbot
über die Bot-Zentrale starten und den [24-Stunden-Monitor](PAPER-ACCEPTANCE.md)
ausführen. Wiederanlauf, Teilfüllungen, unbekannte Orders und Not-Aus bleiben
gesonderte Testfälle. Ein laufender oder abgebrochener Monitor ist kein bestandener
24-Stunden-Nachweis; gestoppte Bots ergeben nur Scanner-Beobachtung.

## Kontotest noch separat erforderlich

Der nur lesende Kontotest benötigt lokal eingerichtete KuCoin-Schlüssel unter
`JIN_KUCOIN_KEY`, `JIN_KUCOIN_SECRET`, `JIN_KUCOIN_PASSPHRASE`:

```text
python -m jin_trading.account_check --exchange kucoin --amount 5 --db data/kucoin-readonly.sqlite
```

Er sendet keine Orders. `tradable_routes` trennt technische Mindestmengen und
Tiefe von `feasible` (zusätzlich profitable Schätzungen). Persönliche Gebühren
werden nur mit frischem Nachweis verwendet; Annahmen bleiben gekennzeichnet.
`live_ready` bleibt false. Ohne eingerichtetes Konto ist dieser Schritt offen.

## Wiederverwendete Software

CCXT `4.5.85` wird als unveränderte Abhängigkeit eingebunden, einschließlich
seines KuCoin-WebSocket-Connectors. Keine fremden Zugangsdaten oder vollständigen
Handelsplattformen werden übernommen. Quelle und Lizenz:

- [CCXT v4.5.85](https://github.com/ccxt/ccxt/tree/v4.5.85)
- [KuCoin-Connector](https://github.com/ccxt/ccxt/blob/v4.5.85/python/ccxt/pro/kucoin.py)
- [MIT-Lizenz](https://github.com/ccxt/ccxt/blob/v4.5.85/LICENSE.txt)

Das vorhandene Hummingbot/JIN-Orderjournal und Risikomanagement bleiben die
Ausführungsbasis. Gateway bleibt eine spätere DEX-Integration; Freqtrade,
Cryptofeed und NautilusTrader werden in diesem KuCoin-Ausbau nicht eingebunden.

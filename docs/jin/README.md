# JIN Trading — Bot-Zentrale

Stand: 7. Oktober 2026. Der vorhandene Hummingbot-Controller, Observer, die mobile
Anwendung und Android-Quellen bleiben erhalten. Der zusätzliche Dienst verbindet
Scanner, dauerhafte Ausführung, Kontorisiko und Dashboard über ein SQLite-Journal.
Änderungen: [PR #2](https://github.com/jino101/hummingbot/pull/2).
Offene Arbeiten mit Abnahmen: [ROADMAP.md](ROADMAP.md).
Der [Audit](AUDIT-2026-10-07.md) dokumentiert den ursprünglichen Prüfstand.

## Was funktioniert

- Automatischer Katalog aller unterstützten aktiven Binance-, KuCoin- und
  Bitget-Spotmärkte, soweit sie für USDT-Routen erreichbar sind. Rotierende,
  vollständige Dreiecksgruppen; keine feste Gesamt-Coin-Grenze.
- REST und optional CCXT-Pro-WebSocket-Daten. Abfragen/Subscriptions bleiben
  begrenzt; nicht alle Märkte werden gleichzeitig überwacht. Ein langsamer
  Anbieter hält frische Routen eines anderen nicht auf.
- Gemeinsame Reservierung, Orderabsichten mit Client-ID vor dem Versand,
  tatsächliche Füllmengen, Gebühren, unbekannte Orders, Teilfüllungen und
  Wiederherstellung nach Neustart. Unbestätigte Orders werden nicht erneut gesendet.
- Drei-Leg-IOC-Ausführung mit vollständiger Vorprüfung vor der ersten Order;
  die nächste Order setzt die vollständige terminale Füllung der vorherigen voraus.
- Paper-Wallets mit echten simulierten Einzelorders, Restbeständen und Bewertung.
  Momentum, Grid und Mean Reversion laufen ebenfalls im Paper-Modus.
  Vorfinanziertes Cross-Exchange ist über die Ausführungs-API getestet; seine
  automatische Bot-Konfiguration und Echtgeldfreigabe bleiben offen.
- Bis zu 50% gemeinsam reserviertes Kapital; 10% Tagesverlust als dauerhafte
  Stop-Regel auf bewertete Kontobestände, Tageswechsel Europe/Berlin. Bei
  veralteten Kontodaten, ungeklärten Orders oder fehlenden Berechtigungen keine
  neue Ausführung. Kurslücken können die Stop-Grenze überschreiten.
- Kapitalstufen 5, 10, 25, 50, 100, 250, 500 und 1.000 USDT. Die Prozentgrenzen
  werden bei Wachstum nicht automatisch erhöht. 1% ist ein modelliertes
  Risikobudget für die Positionsgröße, keine Verlustgarantie.
- Mobile Start/Stop-Steuerung, Not-Aus, Orderabgleich, ausdrückliche Annahme
  abgeglichener Restbestände, komplette CSV-Ausgabe, Online-Sicherung und Restore
  in eine neue Datei. Ein Reset startet keinen Bot automatisch.

## Paper starten

Python 3.12; der REST-Paper-Dienst benötigt keine Börsen-Zugangsdaten und keine
Hummingbot-Kompilierung. Bots sind bei der ersten Einrichtung gestoppt.

```bash
export JIN_DASHBOARD_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m jin_trading.server
```

Dashboard auf `http://127.0.0.1:8788`. Den Dashboard-Schlüssel lokal privat
aufbewahren. Die Beispielkonfiguration nutzt **100 virtuelle USDT**, verteilt
auf zwei Bots mit je 50. Das ist kein Zugriff auf deine tatsächlichen 5 USDT.
Für ein neues Paper-Journal mit nur 5 virtuellen USDT auf KuCoin:

```bash
python -m jin_trading.server --config jin_trading/config.5usdt.json --db data/jin-paper-5.sqlite
```

Konfigurationsänderungen überschreiben vorhandene Budgets nicht. Der ausdrückliche
Paper-Budget-Reset setzt virtuelle Wallets und Trades zurück, stoppt Bots und ist
bei ungeklärten Ausführungen blockiert. Vor einer gewünschten Migration sichern:

```bash
python -m jin_trading.operations backup --db data/jin-paper.sqlite --destination data/paper-before-reset.sqlite
python -m jin_trading.server --reset-paper-budgets
```

Dieser Reset ist für Live-/Demo-Datenbanken gesperrt. Wiederherstellung überschreibt
nie eine vorhandene Datei; den Dienst beim anschließenden Dateiumstieg stoppen.

### WebSocket-Daten und Replays

```bash
python -m pip install -r jin_trading/requirements-live.txt
python -m jin_trading.server --feed websocket
```

CCXT ist auf 4.5.85 festgelegt. Automatische Subscription-Gruppen rotieren;
gehaltene Bestände und konfigurierte Signal-Märkte werden priorisiert, und der
Katalog wird alle 15 Minuten neu geladen. Höchstens 20 Subscriptions pro Börse;
zu viele Bestandsmärkte blockieren frische Gesamtbewertung statt sie zu erfinden.
Reconnects, Neuabonnements und unveränderte Sequenzen erneuern keine alten Kurse. Ein 24-Stunden-
Börsentest ist noch durchzuführen. REST hat mindestens 250 ms Abstand pro Anbieter
und Cooldown bei HTTP 418/429/451. Fehlende oder ungültige Marktregeln werden
übersprungen. Bitget-Quote-Umrechnungen müssen frisch sein.

Optional `record_path` in der Paper-Konfiguration setzen. JSONL-Aufzeichnungen
rotieren bei ungefähr 10 MB. Replay verlangt eine neue Datenbank:

```bash
python -m jin_trading.replay data/jin-books.jsonl --db data/replay-new.sqlite
```

Replay-Schätzungen belegen weder Ausführbarkeit noch Gewinn mit einem echten Konto.
Der vorhandene Hummingbot-Monitor `jin_arbitrage_monitor` liefert alternativ
Connector-Bücher mit tatsächlichen Tracker-Zeitstempeln. Fehlende Zeitstempel
werden ausgeschlossen. Nur einen Feed-Schreiber je Paper-Journal betreiben.

## Deine echten 5 USDT zunächst prüfen

Die optionalen CCXT-Adapter lesen Spot-Bestände, persönliche Gebühren und aktuelle
API-Berechtigungen. Zugangsdaten ausschließlich in lokalen Umgebungsvariablen:
`JIN_KUCOIN_KEY`, `JIN_KUCOIN_SECRET`, `JIN_KUCOIN_PASSPHRASE`; entsprechend
`JIN_BINANCE_*` und `JIN_BITGET_*`. Live benötigt lesende und Spot-Handelsrechte
und nachgewiesene deaktivierte Auszahlungs-/Transferrechte.

```bash
python -m jin_trading.account_check --exchange kucoin --amount 5 --db data/jin-account-check.sqlite
```

Dieser Check sendet keine Orders. Er prüft Bestand, Regeln und Route-Mindestmengen;
seine öffentlichen Gebührenannahmen sind im Ergebnis ausgewiesen und kein Beleg
für persönliche Gebühren. Der Live-Preflight fordert persönliche Gebühren separat
an. Bei 5 USDT und 50% Einsatz kann keine Route alle Mindestorders erfüllen.
Ein solches Ergebnis bleibt gültig; Mindestbeträge werden nicht umgangen.

## Separater Live-Dienst

Der Standardserver und Docker-Compose bleiben Paper. Für den autonomen Live-Dienst
sind eine getrennte Datenbank, lokale Zugangsdaten und die ausdrückliche lokale
Aktivierung erforderlich. Das Dashboard selbst aktiviert kein Echtgeld.

```bash
python -m jin_trading.live_worker --config jin_trading/config.live.example.json --db data/jin-live.sqlite --activate-live I_UNDERSTAND_LIVE_ORDERS
```

Der Port ist 8790, standardmäßig nur lokal erreichbar. Dies ist eine Anleitung
für die spätere, bewusst freigegebene Kontoprüfung; im Entwicklungsprozess wurden
keine echten Orders ausgeführt. Der Dienst unterstützt derzeit Spot-Dreiecke.
Beim ersten Start blockiert ein höherer realer Kontowert als die konfigurierte
Anfangszuteilung (über 1% Toleranz). Mehrere Bots auf demselben Konto teilen dessen
Equity nach ihren Gewichten, ohne das Konto mehrfach zu zählen. Die erste tatsächliche
Zuteilung wird für PnL gespeichert; Neustarts setzen sie nicht zurück.
Externes Ein-/Auszahlen im laufenden Betrieb wird nicht als Cashflow herausgerechnet;
es verändert Equity/Wachstumsanzeige. Vor Änderungen stoppen und die Zuteilung prüfen.

Nach einem unbekannten/teilgefüllten Auftrag: stoppen, Orders abgleichen, tatsächliche
Bestände prüfen, dann gegebenenfalls „Geprüfte Bestände akzeptieren“. Dieser Schritt
löst nur die betreffende Reservierung, nachdem alle Orders terminal bestätigt sind
und Kontobestände frisch bewertet wurden. Er sendet keine Hedge-/Transferorder und
hebt die globale Sperre nicht auf. Ein separater Reset bleibt bei Tagesverlust blockiert.

Der alte native Hummingbot-Live-Executor ist gesperrt, bis er an diese Aufsicht
angebunden ist. Auch die neue Live-Cross-Exchange-Funktion blockiert ohne Tokenidentität
und abgenommenen Inventarausgleich. Netzwerk-Namensgleichheit beweist keine Tokenidentität.
Keine automatischen Auszahlungen oder Transfers. Alpaca-Paper- und OANDA-Practice-
Transporte sind vorhanden; ihre gemeinsame Demo-Ausführung, USD-/FX-Bewertung,
Handelszeiten und Broker-Abnahme sind noch zu implementieren.

## Smartphone und Betrieb

Private [Bot-Zentrale](https://jin-arbitrage-bot.jinoandjelkovic.chatgpt.site).
Sie liest dieselbe API und zeigt ohne verbundenen Dienst keine erfundenen Kontostände.
Trage die HTTPS-Adresse des eigenen Bot-Dienstes und seinen Dashboard-Schlüssel ein.
Der Schlüssel bleibt nur im Seitenspeicher; Börsenschlüssel bleiben auf dem Server.
Die Site-Adresse muss in `allowed_origins` freigegeben sein. Veraltete Verbindungen
sperren Steuerung, Live-Konten sind deutlich gekennzeichnet.

```bash
docker compose -f docker-compose.jin.yml up -d --build
python -m jin_trading.operations health --db data/jin-paper.sqlite
python -m jin_trading.operations restore --db data/paper-before-reset.sqlite --destination data/restored-new.sqlite
```

Compose bietet dauerhafte Daten, Neustart, begrenzte Logs und HTTP-Liveness;
`operations health` prüft aktive Bot-Heartbeats und ungeklärte Ausführungen.
Ein externer Zustandsalarm, HTTPS/VPN und ein bezahlter 24/7-Host sind noch nicht
eingerichtet. Die Site hostet die Oberfläche, nicht den Python-Handelsprozess.
Replit ist eine alternative Oberfläche/Hosting-Vorbereitung. Seine Entwicklungsvorschau
belegt keinen Dauerbetrieb; für Hintergrundarbeit eine geeignete ständig laufende
Deployment-Art und persistente Datenhaltung getrennt prüfen.

Günstige Alternative ohne eigenen Laptop: kleiner Linux-VPS, beispielsweise
[Hetzner Cloud](https://www.hetzner.com/cloud/), zunächst für Paper mit Docker.
Konkreten Tarif, aktuelle Kosten, Region und Börsen-Erreichbarkeit vor Buchung prüfen.
[Replit-Deployment-Arten](https://docs.replit.com/features/publishing/deployment-types)
bleiben ebenfalls zu prüfen. Kein kostenpflichtiger Host wurde bestellt.

## Prüfen

```bash
python -m coverage run --rcfile=/dev/null --branch --source=jin_trading -m unittest discover -s tests_jin
python -m coverage report --rcfile=/dev/null --fail-under=80
python -m compileall -q jin_trading scripts/jin_arbitrage_monitor.py
```

Die CI prüft zusätzlich native Hummingbot-Controller/Executor, mobile API, Docker-Build
und Compose. Tests decken Teilfüllungen, Timeouts, doppelte Events, Stop, Neustart,
Tageswechsel, gemeinsame Reservierung, stale Daten, Berechtigungen, Budgetzuordnung,
Mindestorders und Gebühren ab. Externe Konto-, WebSocket-Soak-, Telefon- und Latenztests
sind in der Roadmap ausdrücklich offen; institutionelles HFT wird nicht behauptet.

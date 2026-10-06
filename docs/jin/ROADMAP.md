# JIN Trading Roadmap

Stand: 6. Oktober 2026. Arbeitszweig: `feat/jin-trading-control`, Entwurfs-PR #2
auf `chatgpt/arbitrage-bot`. Kein Live-Betrieb durch den neuen Paper-Dienst.

## Bereits umgesetzt

- Automatische Erkennung aller unterstützten aktiven USDT-Märkte und kompletter
  USDT-Dreieckswege auf KuCoin/Binance; Bitget derzeit nur USDT-Märkte.
- Kein festes Coin-Limit; faire REST-Rotation mit vollständigen Dreiecksgruppen,
  Anfrageabständen, HTTP-Cooldown und Anzeige der tatsächlichen Abdeckung.
- Paper-Bots, gemeinsame virtuelle 5 USDT, Reinvestition, 10-%-Tagesverlustsperre,
  persistenter Not-Aus, Dashboard, Recording/Replay und Docker-Konfiguration.
- Korrekturen an Transfer-Richtung, PnL, Gebühren, Teilfüllungsaufbewahrung und
  Live-Bereitschaft. Vor dieser Erweiterung bestanden beide PR-Prüfungen auf
  GitHub einschließlich nativer Jino-Tests; neue Änderungen separat prüfen.

## Reihenfolge und Abnahmekriterien

| Priorität | Fehlender Teil | Fertig, wenn … | Voraussetzung |
|---|---|---|---|
| P0 | Aktuelle Erweiterung vollständig prüfen | Paper- und native GitHub-CI grün; Rotation unter realen API-Antworten getestet | Erreichbare Börsen-APIs |
| P0 | Smartphone-Zugriff und 24/7-Betrieb | Docker-Build geprüft; HTTPS/VPN, Neustart, Sicherung und Not-Aus am Galaxy getestet | Eigener Host oder gewählter Server |
| P0 | 5-USDT-Machbarkeitsprüfung | Tatsächliche KuCoin-Gebühren, Mindestmengen, Guthaben und erreichbare Routen ergeben einen dokumentierten Bericht | Börsenkonto lokal verbinden, keine Schlüssel im Chat |
| P1 | Vollständige Transferprüfung | Gemeinsame Tokenidentität, Netzwerke, Aus-/Einzahlungssperren, Gebühren und Kapitalverteilung geprüft | Authentifizierte Kontodaten, wo erforderlich |
| P1 | Große WebSocket-Abdeckung | Automatische Subscription-Shards, Reconnect, Snapshot/Diff-Abgleich und messbare Vollumlaufzeiten | Native Connector-Integration |
| P1 | Bitget-Dreieckswege | Nicht-USDT-Regeln korrekt umgerechnet; Grenzen und Fees mit Fixtures und API geprüft | Zusätzliche Regel- und Bewertungslogik |
| P1 | Live-Dreiecks-Executor | Jede Teilfüllung, Zeitüberschreitung, späte Füllung und jeder Neustart reconciliert; sichere Restmengenbehandlung getestet | Zustandsmaschine und Börsensandbox |
| P1 | Gemeinsame reale Mehrbot-Steuerung | Portfoliorisiko über alle Prozesse/Konten; reserviertes Kapital; zentraler Order-Stopp und Orderabgleich | Authentifizierte Supervisor-Anbindung |
| P2 | Wachstumsstufen | Konfigurierbare Kapitalstufen und Einsatzgrößen; Tageslimit bleibt kontoweit; Replay validiert | Abstimmung der Stufen ohne Gewinnversprechen |
| P2 | Weitere Strategien | Jede Strategie isoliert konfigurierbar, mit Kosten/Slippage validiert und zentral begrenzt | Strategieauswahl und realistische Daten |
| P2 | Aktien und Forex | Brokeradapter mit Handelszeiten, Währungen, Lotgrößen und Gebühren; Sandboxtests bestanden | Broker auswählen und Konto bereitstellen |
| P3 | Niedrige Latenz / HFT-ähnlicher Modus | Datenalter und Order-Latenz messbar; Lasttests, Co-Location-Bedarf und Kosten bewertet | Infrastruktur und Börsenlimits |

## Nächster konkreter Meilenstein

Scanner auf einem erreichbaren Host starten, den gesamten Marktkatalog erfassen,
einen vollständigen Rotationsdurchlauf protokollieren und am Smartphone prüfen.
Ergebnis: sichtbare Paaranzahl je Börse, Wiederbesuchszeit, API-Fehler und für
5 USDT tatsächlich modellierbare Routen. Erst danach Live-Ausführung ausbauen.

## Plugin-Status

- GitHub: vorhandener Code und PR werden direkt gepflegt.
- Context7: Hummingbot-Dokumentation abgefragt; Börsenregeln zusätzlich an
  offiziellen KuCoin/Binance/Bitget-Dokumentationen geprüft.
- Composio: Werkzeugerkennung genutzt; zusätzliche GitHub-Verbindung benötigt.
- Replit: kein passendes vorhandenes Trading-Projekt gefunden; kein Parallelprojekt erstellt.
- Pets: Sammlung geprüft; reine Chat-Begleiter, keine Trading-Funktion.
- Template Creator: Workflow geprüft. Benötigt eine unterstützte Referenz und
  überprüfte Vorschau; keine ungefragte Projekt- oder Vorlagenkopie erstellt.
- Visualize: Roadmap wird als verständliche Phasenübersicht dargestellt.

## Grenzen

Eine größere Coin-Liste erhöht die Abdeckung, nicht automatisch die Rendite.
Rotierende REST-Daten sind keine gleichzeitige Marktüberwachung. Mindestmengen,
Kontobeschränkungen und fehlende Liquidität können bei 5 USDT jede Route blockieren.
Die Paper-Kapitalgrenze bildet keine Garantie für reale maximale Verluste.
Keine echten Orders, Überweisungen oder Produktionsbereitstellung in dieser Änderung.

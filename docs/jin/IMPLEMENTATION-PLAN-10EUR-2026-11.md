# JIN Trading-Bot – Balanced Full-Build Plan

Stand: 20. November 2026  
Arbeitszweig: `jin/10eur-balanced-build`  
Ausgangscommit: `f8817cbf6c5afa48c0a1b274dfa59fccfeee034b` (PR #2 / `feat/jin-trading-control`)

## Ziel

Ein überprüfbares Spot-Arbitrage-System mit:
- Cross-Exchange-Arbitrage (vorfinanzierte Bestände, keine automatischen Transfers)
- Dreiecksarbitrage
- 10 EUR Rechenkapital als verbindliches Gesamtbudget
- konservativer Paper-Modus als Standard
- belastbarer Daten-, Gebühren-, Liquiditäts- und Risikoprüfung
- mobiler Bedienbarkeit
- späterer, ausdrücklich freizugebender Echtgeldvorbereitung

10 EUR ist ein EUR-denominiertes Gesamtbudget. Es darf nicht stillschweigend als 10 USDT interpretiert werden. Vor einer USDT-Order muss der EUR/USDT-Umrechnungskurs mit Quelle und Zeitstempel vorliegen. Fehlt eine belastbare Umrechnung oder ist eine Mindestorder nicht erfüllbar, wird die Route abgelehnt.

## Sicherheitsregeln

1. Keine echten Orders während Audit, Entwicklung oder Paper-Abnahme.
2. Keine API-Auszahlungsberechtigung; Transfers werden nicht automatisiert.
3. Live-Modus bleibt standardmäßig deaktiviert und getrennt vom Paper-Profil.
4. Unbekannte, veraltete oder widersprüchliche Daten führen zu fail-closed.
5. Keine Gewinn- oder Erfolgsversprechen.
6. Vorhandene PRs bleiben unangetastet; Änderungen erfolgen nur in diesem Arbeitszweig.
7. Jede neue Funktion erhält Tests und eine dokumentierte Abnahmebedingung.

## Bestandsaufnahme am Start

- PR #1: offener Draft, Branch `chatgpt/arbitrage-bot`, Cross-Exchange-Controller und mobile Kontrolle.
- PR #2: offener Draft, Branch `feat/jin-trading-control`, 75 geänderte Dateien; Paper-Dienst, KuCoin-Feeds, SQLite-Journal, Risiko-/Supervisorlogik.
- PR #3: offener Draft, Branch `jin-arbitrage-v2`, isolierte V2-Experimente; nicht ungeprüft mit PR #2 zusammenführen.
- PR #2 beschreibt 166 bestandene JIN-Tests und 87 % Coverage am Commit `f8817cbf6c5afa48c0a1b274dfa59fccfeee034b`; GitHub-Actions-Läufe vom 12.10.2026 waren erfolgreich. Das ist kein Beleg für einen 24-Stunden-Lauf oder profitable Live-Ausführung.
- Die bestehende Paper-Konfiguration `config.5usdt.json` startet mit 5 USDT und einem KuCoin-Dreiecks-Bot. Sie entspricht nicht dem vereinbarten 10-EUR-Gesamtbudget.
- Die bestehende Worker-Konfiguration weist `cross_exchange` als Strategie zurück; der Cross-Exchange-Ausführungspfad ist im Paper-Modus gesondert vorhanden und im Live-Modus ausdrücklich gesperrt.
- Die Roadmap dokumentiert Konto-Readonly-Prüfung, eigenen Dauerhost, 24-Stunden-Paper-Abnahme, Cross-Exchange-Integration und Live-Abnahme als offen bzw. teilweise offen.

## Arbeitspakete und Abnahmekriterien

### P0 – Audit und sichere Entwicklungsbasis
- PR #1/#2/#3, Branches, Abhängigkeiten, CI-Workflows, Dokumentation und kritische Ausführungspfade vergleichen.
- Prüfen, welche Tests tatsächlich ausgeführt werden und welche nur behauptet/dokumentiert sind.
- Keine Merge-Aktion auf `master`.
- Abnahme: reproduzierbare Liste von Implementiert / Teilweise / Offen / Fehlerhaft.

### P1 – Kapitalmodell 10 EUR
- EUR als Budget- und Reporting-Referenz einführen.
- EUR/USDT-Umrechnung mit Quelle, Zeitstempel und maximalem Datenalter.
- Kapitalobergrenze, Reserve, Einsatzlimit und Gebühren in Decimal.
- Börsen-Mindestorder, Mindestnotional, Lot-/Tick-Size und verfügbare Bestände je Leg prüfen.
- Abnahme: Tests beweisen, dass Gesamtbudget inklusive Reservierungen 10 EUR nicht überschreitet; fehlende FX-Daten oder Mindestorder führen zur Ablehnung.

### P2 – Dreiecksarbitrage
- Drei Legs anhand echter Orderbuch-Tiefe simulieren.
- Jede Gebühr, Rundung, Mindestmenge, Mindestnotional, Restbetrag und Datenalter berücksichtigen.
- Partial-/Unknown-Fill und Neustart-Recovery testen.
- Abnahme: unabhängige Nachberechnung aus gespeicherten Rohdaten stimmt mit dem Scanner überein; keine Folgeorder nach unvollständigem Leg.

### P3 – Cross-Exchange
- Scanner-Ausgabe und ausführbaren Pfad klar trennen.
- Vorfinanzierte Quote-/Base-Bestände auf beiden Börsen gemeinsam reservieren.
- Beide Bücher, Gebühren, Präzision, Mindestorders, Liquidität und Inventaridentität prüfen.
- Leg-Risiko, Teilfüllung, Cancel/late-fill, Recovery und Bestandsausgleich testen.
- Abnahme: vollständige Paper-Replay- und Fehler-Injektionstests; Live bleibt gesperrt, bis venue-spezifische Abnahme vorliegt.

### P4 – Datenqualität und Marktuniversum
- WebSocket-Feeds, Sequenzen, Reconnects, Feed-Staleness und Börsen-Rate-Limits prüfen.
- Handelbarkeit, Einzahlung, Auszahlung und Netzwerk getrennt modellieren.
- Unbekannte Statuswerte als unbekannt behandeln, nicht als aktiv.
- Abnahme: keine Gelegenheit aus veralteten, nicht handelbaren oder unvollständigen Büchern.

### P5 – Mobile Betriebsebene und Dauerbetrieb
- Smartphone-Dashboard, Status, Warnungen, Journal und Export prüfen.
- Persistente Datenbank, sichere Secrets, HTTPS/VPN, Autostart, Backup/Restore und Monitoring dokumentieren.
- Abnahme: unabhängiger 24-Stunden-Paper-Lauf auf einem dauerhaft erreichbaren Host, inklusive dokumentierter Ausfälle und Recovery. Eine GitHub-CI-Simulation ersetzt den Dauerlauf nicht.

### P6 – Echtgeld-Vorbereitung (separate Freigabe)
- Konto nur lesend prüfen: Identität, Bestände, persönliche Gebühren, Marktregeln und API-Rechte.
- Nur nach expliziter Nutzerentscheidung und bestandenen Gates: kleinste kontrollierte Live-Validierung.
- Auszahlungsrechte bleiben deaktiviert.
- Abnahme: dokumentierter echter Order-/Fill-/Fee-/Cancel-/Recovery-Nachweis. Bis dahin kein Live-Start.

## Zeitplanung (Schätzung, keine Zusage)

- Audit und Entwicklungsplan: 0,5–1,5 aktive Arbeitstage.
- 10-EUR-Kapitalmodell und Tests: 1–3 aktive Arbeitstage.
- Dreiecksarbitrage-Härtung: 1–3 aktive Arbeitstage.
- Cross-Exchange-Paper-Integration: 2–5 aktive Arbeitstage.
- Daten-/Feed- und Mobile-/Betriebshärtung: 2–5 aktive Arbeitstage.
- Echtgeld-Vorbereitung: 1–3 aktive Arbeitstage nach bestandenen Tests und nur mit Nutzerzugang/Freigabe.
- 24-Stunden-Paper-Abnahme: mindestens 24 Stunden echte Laufzeit zusätzlich.

Die tatsächliche Dauer hängt von gefundenen Fehlern, API-/Host-Zugang und Laufzeitbeobachtungen ab. Aktive Codearbeit kann ich hier unterstützen; ein Dienst läuft nicht dauerhaft allein durch diesen Chat.

## Aktueller Status

- [x] Eigenen Arbeitszweig von PR #2 erstellt.
- [x] GitHub-Repository und offene PRs erneut geprüft.
- [x] Ausgangsbudget- und Integrationslücken identifiziert.
- [x] P0-Auditbericht erstellt; Cross-Exchange-Integration, EUR-Budget und Fee-Modell als Blocker dokumentiert.
- [ ] 10-EUR-Kapitalmodell implementieren.
- [x] Erste Cross-Exchange-Härtung: vollständige IOC-Orderbuchtiefe und Nettogewinn nach Quote-Gebühren werden vor der ersten Paper-Order geprüft.
- [x] Regressionstests für nicht profitable Routen und unzureichende Tiefe ergänzt.
- [ ] Neue Regressionstests und vollständige Suite ausführen; für den Arbeitszweig liegen noch keine GitHub-Actions-Läufe vor.
- [ ] Paper-Abnahmen durchführen.
- [ ] Live-Freigabe separat entscheiden.

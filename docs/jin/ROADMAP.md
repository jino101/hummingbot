# JIN Trading Roadmap

Stand: **7. Oktober 2026**. Projekt `jino101/hummingbot`, Arbeitszweig
`feat/jin-trading-control`, Entwurfs-[PR #2](https://github.com/jino101/hummingbot/pull/2).
Diese Reihenfolge basiert auf der [Codeprüfung](AUDIT-2026-10-07.md).

Ziel: zunächst 5 USDT auf KuCoin, mehrere zentral begrenzte Bots, maximal 10 %
Tagesverlust als Stop-Regel, Smartphone-Bedienung, danach weitere Strategien,
Aktien und Forex. Kapital und Handelsbarkeit vor Echtgeldbetrieb prüfen.

## 0 — Grundlage: vorhanden

- [x] Eigenen Hummingbot-Controller, Beobachtung, Readonly-Prüfungen und Android-Quellen erhalten.
- [x] Unterstützten aktiven USDT-Katalog und erreichbare USDT-Dreiecke automatisch erkennen.
- [x] Route-komplette REST-Batches ohne feste Gesamt-Coin-Grenze rotieren; Cooldown und Abdeckung anzeigen.
- [x] Bitget-Mindestnotional für Nicht-USDT-Quotes umrechnen, fehlende Umrechnung ausschließen.
- [x] Mehrere Paper-Bots, gemeinsame virtuelle 5 USDT, Reinvestition, Not-Aus und 10-%-Tagesregel.
- [x] Dashboard, Recording/Replay, Docker-Build und Compose-Konfiguration.
- [x] Stop fordert Orderstornierung an und behält bekannte Füllungen; nicht endliche Live-Eingaben blockieren.

Abnahmebeleg nach Sicherheitskorrekturen: **212 native Tests, 46 Paper-unittests,
44 Pure-/Mobile-Tests und Docker-Checks grün**, **89 % Coverage** für `jin_trading`.
Zwölf ungültige Eingabeszenarien geprüft; GitHub-Checks im Audit verlinkt.

## 1 — P0: Orderaufsicht und gemeinsames reales Risiko

- [ ] **R01 / F03:** Not-Aus erzeugt Stop-Actions für aktive Executor; Stornierungsbestätigungen,
  späte Füllungen und unbekannte Orders dauerhaft abgleichen.
- [ ] **R02 / F04:** Gemeinsame reale Equity, Gebühren, gehaltene Positionen und reserviertes
  Kapital über alle Bots/Konten führen; 10-%-Grenze mit einheitlichem Tageswechsel.
- [ ] **R03 / F05:** Tatsächliches Orderbuchalter vor Signal und Order prüfen; Reconnect-Lücken blockieren.

**Fertig, wenn:** Teilfüllung, Ordertimeout, Netzwerkabbruch, doppeltes Event,
Not-Aus und Neustart getestet sind; keine zweite Instanz dasselbe Kapital einsetzen
kann; gehaltene Verluste in der globalen Equity erscheinen.

## 2 — P1: belastbare Kurse und 5-USDT-Machbarkeit

- [ ] **R04 / F06–F08:** Bitget-Referenzkurs-Alter und Mindestnotional absichern;
  langsame Börsen isolieren; Gebühren pro Leg samt Flat Fees korrekt bewerten.
- [ ] **R05 / F09:** Tokenidentität, Netzwerke, Mindesttransfer, Empfangsdaten und
  Kapitalrückweg prüfen; authentifizierten Readonly-Adapter für Bitget ergänzen.
- [ ] **R06:** KuCoin-Konto lokal nur lesend verbinden; verfügbare 5 USDT,
  persönliche Gebühren und alle drei Mindestorders einer Route dokumentieren.
- [ ] **R07:** Automatische WebSocket-Subscriptions in Shards, Reconnect und
  Snapshot/Diff-Abgleich; Kataloggröße, Datenalter und Wiederbesuchszeiten messen.

**Fertig, wenn:** Vollständiger API-Katalogumlauf protokolliert; jede Route hat
frische Daten und korrekte Mindestmengen/Kosten. Ergebnis darf auch sein:
„Mit 5 USDT ist derzeit keine Route ausführbar.“ Keine Mindestgrenze umgehen.

## 3 — P1: ein Dashboard und dauerhafter Paper-Betrieb

- [ ] **R08 / F12–F13:** Vorhandene Sites-Oberfläche an dieselbe authentifizierte
  Bot-API anbinden; Coin-Katalog, Ledger und Risikostatus serverseitig teilen.
- [ ] **R09 / F10/F15:** Risiko-Latch bei abgewiesenem Start/Reset dauerhaft
  speichern; Sonderzeichen-IDs, ungültige Beobachtungsdaten, Export und Log-Schreiber absichern.
- [ ] **R10 / F14:** Host festlegen: eigener Linux-Rechner oder Replit Reserved VM
  nach Prüfung von Kosten, Region, API-Erreichbarkeit und Datenhaltung.
- [ ] **R11 / F14:** HTTPS/VPN, Autostart, Sicherung/Wiederherstellung, Zustandsalarm
  und Galaxy-Test; Android-CI passend zum Arbeitszweig und signierte Release-APK.

**Fertig, wenn:** 24 Stunden Paper-Betrieb mit dokumentierten API-Fehlern läuft;
nach Neustart stimmen Ledger/Not-Aus; zwei Geräte sehen denselben Zustand;
veraltete Chancen lassen sich nicht ausführen; eine Sicherung wurde zurückgespielt.

## 4 — P1: Live-Ausführung nach bestandenen Grundlagen

- [ ] **R12 / F11:** Drei-Leg-Executor mit Füllmengen, Restbeständen,
  Gebührenwährung, Fristen, Abbruch und Recovery implementieren.
- [ ] **R13:** Bestehenden Cross-Exchange-Executor an Supervisor und zentrale
  Kapitalreservierung anbinden; bekannte Fill-Mengen statt ursprünglicher Menge verwenden.
- [ ] **R14:** Sandbox-/Demotests und danach dokumentierten, gesondert
  freigegebenen begrenzten Echtgeldtest durchführen.

**Voraussetzung:** R01–R11 bestanden, handelbares Mindestkapital nachgewiesen und
Konten lokal verbunden. Diese Roadmap erteilt keine Freigabe für echte Orders.

## 5 — P2/P3: Wachstum, weitere Strategien, Aktien und Forex

- [ ] **R15 / F16:** Konfigurierbare Kapitalstufen für 5/10/weitere USDT;
  Einsatz und Reservierung wachsen innerhalb derselben globalen Risikogrenze.
- [ ] **R16 / F16:** Market-Making/direktionale Strategien individuell konfigurieren,
  parallel mit Kosten/Slippage testen und zentral stoppen können.
- [ ] **R17 / F17:** Aktien-/Forex-Broker auswählen; Daten-/Orderadapter,
  Handelszeiten, Währungen, Lotgrößen, Gebühren und Demokonto-Prüfungen ergänzen.
- [ ] **R18 / F17:** Daten-/Order-Latenz und Lasttests messen; Infrastruktur
  und Kosten vor Bewerbung eines niedrigen Latenzmodus prüfen.

**Fertig, wenn:** Neue Strategie/Broker hat nachvollziehbare Daten- und
Ausführungstests und kann die gemeinsame Risikogrenze nicht umgehen.

## Plugin-Status und konkrete nächste Arbeit

| Werkzeug | Geprüft | Nächster Einsatz |
|---|---|---|
| GitHub | Vorhandener PR, Code und CI; Issues deaktiviert | Arbeitsliste im PR und dieser Roadmap weiterführen |
| Composio | Tools gesucht, keine aktive GitHub-Verbindung darin | Nach Verbindung GitHub-/Aufgaben-Workflows; Alarmziel erst festlegen |
| Replit | Keine vorhandene App gefunden | Host für denselben Code; Reserved VM prüfen |
| Sites | Vorhandene private JIN-Site samt eigenem Quellcode geprüft | Gemeinsame API statt browserlokaler 10-USDT-/10-Coin-Demo |
| Visualize | Phasenübersicht aus dieser Arbeitsliste | Offene Abnahmekriterien sichtbar halten |

**Nächster konkreter Implementierungsschritt:** R01–R03: aktive Orders stoppen und
abgleichen, reale Portfoliorisiken gemeinsam führen, tatsächliches Buchalter prüfen.
Parallel R06/R10: nur lesender KuCoin-Machbarkeitsbericht und erreichbarer Paper-Host.

Benötigte externe Angaben: ausgewählter Host und später Broker; Kontoverbindung
erfolgt lokal. Zugangsdaten gehören nicht in Chat, GitHub oder Browsercode.

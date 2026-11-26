# JIN Trading-Bot – Integrationsprüfung

**Prüfdatum:** 26. November 2026  
**Ausgangszweig:** `jin/10eur-balanced-build`  
**Ausgangscommit:** `3372fbecaffde8b8a59c6f41ddf2e08d05ba1b70`  
**Prüfart:** statische Prüfung von GitHub-Quellcode, Branches, Pull Requests und dokumentierten Tests. Es wurden in dieser Prüfung weder Python-Tests lokal ausgeführt noch Börsenkonten verbunden oder Orders gesendet.

## Ergebnis

Die vorhandene Implementierung ist eine brauchbare Paper-Trading-Grundlage, aber noch nicht der vereinbarte vollständige Bot mit 10 EUR Gesamtbudget und integriertem Cross-Exchange-Betrieb. Die wichtigsten offenen Punkte sind echte Integrationslücken und keine bloßen UI-Aufgaben.

## Verifizierte Befunde

| Bereich | Befund | Status |
|---|---|---|
| Dreiecksarbitrage | Scanner, drei Legs, Orderbuch-Tiefenprüfung, IOC-Ausführung und Recovery-Code vorhanden. | Teilweise – weitere Fee-/Fill-Abnahme offen |
| Cross-Exchange-Scanner | `scan_with_diagnostics` erkennt Cross-Exchange-Kandidaten. | Vorhanden |
| Cross-Exchange-Worker | `validate_config` weist `strategy == cross_exchange` zurück. Der automatische Worker-Ausführungspfad wählt nur Dreiecksgelegenheiten aus. | Nicht integriert |
| Cross-Exchange-Ausführung | `ExecutionEngine.cross` unterstützt vorfinanzierte Paper-Konten und prüft inzwischen Tiefe, Mindestgrößen und Nettogewinn vor der ersten Paper-Order. Live wird ausdrücklich abgewiesen. | Paper-API vorhanden, Worker-Integration offen |
| Kapital | Beispielkonfiguration nutzt 50 + 50 virtuelle USDT; das separate Profil nutzt 5 USDT. Das Kapitalmodell in Worker, Store und Handelslogik ist USDT-basiert. | 10-EUR-Gesamtlimit fehlt |
| Gebühren | `Book` speichert eine Gebührenquote, aber keine Gebührenwährung. `PaperBroker` verbucht Gebühren in Quote-Währung; die Umrechnung im Orderbuchmodell bildet die Gebührenwährung nicht durchgehend explizit ab. | Modell muss vereinheitlicht werden |
| Börsen-/Netzwerkstatus | Konto-Adapter prüfen API-Rechte, Guthaben und Gebühren. Das ist nicht gleichbedeutend mit einer aktuellen Prüfung, ob Ein- und Auszahlungen eines konkreten Assets über dasselbe Netzwerk auf beiden Börsen aktiv sind. Eine solche Prüfung muss im ausführbaren Kandidatenpfad zwingend verknüpft sein. | End-to-end-Verknüpfung nicht nachgewiesen |
| Mobile Bedienung | Web-Dashboard, API und mobile Dateien sind vorhanden. Die gehostete Oberfläche ist nicht selbst der dauerhaft laufende Python-Handelsprozess. | Oberfläche vorhanden, Hostbetrieb offen |
| 24-Stunden-Paper-Abnahme | Ein Beobachtungsmonitor ist dokumentiert; ein abgeschlossener 24-Stunden-Lauf mit finaler Summary und Fault-/Recovery-Abnahme wurde nicht nachgewiesen. | Offen |
| HFT / V2 | Ein getrennter V2-Zweig enthält einen HFT-Prototyp und weitere Arbitrage-Experimente. Das ist kein Nachweis für getesteten produktiven HFT-Betrieb. | Experimentell, nicht zusammenführen |
| CI | Der Stand vom 20. November hat null GitHub-Actions-Läufe. Der erfolgreiche PR-#2-Testnachweis bezieht sich auf den älteren Commit vom 12. Oktober; die damaligen Actions wurden laut PR-Dokumentation anschließend wieder deaktiviert. | Aktuelle Änderungen unbestätigt |

## Kritische Integrationsaufgaben

### P0 – Vor jeder Echtgeldfreigabe

1. **10-EUR-Portfolio statt USDT-Budget pro Bot**
   - EUR muss die zentrale Budget- und Reporting-Währung sein.
   - EUR/USDT muss aus einer frischen, zeitgestempelten Kursquelle kommen.
   - Alle Wallets, offenen Reservierungen und unbekannten Orders zählen gemeinsam gegen 10 EUR.
   - Bei fehlendem/veraltetem FX-Kurs, nicht erfüllbarer Mindestorder oder unklarer Exposure wird keine neue Position eröffnet.
   - Tests müssen beweisen, dass die Gesamtgrenze auch bei mehreren Bots und parallelen Reservierungen nie überschritten wird.

2. **Gebührenmodell vereinheitlichen**
   - Für jede Markt-/Orderbuchnotierung muss die Gebührenwährung explizit bekannt sein: Base, Quote oder ein drittes Token.
   - Scanner, Paper-Broker, Ausführung und Fill-Abgleich müssen dieselbe Gebührenlogik verwenden.
   - Unbekannte oder nicht umrechenbare Gebühren blockieren den Trade.
   - Regressionstests für Base-, Quote- und Dritt-Token-Gebühren sowie Teilfüllungen ergänzen.

3. **Cross-Exchange als echte Worker-Strategie einbinden**
   - Zwei eigenständige Börsenkonten und deren unabhängige Orderbücher müssen konfigurierbar sein.
   - Beide Bestände sind vorab zu reservieren; automatische Transfers bleiben aus.
   - Tokenidentität, Handelsregeln, Mindestnotional, Gebühren, Tiefe, Teilfüllungen und Recovery müssen geprüft werden.
   - Der Worker darf Cross-Exchange nicht nur anzeigen, sondern muss einen getrennten Paper-Ausführungspfad steuern können.
   - Live bleibt gesperrt, bis beide Handelsplätze separat abgenommen sind.

4. **Netzwerk-/Auszahlbarkeit in den Kandidatenpfad integrieren**
   - Handelsstatus, Einzahlung, Auszahlung und Netzwerkstatus sind unterschiedliche Zustände.
   - Asset, Chain/Netzwerk, Memo/Tag, Mindestbetrag und Gebühren müssen auf beiden Plattformen übereinstimmen.
   - Unbekannt, pausiert oder widersprüchlich bedeutet: Gelegenheit verwerfen.
   - Keine automatischen Auszahlungen oder Transfers; Auszahlungsrechte bleiben deaktiviert.

### P1 – Vor Dauerbetrieb

5. Alle aktuellen Änderungen auf dem Arbeitszweig durch CI laufen lassen; die vorhandenen Workflow-Dateien reichen nicht als Testnachweis.
6. 24-Stunden-Paper-Soak auf einem persistenten Host durchführen, inklusive Datenfeed-Ausfall, veralteter Daten, Neustart, Kill-Switch, unbekannter Order und Wiederherstellung.
7. Mobile Oberfläche mit diesem Host verbinden; HTTPS oder privates VPN, persistente Datenbank, Backups, Restore und unabhängige Zustandsalarme abnehmen.
8. Erst danach eine separate Live-Readiness-Prüfung durchführen. Eine Echtgeldfreigabe ist eine separate Nutzerentscheidung.

### P2 – Später

9. V2-/HFT-Komponenten einzeln portieren, nicht den ganzen experimentellen Zweig blind zusammenführen. Latenz, Durchsatz, Slippage und Ausführungsqualität zuerst messen.
10. Vor weiterer Integration die lokale Fork-Basis gegen das offizielle Hummingbot-Repository aktualisieren. Die lokale Fork-`master`-Basis liegt laut GitHub-Vergleich rund 302 Commits hinter dem offiziellen `master` (Stand 18. November 2026, Hummingbot v2.18.0). Das Update gehört in einen separaten Wartungszweig und benötigt Kompatibilitäts- und Regressionstests.

## GitHub-Arbeitsregeln

- Änderungen bleiben zunächst auf Feature-Zweigen und in Draft-Pull-Requests.
- `master` wird nicht direkt verändert oder automatisch gemergt.
- Bestehende PRs #1, #2 und #3 bleiben getrennt; insbesondere der experimentelle V2-Zweig wird nicht ungeprüft mit dem Paper-Dienst vermischt.
- Keine API-Schlüssel, Passphrasen oder Kontodaten in GitHub einchecken.
- Keine echten Orders, keine automatischen Transfers und keine Auszahlungsberechtigungen während dieser Integrationsphase.

## Abnahmekriterien für „integriert“

Der Bot gilt erst als integriert, wenn:
- das aggregierte EUR-Gesamtlimit automatisiert und getestet ist;
- Gebühren in allen Rechenschritten dieselbe tatsächliche Währung und denselben Betrag verwenden;
- Dreiecks- und Cross-Exchange-Paper-Ausführung beide über denselben Supervisor-/Journal-/Risk-Pfad laufen;
- Netzwerk- und Marktstatus vor jeder Gelegenheit fail-closed geprüft werden;
- die neuen Tests auf dem tatsächlichen Ziel-Commit grün sind;
- der 24-Stunden-Paper-Lauf und die Wiederherstellung dokumentiert bestanden sind.

**Aktuelle Einstufung:** Paper-Grundlage vorhanden; vollständige Integration und Betriebsabnahme offen. Keine Aussage über Profitabilität oder Live-Tauglichkeit.

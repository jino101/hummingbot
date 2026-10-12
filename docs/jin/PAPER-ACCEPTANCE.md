# Beobachteter Paper-Dauerlauf

Der Monitor `scripts/jin_paper_soak.py` liest ausschließlich `GET /api/state`
eines bereits eingerichteten lokalen Dienstes. Er startet und stoppt weder den
Dienst noch Bots; er sendet keine Orders und verändert keine Konfiguration.
Der Dienst kann beim Lesen seines Zustands selbst seine vorhandenen Risiko-
und Statusprüfungen ausführen.

## Start und privates Protokoll

Der Dashboard-Schlüssel muss bereits lokal in `JIN_DASHBOARD_TOKEN` stehen.
Es gibt absichtlich kein Schlüsselargument für die Befehlszeile. Verwende den
gleichen Schlüssel wie beim laufenden Dienst; keinen neuen Schlüssel erzeugen.
Schlüssel, Rohantworten, URLs und Fehlermeldungstexte werden nicht protokolliert.
Der Monitor akzeptiert nur Loopback-Adressen; HTTP-Proxys und Weiterleitungen
sind deaktiviert, damit der Schlüssel lokal bleibt.

Aus dem Repositoryverzeichnis (Python 3.12 oder neuer):

```bash
python scripts/jin_paper_soak.py --url http://127.0.0.1:8788 --duration-seconds 86400 --output ../.local/paper-soak-24h.jsonl
```

Zunächst kann dieselbe Anleitung mit `--duration-seconds 60` und einer anderen
Ausgabedatei für einen kurzen Funktionstest verwendet werden. **60 Sekunden
sind kein 24-Stunden-Nachweis.** Der Dienst und der Monitor müssen während der
gewünschten Dauer laufen; Ruhezustand, Abbruch oder eine geschlossene Konsole
können die Beobachtung unterbrechen. Der Monitor richtet keinen Autostart ein.

Die JSONL-Datei wird exklusiv neu erstellt: vorhandene Ergebnisse werden nie
überschrieben. Unter Unix gilt `0600`; unter Windows erhält sie eine geschützte
DACL mit Vollzugriff nur für den Dateieigentümer. Scheitert die Absicherung,
werden keine Beobachtungsdaten geschrieben. Ergebnisse in einem privaten
lokalen Verzeichnis außerhalb des Repositorys aufbewahren; nicht committen.

Alle fünf Sekunden erfolgt eine Abfrage mit vier Sekunden HTTP-Zeitlimit.
Jede Zeile wird sofort geschrieben. Die erste Zeile beschreibt den Beginn,
dann folgen Stichproben und zuletzt eine Zusammenfassung. UTC-Zeitstempel und
monoton gemessene Laufzeit werden getrennt festgehalten. Strg+C schreibt nach
Möglichkeit eine Zusammenfassung mit `interrupted: true`; ein harter Prozess-
oder Stromausfall kann sie verhindern. **Ohne letzte Summary ist der Lauf
nicht abgeschlossen.** Nach einem Abbruch beginnt ein neuer Lauf in einer
neuen Datei; getrennte Läufe dürfen nicht als ununterbrochene Dauer addiert werden.

## Bedeutung der Ergebnisse

- `completed`: die gewählte Dauer wurde tatsächlich beobachtet, ohne manuellen
  Abbruch oder vorzeitigen Stopp wegen falscher Anmeldung/anderem Kontomodus.
  Abgeschlossene Läufe können Fehler enthalten und damit `passed: false` haben.
- `passed`: strenges **Monitoring-Gate**. Zusätzlich zur vollständigen Dauer
  müssen mindestens zwei Stichproben bis zum Ende vorhanden sein, alle Abfragen
  erfolgreich und Paper-Worker/Portfolio bereit gewesen sein. Keine erkannten
  Feedfehler, Halts, fehlenden/abgelaufenen Marktdaten oder ungültigen Kennzahlen.
  Die größte Stichprobenlücke darf zehn Sekunden nicht überschreiten.
- `readiness_percent`, `readiness_outages`, `stale_samples`, `worker_error_samples`
  und `max_poll_gap_seconds` zeigen Verfügbarkeit und Ausfälle. Readiness-Prozent
  ist ein Anteil der Stichproben, keine kontinuierlich gemessene Verfügbarkeit.
  Ein Ausfall zählt beim Wechsel in eine nicht bereite Phase; der erste bereits
  fehlerhafte Messpunkt zählt ebenfalls. Marktalter wird zusätzlich anhand des
  gelieferten Zeitstempels gegen die lokale Uhr geprüft; die Rechneruhr muss stimmen.
- `paper_pnl_start/end/change` sind Differenzen aus gemeldeter Equity und
  gespeicherter Baseline, keine garantierten oder realisierten Echtgeldgewinne.
  Resets oder Bestandsänderungen während des Laufs können die Zahlen verfälschen.
- Orderzahlen beziehen sich auf eindeutige **beobachtete** IDs und Zustände;
  die IDs selbst stehen nicht im Protokoll. `unique_trades_observed_lower_bound`
  ist nur eine Mindestzahl, weil die API höchstens 100 vergangene Trades liefert.
- `enabled_bot_samples` zeigt, wie oft mindestens ein Bot eingeschaltet war.
  Waren alle Bots gestoppt, steht `observation_mode: scanner_only`. Das ist keine
  Paper-Ausführungsabnahme. `paper_execution_accepted` bleibt deshalb stets `false`.

Keine profitable Route und null Orders sind gültige Ergebnisse; Gewinn oder
Handelsaktivität sind kein Bestehenskriterium. Veraltete Kurse können korrekt
gesperrte Handelsgelegenheiten sein. `passed: false` bei Staleness bedeutet daher
eine verfehlte strenge Datenverfügbarkeitsprüfung, nicht automatisch falsches
Handelsverhalten. Die Fehlerarten sind vor einer Bewertung einzeln anzusehen.

Exitcodes: `0` Monitoring-Gate bestanden, `1` abgeschlossen/nicht bestanden oder
vorzeitig abgebrochen wegen Anmeldung/Modus, `2` Start-/Datei-/Parameterfehler,
`130` Strg+C. Nur die Kombination aus Summary, tatsächlicher Laufzeit und
Fehlerkriterien belegt das jeweilige Ergebnis; der Dateiname allein belegt nichts.

## Grenzen und weitere Abnahme

Dieser GET-Monitor prüft keine absichtlich ausgelösten Ausfälle (Fault Injection),
keine Orderkorrektheit, keine Fill-Realistik, keinen echten Wiederanlauf, keine
Transfers, keine Latenzgarantie und keine echte Handelsfreigabe. Störungen zwischen
zwei Stichproben können unbemerkt bleiben. Ohne beobachtete Orders fehlen auch
Beobachtungen ihrer Lebenszyklen. Dafür sind getrennte Offline-/Integrationstests
und kontrollierte Paper-Fehlerszenarien notwendig. Der Monitor stoppt selbst bei
Fehlern keinen Bot; vorhandene Sicherheitsmechanismen bleiben Aufgabe des Dienstes.

Automatische Tests des Monitors nutzen simulierte Uhren und Antworten:

```bash
python -m unittest discover -s tests_jin -p test_soak.py -v
```

Ein bestandener Test dieser Datei belegt die Monitorlogik, nicht einen tatsächlich
durchgeführten 24-Stunden-Börsenlauf.

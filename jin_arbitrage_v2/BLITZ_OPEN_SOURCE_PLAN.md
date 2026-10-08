# Blitzversion – Open-Source-Integration

**Scope:** schneller nutzbarer Scanner mit Paper-Ausführung. Live-Orders bleiben deaktiviert.

## Bausteine zur Prüfung

| Projekt | Quelle | Geplanter Einsatz |
|---|---|---|
| CCXT | https://github.com/ccxt/ccxt | Vereinheitlichte Exchange-REST-Marktdaten und Marktsymbole |
| Cryptofeed | https://github.com/bmoscon/cryptofeed | Streaming-Feeds / Orderbooks |
| Hummingbot | https://github.com/hummingbot/hummingbot | Bereits vorhandene Connector- und Strategy-Infrastruktur |
| Freqtrade | https://github.com/freqtrade/freqtrade | Ideen für Backtesting und Paper-Simulation |
| NautilusTrader | https://github.com/nautechsystems/nautilus_trader | Event-/Execution-Architektur als Referenz |

**Vor Übernahme:** Lizenz und Version pro Projekt prüfen; Notices erhalten; Abhängigkeiten isolieren. Keine fremden Dateien ungeprüft kopieren. Lizenzkompatibilität muss vor dem Import bestätigt werden.

## Blitz-Meilensteine

1. **Feeds:** zwei Börsen nachweislich live, Fehler sichtbar, Reconnect und stale-quote filter.
2. **Scanner:** mehrere Paare; Preis- und Orderbook-Tiefe; Gebühren und Slippage; ausführbare Größe.
3. **Paper:** deterministische Simulation, Teilfüllungen, Gebühren, P&L und Limits.
4. **UI:** mobilfreundliche Live-Chancenliste mit Feed-Status.
5. **Release-Gate:** Offline-Tests, Live-Read-Only-Smoke-Test, 24h stabiler Paper-Lauf.

## Abgrenzung

- Alle 40 Ideen bleiben in ROADMAP_OPTION_E.md.
- Blitzversion ist kein echtes HFT und garantiert keinen Gewinn.
- Kein Live-Trading, keine Exchange-Keys, keine automatischen Auszahlungen.

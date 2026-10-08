# JIN Arbitrage V2 – Option E (40 Ideen)

Status: Roadmap, **keine Zusage fertiger Features**. Standard bleibt PAPER; keine echten Orders oder API-Schlüssel in Tests.

## Phase 01: Marktdaten
WebSockets aller Börsen; Reconnect; Stale Quotes; Depth Cache; Latenz; Tests

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 02: Ausführbare Arbitrage
Fees; Slippage; Netzwerkstatus; Liquidität; Ranking; realistische Paper-Fills

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 03: Risikokontrolle
Circuit Breaker; Positionsgrößen; Partial-Fill-Simulation; Hedge-Simulation; Rebalancing

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 04: Arbitrage-Strategien
Cross; Triangular; Quadrangular; CEX-DEX; DEX-DEX; Funding; Cash-and-Carry

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 05: Solana & weitere Chains
Meme Discovery; Token-Prüfung; Jupiter/Raydium/Orca/Meteora; EVM später

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 06: Quant-Strategien
Stat Arb; Pairs; Mean Reversion; Momentum; Breakout; Market Making; Grid

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 07: Analyse & Forschung
Liquidationen; On-Chain; DeFi-Yield; Portfolio; KI-Anomalien; Backtesting

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Phase 08: Produkt & Betrieb
SQLite/PnL; Dashboard; Alerts; 24/7 Monitoring; Deployment; Integrationstests

**Abnahme:** deterministische Offline-Tests, dann getrennte Live-Marktdaten-Tests ohne Orders. Fehler müssen sichtbar sein; Gebühren, Latenz und Datenalter dokumentieren.

## Aktueller nächster Meilenstein

- [x] Binance Live-Bid/Ask auf dem Nutzerterminal beobachtet
- [x] Stream-Fehler werden aus merge_streams gemeldet
- [x] Offline-Tests für Parser und Stream-Merge hinzugefügt (noch lokal auszuführen)
- [ ] Bybit Live-Verbindung separat bestätigen
- [ ] Reconnect mit Backoff, Heartbeats und Statusanzeige
- [ ] Stale-Quote-Schutz und ausführbare Orderbook-Tiefe
- [ ] Vollständige Paper-Execution mit Gebühren und Teilfüllungen

## Sicherheits-Gates

Kein Live-Trading vor unabhängigen Integrationstests, Ausfalltests, Risikofreigabe und ausdrücklicher Entscheidung des Nutzers. Geschätzter Paper-PnL ist kein realisierter Gewinn.

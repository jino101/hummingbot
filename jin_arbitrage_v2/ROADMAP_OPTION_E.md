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


## Implementation sweep 2026-10-08

The eight roadmap phases now have code-level paper/research coverage, with these boundaries:

- Phase 01: CEX REST depth, Binance/Bybit streams, reconnect/backoff, stale checks, feed health.
- Phase 02: depth-aware cross-exchange scanner, cost model, market/network compatibility primitives, partial paper fills.
- Phase 03: risk limits, kill switch, partial-fill paper execution, rebalance planning. Hedge remains simulation/research, never an automatic live order.
- Phase 04: cross, triangular/depth triangular, generic multi-leg/quadrangular, DEX normalization, funding and cash-and-carry research scanners.
- Phase 05: Solana token filtering/discovery primitives plus Jupiter/Raydium/Orca/Meteora adapter interfaces and Gateway quote client. Real provider quote responses still require live read-only integration tests.
- Phase 06: stat-arb plus pairs z-score, mean reversion, momentum, breakout, market-making quotes and grid research helpers.
- Phase 07: liquidation pressure, on-chain flow, yield ranking, portfolio metrics, anomaly scoring and deterministic backtest helper.
- Phase 08: SQLite trade store, dashboard payload, alerts, runners and end-to-end offline acceptance test.

### Definition of complete
“Implemented” here means code exists and is covered by deterministic tests where feasible. It does **not** mean every external venue/API has been live-verified. Live trading remains disabled. Release still requires the test suite, read-only smoke tests, provider credentials/API access where required, and a sustained paper run.

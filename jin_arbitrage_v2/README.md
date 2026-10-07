# JIN Arbitrage Bot V2

Experimental arbitrage extension layer for this Hummingbot fork.

## Scope
- 13 CEX configuration
- Cross-exchange opportunity model
- Triangular arbitrage scanner
- Solana / meme-coin discovery and DEX quote adapters
- Jupiter, Raydium, Orca and Meteora adapter interfaces
- CEX<->DEX and DEX<->DEX opportunity normalization
- liquidity, slippage, price-impact and token-safety filters
- risk engine and execution state machine
- paper mode by default; live mode requires explicit opt-in
- mobile dashboard API data model

## Safety
Live trading is OFF by default. Do not enable real orders until connector-specific tests, partial-fill handling and risk limits have been validated.

## Licensing
This folder is original integration code and interfaces. External open-source components may only be incorporated when their licenses are compatible and their notices are retained.

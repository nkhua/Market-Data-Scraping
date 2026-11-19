# Trading Bot

Production-structured Python starter for a multi-asset trading research system.

The default runtime is now `research_only`. It can scan the current U.S. stock universe when IBKR market data is configured, never invents market data, and rejects candidates when real data is unavailable, stale, or incomplete.

## Current Pipeline

```text
run_once
  -> build_services
  -> MultiAssetResearchPipeline.run
  -> configured universe builders
  -> all-stock Nasdaq Trader universe builder
  -> optional news catalyst universe builder
  -> research market data provider
  -> optional research news provider
  -> asset-specific scanner
  -> ResearchRiskGate.evaluate
  -> SEC earnings evidence and cross-source checks for eligible stocks
  -> ClaudeDecisionService.review
  -> ResearchStore persistence
```

Claude receives only filtered candidates. Claude can make the research decision: thesis, direction, confidence, opportunity score, and suggested strategy. Broker execution still requires deterministic risk approval.

## Code Layout

```text
app/research/   universe builders, real market/news data, scanners, research risk gate
app/claude/     Claude client, prompt construction, structured decision parsing
app/execution/  order manager, trade executor, execution risk/position sizing
app/broker/     broker connectivity adapters, currently IBKR connection/contract lookup
app/storage/    SQLite persistence for scans, signals, Claude decisions, risk decisions, orders
```

## Supported Research Shapes

Phase 1 adds domain support for:

- stocks
- ETFs
- options
- futures
- forex, crypto, and bonds as disabled structural types

Options and futures have separate validation rules. Options require a known max loss or defined-risk structure. Futures require margin and expiry/rollover data.

## Data Policy

Production code must not use invented prices, catalysts, portfolios, or broker state. Blank provider settings mean data is unavailable.

The safe default result is therefore usually:

```json
[]
```

That is intentional when no real market data provider is configured. Wire IBKR before expecting opportunities.

## Configuration

Edit [settings.yaml](config/settings.yaml).

Important sections:

- `app.trading_mode`
- `app.enable_live_trading`
- `universe`
- `research`
- `risk`
- `broker`
- `claude`

Default enabled asset classes:

```yaml
research:
  allowed_asset_classes:
    - "stock"
    - "etf"
```

Options and futures exist structurally but stay disabled until their data, liquidity, and risk requirements are configured.

## Environment

Create `.env` from `.env.example`.

Key variables:

- `ANTHROPIC_API_KEY`
- `IBKR_HOST`
- `IBKR_PORT`
- `IBKR_CLIENT_ID`
- `IBKR_ACCOUNT_ID`
- `TRADING_MODE=research_only`
- `ENABLE_LIVE_TRADING=false`
- `ALLOWED_ASSET_CLASSES=stock,etf`
- `MARKET_DATA_PROVIDER`
- `NEWS_DATA_PROVIDER`
- `ALL_STOCKS_UNIVERSE_ENABLED=true`
- `ALL_STOCKS_INCLUDE_ETFS=false`
- `ALL_STOCKS_MAX_SYMBOLS=0`
- `ALPHA_VANTAGE_API_KEY`
- `NEWS_FOCUS_ENABLED=false`
- `NEWS_FOCUS_TOPICS=financial_markets,earnings,mergers_and_acquisitions,ipo,economy_macro,economy_monetary`
- `NEWS_FOCUS_MAX_ARTICLES=50`
- `NEWS_FOCUS_MAX_SYMBOLS=25`
- `MAX_RISK_PER_TRADE_PERCENT`
- `MAX_PORTFOLIO_EXPOSURE_PERCENT`
- `MAX_MARGIN_USAGE_PERCENT`
- `MIN_LIQUIDITY_THRESHOLD`
- `ALLOW_OPTIONS=false`
- `ALLOW_FUTURES=false`
- `ALLOW_FOREX=false`
- `ALLOW_CRYPTO=false`
- `ALLOW_SHORTING=false`
- `ALLOW_NAKED_OPTIONS=false`

## Running

```bash
python scripts/run_dry_cycle.py
```

or:

```bash
python scripts/run_paper.py
```

Both use the configured runtime. With the default `research_only` settings and no real market data provider, no broker order path runs.

## Real IBKR Research Data

To let the research layer use IBKR as the real source, run TWS or IB Gateway with API access enabled, then configure:

```env
MARKET_DATA_PROVIDER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=101
IBKR_ACCOUNT_ID=your_paper_account
IBKR_STOCK_SCANNER_ENABLED=true
IBKR_STOCK_SCANNER_CODES=HOT_BY_VOLUME,TOP_PERC_GAIN
IBKR_STOCK_SCANNER_MAX_RESULTS=25
```

When IBKR is connected and market data permissions are available, the research pipeline can:

- pull account context and positions
- load the current U.S. stock universe from Nasdaq Trader's symbol directory
- discover stock candidates from IBKR scanner rows
- qualify contracts
- request top-of-book quote data
- request historical bars
- compute trend, breakout, volume, and volatility signals
- send only passing candidates to Claude

If TWS is disconnected, market data permissions are missing, quote data is empty, or historical bars are empty, the candidate is rejected before Claude.

## All-Stock Universe

When `ALL_STOCKS_UNIVERSE_ENABLED=true` and `MARKET_DATA_PROVIDER=ibkr`, the research layer loads the current U.S. stock universe from Nasdaq Trader:

- `nasdaqlisted.txt`
- `otherlisted.txt`

The builder excludes test securities and, by default, ETFs. Set `ALL_STOCKS_INCLUDE_ETFS=true` only if you want ETFs added to this broad universe. `ALL_STOCKS_MAX_SYMBOLS=0` means no cap; use a small value only for local smoke checks.

This does not mean every symbol is sent to Claude. Every symbol is scanned with real IBKR data first, then liquidity/risk filters run, then only the configured top candidates reach Claude.

## Real News-Focused Research

The research layer can also use Alpha Vantage's `NEWS_SENTIMENT` endpoint as a real catalyst source.

To enrich configured or IBKR-discovered instruments with news context:

```env
NEWS_DATA_PROVIDER=alpha_vantage
ALPHA_VANTAGE_API_KEY=your_key
```

To also discover candidates from recent market news:

```env
NEWS_FOCUS_ENABLED=true
NEWS_FOCUS_TOPICS=financial_markets,earnings,mergers_and_acquisitions,ipo,economy_macro,economy_monetary
NEWS_FOCUS_MAX_ARTICLES=50
NEWS_FOCUS_MAX_SYMBOLS=25
```

News-focused candidates are not sent straight to Claude. The system still requires real market data, liquidity checks, and risk validation first. If the news provider is unavailable, returns an error, or produces no usable ticker context, the news-focused builder returns no instruments.

## Earnings, Source Checks, and Cited Research

For stocks that pass the research gate and fit within the Claude candidate limit, the pipeline collects evidence before requesting a thesis:

- **Earnings reports:** [SEC EDGAR Company Facts](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) supplies US GAAP revenue, net income, and diluted EPS where reported. The parser selects the latest usable quarterly and annual periods separately, excludes longer quarterly year-to-date figures, and retains the filing date, taxonomy field, unit, and filing link for each value.
- **Financial comparisons:** [Alpha Vantage income statements](https://www.alphavantage.co/documentation/#income-statement) are compared with the filing for the same metric, fiscal period type, period end, and reported currency. Revenue and net income match within the greater of $1 and 0.01%. Diluted EPS stays single-source because the comparison feed does not provide an equivalent figure. Alpha Vantage can derive its figures from the same SEC filing, so this check measures agreement with the vendor's normalization.
- **Price comparisons:** The latest eligible IBKR regular-session USD daily close within the past seven days is compared with the [Alpha Vantage daily close](https://www.alphavantage.co/documentation/#daily) for that exact session. Both providers must identify the intended market data. Matches allow the greater of one cent and 0.01%. The check excludes the current UTC date. Feed conventions and [IBKR split adjustments](https://interactivebrokers.github.io/tws-api/historical_bars.html) can explain a discrepancy. The check covers the historical close only.
- **Explainability:** Claude returns source IDs for the thesis, bull case, bear case, each catalyst, and each risk. IDs resolve to prices, publisher-attributed news, filings, or specific source checks. Python rejects missing or unknown IDs and requires human review with an `avoid` direction on any cross-source conflict. The numeric comparisons are deterministic. Citation validation checks that references exist, while the reader still assesses whether those references support the written interpretation.

To run a single-stock smoke test with real providers, start TWS or IB Gateway with API access and market-data permissions, set `universe.stock_symbols` to a stock such as `[MSFT]` in `config/settings.yaml`, and configure `.env`:

```env
TRADING_MODE=research_only
ENABLE_LIVE_TRADING=false
MARKET_DATA_PROVIDER=ibkr
NEWS_DATA_PROVIDER=alpha_vantage
ALL_STOCKS_UNIVERSE_ENABLED=false
IBKR_STOCK_SCANNER_ENABLED=false
NEWS_FOCUS_ENABLED=false
HISTORICAL_BAR_SIZE=1 day
SEC_EDGAR_USER_AGENT="Your organization your-contact@example.com"
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key
ANTHROPIC_API_KEY=your_anthropic_key
```

Use your own contact details in the [SEC User-Agent](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data). Set the IBKR host, port, and account values for your setup. Run `python scripts/run_dry_cycle.py` from the project root. Each eligible stock uses up to two Alpha Vantage requests for cross-checks in addition to its news request, so size the universe and schedule to your plan's quota.

Inspect `candidate.evidence` and `claude_analysis.citations` in the cycle JSON or the saved SQLite `risk_decisions` payload. `matched` means the compared values agree within the recorded tolerance. `conflict` retains both values and the tolerance. `unverified` records why a match could not be established, such as a missing credential, rate limit, or incompatible fiscal date. `candidate.evidence.filings.reason` surfaces an unavailable filing feed even when there are no individual earnings checks. News is attributed to its publisher, and the system does not fact-check arbitrary article text.

## Verification

```bash
python -B -m pytest
```

The offline tests cover missing and stale data, asset-specific validation, universe parsing, filing normalization, cross-source matches and conflicts, unavailable or incomparable data, citation validation, and persistence through the research cycle. Live provider access is verified separately with the smoke test above.

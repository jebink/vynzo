# VYNZO architecture

Monorepo, modular architecture. Target layout below; **only Phase 1 is built**. Folders for
later phases contain a README saying what they will hold.

## Layout

```
vynzo/
├── apps/
│   ├── web/                  Next.js website                              Phase 1
│   ├── mobile/               React Native / Expo                          Phase 2
│   └── admin/                Internal operations dashboard                Phase 2
├── services/
│   ├── api/                  FastAPI, modular by business domain          Phase 1
│   ├── market-ingestion/     Provider adapters (NSE/BSE/vendors)          Phase 1 (Python)
│   ├── fundamentals-worker/  Statements and corporate actions             Phase 1
│   ├── analytics-worker/     Indicators, signals, news sentiment          Phase 1 (signals); rest Phase 2
│   ├── candle-worker/        OHLCV aggregation and corrections            Phase 2
│   ├── notification-worker/  Alerts delivery                              Phase 2
│   └── market-processor/     Tick trade/quote normalization               Phase 3
├── packages/                 Shared contracts (api-client, contracts)
├── database/
│   ├── postgres/             TimescaleDB migrations (dbmate)              Phase 1
│   ├── redis/                Cache key conventions                        Phase 2
│   └── clickhouse/           Tick and order-book DDL                      Phase 3
├── infra/                    compose/, cron/
├── data/                     Local development data only
├── scripts/                  bootstrap, migrate, backup/restore
├── tests/                    Cross-service integration, e2e, replay
└── docs/                     Architecture, ADRs, API, data contracts, runbooks
```

## Data flow (Phase 1)

```
providers (NSE/BSE/vendor) ──► market-ingestion ──► TimescaleDB ◄── fundamentals-worker
                                                       │  ▲
                                                       │  └── analytics-worker (indicators, signals)
                                                       ▼
                                                  services/api ──► apps/web
```

Phase 3 puts an event bus (Redpanda) between ingestion and storage, adds `market-processor` and
ClickHouse for tick data, and archives raw events immutably for replay.

## API module layout

Each domain module in `services/api/app/modules/<domain>/`:

| File | Responsibility |
|---|---|
| `router.py` | HTTP only: parse request, shape response |
| `schemas.py` | Pydantic request/response models (the API contract) |
| `service.py` | Business use cases |
| `repository.py` | SQL / persistence |
| `scoring.py` | (stock_grading) pure, versioned grading logic |
| `tests/` | Module tests |

## Phases

1. **Working research platform**: web, api, market-ingestion, fundamentals-worker,
   analytics-worker (signals), postgres, compose. Licensed historical/EOD data, fundamentals,
   stock pages, basic grading.
2. **Advanced research**: screening, portfolios, watchlists, auth, financial-ratio history,
   candle aggregation, data-quality dashboards, reproducible grading models.
3. **Full tick infrastructure**: Redpanda, ClickHouse, order-book reconstruction, provider
   reconciliation, archival and replay. Only once licensed feeds and measured workload justify it.

## Architectural rules

1. **One authoritative instrument identity system.** Company IDs, exchange listing IDs and provider
   tokens stay distinct.
2. **Raw data is immutable.** Normalized and derived datasets can be rebuilt from retained source data.
3. **Migrations live in one place** (`database/`). Services never create or alter shared tables.
4. **Shared packages hold contracts, not business logic.** No giant `common/`.
5. **Every analytics result has provenance and a version**: source data, calculation version, as-of timestamp.
6. **All ingestion supports replay and validation.** A successful API response is not proof of complete coverage.
7. **No microservice without an operational reason.** Split only for scaling or isolation needs.

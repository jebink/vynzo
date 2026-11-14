# database

The one place where schema changes live (architecture rule 3). Services read and write tables;
they never create or alter them.

| Folder | Phase | Contents |
|---|---|---|
| `postgres/` | 1 | PostgreSQL + TimescaleDB migrations (dbmate) |
| `clickhouse/` | 3 | Tick-data and order-book DDL |
| `redis/` | 2 | Cache key conventions |

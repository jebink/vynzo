# tests

Cross-service tests. Unit tests live next to each service (`services/*/tests`, `apps/web`).

| Folder | Contents |
|---|---|
| `integration/` | Services against a real TimescaleDB (migrations applied) |
| `e2e/` | Web + API, user flows |
| `replay/` | Re-run ingestion over recorded provider data and compare outputs (architecture rule 6) |

# packages

Shared **contracts**, not business logic (architecture rule 4). No `common/` dumping ground.

| Package | Phase | Contents |
|---|---|---|
| `api-client/` | 1 | TypeScript client generated from the API's OpenAPI schema, used by `apps/web` (and later `apps/mobile`) |
| `contracts/` | 3 | Event schemas for the event bus (raw and normalized market events) |

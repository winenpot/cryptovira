# ADR 0007 — `MarketDataSource` as a `Protocol`, backed by a project-owned `httpx` client

**Status:** Accepted · 2026-08-14

## Context

Step 3 needs candles in Postgres, and something that fetches them from an exchange. The old
system never actually solved this cleanly:

- `old-version/binance/` is a full vendored fork of `python-binance`, frozen at whatever state it
  was in when copied in. `docs/roadmap.md`'s "deliberately dropped" table already calls for
  retiring it in favor of "a maintained client."
- A separate microservice, `old-version/crypto-price/`, used the third-party `cryptofeed` library
  to stream klines over WebSocket into **Redis**, never Postgres. Candle data had no database
  representation at all, and therefore no idempotency mechanism beyond incidental dedup from
  Redis sorted-set scoring.
- Nothing in the old codebase separated "how we talk to an exchange" from "what we do with the
  data" — call sites reached for the vendored client directly (`core/apps/market/utils/helper.py`,
  `core/apps/market/tasks/price.py`), so there was no seam a test could use to avoid the network.

This is also the first place the rewrite needs "an interface tests can swap a fake behind" —
`src/` has none yet (confirmed: no `Protocol`/`abc.ABC` anywhere before this).

## Decision

`MarketDataSource` (`src/cryptovira/apps/market/sources/base.py`) is a `typing.Protocol`, not an
`abc.ABC`:

```python
class MarketDataSource(Protocol):
    def get_klines(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int = 500,
        start_time: datetime | None = None,
    ) -> Sequence[Kline]: ...
```

Structural typing means the real implementation and `tests/apps/market/fakes.py`'s
`FakeMarketDataSource` need no shared base class — satisfying the method signature is enough,
which is the lower-ceremony choice for a single-method interface with exactly one production
implementation today.

The real implementation, `BinanceRestMarketDataSource`
(`src/cryptovira/apps/market/sources/binance.py`), is a ~70-line `httpx` client against Binance's
public `GET /api/v3/klines` — no vendored fork, and deliberately not the `python-binance` PyPI
package either:

- Public spot klines need no authentication, so there is nothing an off-the-shelf client's
  credential handling would buy here.
- `python-binance` ships no type stubs. Under this project's `strict` mypy, that means either a
  new entry in `pyproject.toml`'s explicit `ignore_missing_imports` override list — a "conscious
  decision" per that list's own comment — or fighting an untyped dependency at every call site.
  `httpx` ships `py.typed` and needs no override.
- `python-binance` wraps spot, futures, margin, options, and websockets. One public REST endpoint
  doesn't need that surface, and a ~70-line client confined to `apps/market/sources/` is easier to
  audit than trusting an unreviewed fraction of a much larger package.

`market_data_base_url` (`config.py`) is a typed setting, not a hardcoded constant in the client —
so tests or CI can point it at a mock server, and a testnet is a config change, not a code change.
There is no `MARKET_DATA_SOURCE=binance|fake` toggle: one real implementation exists, and
`get_market_data_source()` (`sources/__init__.py`) is the swap point tests use via
`monkeypatch`, which is enough without a config-driven strategy pattern guarding a single
concrete class.

### Idempotency

Reuses the principle ADR 0005 already established for `accounts.User.email`, applied to candles:
`Candle`'s `UniqueConstraint(fields=["currency", "interval", "open_time"])` is what actually
prevents a duplicate row under `task_acks_late` + `task_reject_on_worker_lost` redelivery — not
application-level `get_or_create` logic, which was the old `Currency` model's only idempotency
mechanism and doesn't exist at all for candles in the old system. `ingest_candles`
(`apps/market/tasks.py`) writes with `bulk_create(candles, ignore_conflicts=True)`: a closed
candle is an immutable fact, so a redelivered task has nothing to *update*, only a duplicate
insert for the database to silently reject.

## Consequences

- Adding a second exchange, or a backtest-replay source for the strategy engine (step 4), is a
  second `MarketDataSource` implementation — no changes to `tasks.py` or the `Candle` model.
- The `httpx` client stays thin on purpose: no retry/backoff, no rate-limit handling, no futures
  support. If a real rate-limit problem shows up in practice, it's a small addition to
  `BinanceRestMarketDataSource`, not a reason to reach for a heavier client now.
- `ingest_candles` must keep discarding any kline whose `close_time` hasn't passed yet (Binance's
  klines response can include the still-forming bar as the last element). Writing that bar once
  would be permanent under `ignore_conflicts=True` — there is no later "correct" for a row that
  silently loses every future conflict.

## We would revisit if

A second exchange integration needed something `get_klines`'s current signature can't express
(e.g. a paginated cursor beyond `start_time`/`limit`), or public klines stopped being enough and
authenticated market data (order book depth, user-data streams) became necessary — at which point
this ADR's "no auth needed" premise no longer holds and credential handling would need the same
encryption-at-rest treatment ADR-worthy for step 6 (broker execution).

# Architecture decision records

One file per decision that would otherwise be re-litigated in six months. Format: context →
decision → consequences → what would make us change our mind.

An ADR is immutable once accepted. To reverse a decision, write a new ADR that supersedes it and
add a `Superseded by` line to the old one.

| #                                         | Decision                                    | Status   |
| ----------------------------------------- | ------------------------------------------- | -------- |
| [0001](0001-rewrite-instead-of-upgrade.md) | Rewrite rather than incrementally upgrade    | Accepted |
| [0002](0002-uv-for-packaging.md)           | uv for packaging and the Python toolchain    | Accepted |
| [0003](0003-rabbitmq-as-broker.md)         | RabbitMQ as the Celery broker, Redis as cache | Accepted |
| [0004](0004-single-settings-module.md)     | One settings module, typed env config        | Accepted |
| [0005](0005-custom-user-model.md)          | Thin, email-based custom user model          | Accepted |
| [0006](0006-ta-lib-packaging.md)           | TA-Lib via prebuilt wheels, no compile step  | Accepted |
| [0007](0007-market-data-source-interface.md) | `MarketDataSource` as a `Protocol`, `httpx`-backed | Accepted |

# ADR 0003 — RabbitMQ as the Celery broker, Redis as cache only

**Status:** Accepted · 2026-08-13

## Context

The old system used Redis for everything: Celery broker, result backend, and cache. Its tasks
include placing real orders on an exchange. The failure question that matters is: *if a worker dies
between receiving a message and finishing the work, what happens to that message?*

- **Redis as a broker** has no real acknowledgement protocol. Celery emulates one with a visibility
  timeout: an unacknowledged message is re-queued after N seconds, and the default N (1 hour) is
  longer than most people's task timeouts. Messages in flight are lost on failover because Redis
  replication is asynchronous, and there is no dead-letter concept — a message that always fails
  is either retried forever or dropped.
- **RabbitMQ** is a message broker: per-message `basic.ack`, broker-side redelivery the moment a
  consumer connection drops, publisher confirms so the producer knows a message was persisted,
  durable queues, quorum queues for replication, and dead-letter exchanges for poison messages.

The counter-argument is operational weight — RabbitMQ is a second stateful service to run, monitor,
and upgrade. For a system that moves money, that cost is worth paying.

## Decision

**RabbitMQ 4** is the Celery broker. **Redis 8** stays, restricted to Django's cache and short-lived
locks, configured with no persistence and `allkeys-lru` eviction — treating it as the disposable
component it now is. Task results go to **Postgres** via `django-celery-results`, so a result
survives a broker restart and can be joined against domain tables.

Worker settings chosen to match (`src/cryptovira/celery.py`):

| Setting                         | Value  | Why                                                       |
| ------------------------------- | ------ | --------------------------------------------------------- |
| `task_acks_late`                | `True` | Ack after the task returns, so a crash redelivers the work |
| `task_reject_on_worker_lost`    | `True` | A killed worker's task is requeued, not silently dropped   |
| `worker_prefetch_multiplier`    | `1`    | No hoarding; a slow task cannot park others behind it      |
| `task_time_limit` / soft limit  | 300/270 | A hung exchange call dies rather than pinning a worker    |

`acks_late` means a task can run **twice** (crash after side effect, before ack). That is the
correct trade — losing an order is worse than repeating one — but it makes **idempotency a hard
requirement** for every task that writes: natural keys on ingest, idempotency keys on orders,
`get_or_create`/`SELECT … FOR UPDATE` rather than blind `create`.

Queues are split by blast radius: `market` (price/indicator work), `orders` (execution),
`default` (everything else), so slow price polling cannot starve order placement.

## Consequences

- One more stateful service in compose, CI, and production; RabbitMQ needs its own health checks,
  memory watermarks, and upgrade path.
- Developers must understand AMQP concepts (exchange, routing key, queue, DLX) to debug delivery.
- Deliberate redelivery semantics mean tasks must be written idempotently — enforced by review and
  tested by running tasks twice in the suite.

## Operational note: RabbitMQ 4 and Celery's control queues

RabbitMQ 4 refuses deprecated features by default, and Celery's remote-control (pidbox) and event
channels still declare **transient, non-exclusive** queues. Against a stock RabbitMQ 4 node the
worker dies on startup:

```
amqp.exceptions.InternalError: Queue.declare: (541) INTERNAL_ERROR -
Feature `transient_nonexcl_queues` is deprecated.
```

`docker/rabbitmq/10-cryptovira.conf` permits that one feature. The alternative — setting
`worker_enable_remote_control=False` and `worker_send_task_events=False` — also removes
`celery inspect ping`, which is the worker's health check, and with it any ability to inspect a
running worker. Revisit when kombu declares those queues durable: the feature is slated for
removal in a future RabbitMQ major, and then the flag stops working.

## We would revisit if

The workload became purely fire-and-forget with no money involved (Redis would then be simpler), or
if throughput reached the point where a log-based broker like Kafka, with replay and partitioning,
fit better than a queue.

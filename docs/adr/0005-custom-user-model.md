# ADR 0005 — A thin, email-based custom user model

**Status:** Accepted · 2026-08-14

## Context

Django cannot swap the user model after the first migration touches it — `AUTH_USER_MODEL` must
be set before `migrate` runs for the first time on a real database. Step 2 is therefore the last
possible moment to get this right; the old system's model is the cautionary example of getting it
wrong.

`old-version/core/apps/account/models/users.py` is a single `AbstractUser` subclass carrying
identity (`username`, `uuid`, `email`), Telegram linkage (`telegram_username`,
`telegram_user_id`, `confirm_user_id`), referral/growth (`referral_code`, `referred_by`,
`referral_share_prize_percent`), billing (`credit_wallet`, `consumed_credit_wallet`,
`transfer_pending_credit_wallet`), and trading defaults (`preferred_quantity`,
`preferred_risk_ratio`, `preferred_leverage`, `preferred_backtest_period`) — thirty-odd fields, a
529-line `merge_with()` that hand-transfers rows across seventeen other models, and a `save()`
override that both derives `username` from `email`/`telegram_user_id` *and* enforces email
uniqueness by querying before saving:

```python
similar_users = User.objects.filter(email=self.email).exclude(pk=self.pk)
if similar_users.exists():
    raise ValidationError(...)
```

That check-then-save has no database constraint backing it — `email` is declared
`unique=False`. Two concurrent registrations with the same email can both pass the check before
either commits, and the database happily stores two rows with the same address.

## Decision

A minimal identity model, `cryptovira.apps.accounts.models.User`, subclassing
`AbstractBaseUser` + `PermissionsMixin` directly (not `AbstractUser`) rather than trimming one
down:

- **`email` is `USERNAME_FIELD`, with a real `unique=True` constraint.** No derived `username`,
  no fallback chain, no app-level race. Modern clients log in with an address, not a handle.
- **`uuid` is the public identifier** (`default=uuid.uuid4`, indexed, unique, non-editable) —
  carried over from the old model; it is the one design choice there worth keeping; never expose
  the integer primary key in a URL or a JWT `sub` claim.
- `first_name`, `last_name`, `is_active`, `is_staff`, `date_joined` — the standard set
  `PermissionsMixin` and admin expect.
- **Everything else stays out**, because it belongs to a domain that has not been built yet:
  Telegram linkage → the notifications app (step 5), referrals and credit wallets → payment
  (step 7), trading preferences → the strategy engine (step 4). Each of those gets its own model
  with a `ForeignKey(User)`, not a column bolted onto identity. `merge_with()`'s reason for
  existing — users accumulate duplicate accounts across signup paths (email, Telegram, Google) —
  is real, but it is a **growth/support feature**, not something identity needs to carry from day
  one; it can be rebuilt later against whatever the final related-model set turns out to be.
- Authentication is **JWT** (`djangorestframework-simplejwt`): short-lived access tokens (15 min),
  rotating refresh tokens (7 days) with `BLACKLIST_AFTER_ROTATION`, and a `logout` endpoint that
  blacklists the presented refresh token. This is the mitigation the interview notes
  ([`docs/interview/01-foundations.md`](../interview/01-foundations.md) doesn't cover it — module
  02 does) call for: JWT's revocation problem is real, so revocation is wired in from the start
  rather than left as a known gap.

## Consequences

- No username/password-by-handle login. If a product reason for handles emerges (public profile
  URLs, @mentions), it is a separate, explicitly-nullable field added later — not a resurrection
  of the old fallback logic.
- Every later step that needs a user-scoped field (Telegram ID, referral code, credit balance)
  adds its own small model instead of growing this one. More tables, less coupling — a payment
  migration no longer has to touch the identity table, and `accounts` never imports from
  `payment` or `notifications` the way the old `User.plan` property imported from `payment.Plan`.
- `merge_with()`'s functionality does not exist yet. Duplicate-account merging is deferred until
  there is a second real signup path (Telegram, OAuth) that can actually produce duplicates —
  building it against a single email-only path would just be guessing at the shape it needs.

## We would revisit if

A second identity provider (OAuth, Telegram login) landed before payment/notifications did, in
which case account-merging would need to be pulled forward — still as its own module, not as
fields on `User`.

# Module 02 — Accounts & JWT

Covers roadmap step 2: the custom user model, password handling, JWT authentication, DRF's
class-attribute idioms, throttling, and a couple of real bugs this build actually hit along the
way — those make the best questions, because the answer is "here's the exact failure," not a
textbook paragraph.

---

## A. Custom user models

### A1. Why must `AUTH_USER_MODEL` be decided before the first `migrate`, and what actually breaks if you change it later?

Every app that references "the user" — `admin.LogEntry`, `auth.Permission`'s M2M through table,
any app you write with a `ForeignKey(settings.AUTH_USER_MODEL)` — gets that foreign key **resolved
to a concrete table at migration-apply time**, not re-resolved later. If migrations already ran
with `AUTH_USER_MODEL = "auth.User"` and you switch to a custom model afterward, the old
`auth_user` table still physically exists, already-applied migrations' FK constraints still point
at it, and Django's migration *state* now disagrees with the migration *history*. There is no
clean migration path out — the practical fix on a database with no real data is to drop it and
re-migrate from scratch with the model decided from the start.

> **In this repo:** this happened literally, mid-build — step 1's verification `migrate` ran
> before `accounts.User` existed, using Django's default user model. Swapping `AUTH_USER_MODEL`
> afterward required `docker compose down -v` and a clean `migrate`. `CLAUDE.md` now states the
> rule explicitly for exactly this reason.

### A2. `AbstractUser` vs `AbstractBaseUser` + `PermissionsMixin` — when do you reach for which?

`AbstractUser` is `AbstractBaseUser` + `PermissionsMixin` **plus** a concrete `username`,
`first_name`, `last_name`, a non-unique `email`, and the privilege flags, already wired together.
If you're keeping username/password login, subclassing `AbstractUser` and adding fields is the
fast, safe path. The moment the *login field itself* changes — here, email, with a real unique
constraint — you're fighting `AbstractUser`'s existing `username` field (making it nullable,
removing its uniqueness, keeping `USERNAME_FIELD` in sync) rather than just not declaring it.
`AbstractBaseUser` gives you exactly two things — `set_password`/`check_password` and the
`is_authenticated`/`is_anonymous` properties — and nothing about *how* login works; you declare
that yourself.

> **In this repo:** `src/cryptovira/apps/accounts/models.py` — read the module docstring first,
> it's written as the answer to this exact question.

### A3. What's the one thing you must not forget when subclassing `AbstractBaseUser` directly, and why does Django's own documentation call it out?

A **manager**. `AbstractUser` ships `UserManager` for free because it already knows the login
field is `username`; `AbstractBaseUser` alone has no idea how to construct a user, so
`manage.py createsuperuser` and `User.objects.create_user(...)` both fail without one. It's the
single most common mistake in "roll your own user model" tutorials, and it fails in an unhelpful
way (an `AttributeError` reaching for `create_user`, or `createsuperuser` crashing) rather than
something that points at the real cause.

> **In this repo:** `src/cryptovira/apps/accounts/managers.py`, `use_in_migrations = True` in
> particular — that flag makes migrations that create rows use *this* manager rather than
> Django's bare default, which matters because the bare default would skip password hashing.

### A4. Why does this model expose `uuid` instead of the numeric primary key anywhere externally?

A sequential integer PK in a URL or API response leaks **how many users exist and in what order
they signed up**, and invites enumeration — `/users/1/`, `/users/2/`, walking the whole table. A
separate `UUIDField` (random, not derivable from the PK) is the public handle; the integer `id`
stays internal, because it's still the fastest thing to index and join on. Losing sequential
insert order on the visible identifier is a feature here, not a cost.

> **In this repo:** `User.uuid`; `UserSerializer` exposes `uuid` and never `id`; JWT's
> `USER_ID_FIELD`/`USER_ID_CLAIM` (settings.py `SIMPLE_JWT`) are set to `uuid`/`sub` so the
> token's subject claim is the UUID too, not the row id.

**Drill:** read `docs/adr/0005-custom-user-model.md`'s list of fields the old model had that this
one doesn't (Telegram linkage, referrals, credit wallet, trading preferences). For each, name
which future roadmap step should own it, and why putting it there instead of on `User` keeps that
step's migrations from touching identity at all.

---

## B. Passwords

### B1. What's actually wrong with `user.password = raw_password; user.save()`?

It stores the password **in plaintext**. `set_password()` is not a formatting convenience — it
runs the raw string through Django's configured `PASSWORD_HASHERS` (Argon2/PBKDF2/etc.) and
stores only the hash, algorithm, and salt. There is no code path that should ever assign directly
to `.password`.

> **In this repo:** `UserManager._create_user()` is the one place that calls `set_password()`;
> the comment there is deliberately blunt about never bypassing it.

### B2. Where should password strength rules live, and why reuse `validate_password()` instead of writing your own checks?

One policy, one place: `AUTH_PASSWORD_VALIDATORS` in settings.py is what Django's own admin and
`createsuperuser` already enforce. A hand-rolled "must be 8 characters" check in a serializer is a
second policy that will drift from the first the moment someone edits one but not the other.
`django.contrib.auth.password_validation.validate_password()` runs the configured validators and
raises Django's `ValidationError` — which a DRF serializer must **catch and re-raise as its own**
`ValidationError`, or the response is an unhandled 500 instead of a clean 400 (the two exception
types are not interchangeable; DRF's exception handler only understands its own).

> **In this repo:** `RegisterSerializer.validate_password()` — including the deliberate build of
> a throwaway unsaved `User` instance so the *similarity-to-attributes* validator has something
> to compare against, before a real row exists.

### B3. Why does the registration serializer check email uniqueness itself when the database already enforces it?

Belt-and-suspenders, for different failure shapes. The DB constraint is what actually prevents a
duplicate under **concurrent** requests — two inserts racing each other. The serializer's
`email__iexact` check exists so a normal, non-racing duplicate signup gets a clean 400 with a
field-specific message instead of the 500 an uncaught `IntegrityError` would produce. The
serializer check alone has the exact same race the old system had; it is not a substitute for the
constraint, only a nicer error message on the common path.

> **In this repo:** `tests/apps/accounts/test_models.py::test_email_uniqueness_is_a_real_database_constraint`
> proves the DB-level guarantee directly, bypassing the serializer entirely.

**Drill:** `tests/apps/accounts/test_models.py::test_email_uniqueness_is_case_sensitive_at_the_db_level`
documents a real, currently-accepted gap: `Rider@x.com` and `rider@x.com` pass the DB constraint
as two different rows. Explain why the serializer's `iexact` check closes this for registration
specifically, but not for any other code path that creates a `User` directly (a management
command, a future admin action, a data migration).

---

## C. JWT

### C1. Access token vs refresh token — what is each one actually for?

The **access token** is what gets sent on every authenticated request; it's verified by
**signature alone** — no database lookup — which is the entire point of a JWT (stateless,
horizontally scalable auth with no shared session store). The **refresh token** exists purely to
mint new access tokens once the short-lived one expires, and *that* lookup can hit a database
(the blacklist table), because refresh happens rarely enough that the cost is fine.

### C2. Someone hits "logout." What actually gets revoked, and what doesn't?

The **refresh token** gets blacklisted — a row is written, and any future refresh attempt with
that token is rejected. The **access token already issued and sitting in the client's memory
keeps working**, for every request, until it naturally expires. There is no server-side way to
invalidate an already-issued, signature-valid JWT early without turning it into a stateful token
(a lookup on every single request, which defeats the reason to use JWT at all). This is *the*
JWT trade-off to be able to state precisely in an interview — not "JWTs are hard to revoke" as a
vague line, but this specific mechanism.

> **In this repo:** `LogoutSerializer`'s docstring states this explicitly, and
> `test_logout_does_not_revoke_the_access_token_itself` proves it: the same access token used to
> authenticate the logout call still authenticates a request *after* logout succeeds.

### C3. Given C2, what actually bounds the damage of a stolen access token?

`ACCESS_TOKEN_LIFETIME`. Short-lived access tokens (15 minutes here) don't prevent misuse, they
**bound its window** — a stolen token is a problem for at most that long, not indefinitely. This
is why the access/refresh split exists at all: a long-lived credential (the refresh token) sits
somewhere revocable, while the thing sent on every request expires fast enough that revocation
mostly doesn't need to happen for it.

### C4. What does `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION` buy you, concretely?

Without rotation, one refresh token is valid for its whole lifetime (7 days here) — steal it once,
use it repeatedly. With rotation, **every** refresh call both issues a new refresh token *and*
blacklists the one just spent, so a refresh token is single-use. If an attacker and the real user
both hold a copy of the same refresh token, whoever uses it first "wins" and the other's copy
stops working on their next attempt — not a perfect detection mechanism, but it turns a stolen
long-lived credential into, at most, a small handful of extra requests.

> **In this repo:** `test_a_rotated_refresh_token_cannot_be_reused` — refresh once, then replay
> the *original* refresh token and confirm it's now rejected.

### C5. Why does the login endpoint use `email`, not `username`, and how does simplejwt know that?

Because `USERNAME_FIELD = "email"` on the `User` model, and simplejwt's `TokenObtainPairView`
builds its serializer's fields **from the user model's `USERNAME_FIELD`** at class-definition
time rather than hardcoding `username`. This is the same mechanism the admin login form and
`ModelBackend` use — nothing in the Django/DRF/simplejwt stack assumes the login field is called
`username`; they all ask the model.

**Drill:** `SIMPLE_JWT["USER_ID_FIELD"] = "uuid"` and `"USER_ID_CLAIM" = "sub"` in settings.py.
Decode a real access token at <https://jwt.io> (or `python -c "import jwt; print(jwt.decode(t,
options={'verify_signature': False}))"`) from a login response and find the `sub` claim. Explain
why putting the row's numeric `id` in that claim instead would undo the reasoning in A4.

---

## D. DRF idioms worth recognizing on sight

### D1. `permission_classes = [IsAuthenticated]` sits right on the class body. Isn't a mutable list as a class attribute a bug magnet?

In general, yes — it's why `ruff`'s `RUF012` flags it, and why it's a real problem for something
like a dataclass default. For DRF (and Django more broadly — `MIDDLEWARE`, `INSTALLED_APPS`,
serializer `Meta.fields`), this is the framework's **configuration idiom**: the list is read by
the framework, never mutated in place by instances. Annotating every one with `ClassVar` to
satisfy a linter that's protecting against a mutation that structurally cannot happen (nothing in
DRF ever does `self.permission_classes.append(...)`) trades a false sense of safety for noise
across every view in the project.

> **In this repo:** `pyproject.toml`'s `[tool.ruff.lint] ignore` list documents this decision
> with the reasoning inline — a rule ignored on purpose, not a rule nobody noticed.

### D2. Why does `MeView.get_object()` exist, when `RetrieveUpdateAPIView` already knows how to look up an object from the URL?

Because the default lookup is **pk-from-URL** — `/users/<id>/` — and there deliberately is no
such endpoint here. `me/` carries no id at all; overriding `get_object()` to always return
`self.request.user` means the URL *cannot* address anyone else's profile, full stop. This is a
case where the access control is structural (the URL has no parameter to attack) rather than a
permission check that could be gotten wrong.

### D3. `LogoutView` is `GenericAPIView[Any]`, but `RegisterView` is `CreateAPIView[User]`. What does the type parameter mean, and why the difference?

It's the model/instance type the generic view operates on — what `get_queryset()`/`get_object()`
return. `RegisterView` genuinely creates and returns a `User`. `LogoutView` never looks up a model
instance at all (no `get_object`, no `get_queryset` — it validates a token string and calls
`.blacklist()`), so parameterizing it with `User` would be describing a capability it doesn't
have; `Any` says so honestly instead of picking a type that happens to satisfy mypy.

### D4. `validate_password(self, value)` vs `validate(self, attrs)` — when do you need the second one instead of the first?

A `validate_<field>` method sees one field in isolation and runs during `to_internal_value` for
that field alone. `validate(self, attrs)` runs **after** every field has individually validated,
with the full dict — it's for rules that compare fields to each other (password vs
password-confirmation, start-date vs end-date). `RegisterSerializer` doesn't need it because
there's no cross-field rule here, only a rule that needs *other already-submitted* fields as
context — which is why it reads `self.initial_data` rather than waiting for `validate()`.

**Drill:** `RegisterSerializer.validate_password()` reads specific keys off `self.initial_data`
(`email`, `first_name`, `last_name`) rather than passing the whole dict to `User(**kwargs)`.
Explain what a client sending an unexpected extra field in the JSON body would do to the wholesale
version, and why `initial_data` — the *raw, unvalidated* request payload — is the wrong thing to
trust broadly even though it's convenient here for three known keys.

---

## E. Throttling — and a real bug this build hit

### E1. What does DRF's throttling actually require to function, and what happens if it's silently missing?

A working **cache backend** — throttle counters live there, keyed by scope + client identity (IP
for anonymous, user id once authenticated). Without a configured cache, `AnonRateThrottle` and
friends don't error; they just never trip, because there's nowhere to count requests. This is a
"silent no-op," the worst kind of missing control — nothing in the logs says throttling isn't
working.

> **In this repo:** `CACHES["default"]` is Redis (settings.py) specifically so this isn't
> sqlite's per-process `LocMemCache`, which wouldn't share counts across multiple worker
> processes and would make the rate limit trivially bypassable by which process handled a
> request.

### E2. Why do `register/` and `token/` get their own throttle *scopes* instead of relying on the global `anon` rate?

Because they're the two endpoints a credential-stuffing or account-enumeration script actually
targets. A single global "60 requests/minute across the whole API" budget lets an attacker spend
nearly all of it on password guesses while legitimate anonymous browsing (viewing public
strategies, docs) still needs its own headroom — one shared bucket forces a bad trade between
"generous enough for browsing" and "tight enough to matter for auth."

> **In this repo:** `api/throttles.py`'s `LoginRateThrottle`/`RegistrationRateThrottle`, scoped
> rates in settings.py's `DEFAULT_THROTTLE_RATES`.

### E3. A test overrides `settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` at runtime and the throttle still doesn't trip at the new, lower rate. Why?

This is a real DRF gotcha this build hit directly, not a hypothetical. `SimpleRateThrottle`
(DRF's `throttling.py`) does:

```python
class SimpleRateThrottle(BaseThrottle):
    THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
```

That line runs **once**, when the module is first imported, binding `THROTTLE_RATES` to whatever
plain dict `api_settings.DEFAULT_THROTTLE_RATES` returned *at that moment*. `api_settings` itself
does refresh when Django fires its `setting_changed` signal (that's how `override_settings`
generally works with DRF) — but `SimpleRateThrottle.THROTTLE_RATES` is a separate, already-bound
class attribute that nothing re-reads afterward. Overriding the setting later never reaches it.

The fix is to mutate the throttle class's own dict directly — `monkeypatch.setitem(
LoginRateThrottle.THROTTLE_RATES, "login", "2/min")` — rather than trying to override the Django
setting and expecting the framework to notice.

> **In this repo:** `tests/apps/accounts/api/test_throttling.py` — the comment there is the
> post-mortem of exactly this failure, written while it was still fresh.

**Drill:** find the other place in DRF or Django you'd expect the same "bound once at import,
never re-read" pattern to bite — hint: anything assigned as a class attribute from a settings
value, at class-body scope, rather than looked up inside a method. `REST_FRAMEWORK` itself is
safe (accessed via `api_settings.X`, a descriptor that re-reads); the risk is code that copies a
settings value into a plain attribute once and keeps it.

---

## F. Testing gotchas specific to this module

### F1. Why do the accounts tests need `@pytest.mark.integration` when `test_config.py`'s tests don't?

Any test that touches the ORM at all — even a single `User.objects.create_user(...)` — needs
`@pytest.mark.django_db`, and pytest-django's database fixture needs a **real, reachable
Postgres** to create its test database against. `test_config.py` constructs `Settings` objects
directly with no database involved; `test_health.py`'s fast tests mock the dependency probes so
the real functions never run. The `integration` marker exists so `pytest -m "not integration"`
keeps its documented promise (README, CLAUDE.md) of needing zero external services — which means,
by this project's own convention, *any* test requiring `django_db` gets the marker, not just
tests whose stated purpose is checking connectivity.

### F2. Why does the duplicate-email model test need `transaction.atomic()` around the second `create_user()` call?

```python
with pytest.raises(IntegrityError), transaction.atomic():
    User.objects.create_user(email="rider@example.com", password="pw")
```

pytest-django wraps each `@pytest.mark.django_db` test in an outer transaction (rolled back after
the test, so tests don't leak data into each other). Postgres **aborts the entire transaction**
the moment any statement inside it raises — including an expected `IntegrityError` from a unique
violation — and every subsequent query in that same transaction then fails with `current
transaction is aborted, commands ignored until end of transaction block`, even totally unrelated
ones. Nesting the expected-to-fail statement in its own `atomic()` block creates a savepoint;
only that inner block rolls back on failure, leaving the outer test transaction (and any
assertions after it) usable.

**Drill:** delete the `transaction.atomic()` from
`test_email_uniqueness_is_a_real_database_constraint`, leaving only `pytest.raises(IntegrityError)`,
then add one more assertion after the `with` block (e.g. `assert User.objects.count() == 1`). Run
it and read the actual Postgres error. This is one of the more common "works in SQLite, breaks in
Postgres" surprises, and SQLite doesn't enforce this transaction-abort behaviour the same way —
another reason this project's tests run against real Postgres rather than a faster substitute.

---

## G. Questions you should be able to ask back

1. What's the actual blast radius if this project's refresh-token blacklist table is compromised
   or its rows are deleted — can old, already-blacklisted tokens come back to life?
2. If a user is deleted, what happens to their outstanding/blacklisted token rows — cascade,
   or orphaned forever?
3. What's the plan for a second identity provider (Telegram login, Google OAuth) — does account
   merging (the old system's `merge_with()`) get built then, and where does it live?
4. Access tokens are 15 minutes; is that short enough given there's no per-request revocation
   check, or does it need to be shorter once real money-moving endpoints exist?

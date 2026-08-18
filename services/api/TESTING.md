# Testing — Authentication Module

Test suite for the JWT authentication system (`/users`, `/auth/login`, `/auth/me`, `/profiles/me`) built on top of TinyDB. Tests also cover the now-protected `/suppliers` routes, since protecting them was part of the same authentication project.

## How to run

```bash
# Run the full suite
uv run pytest

# Run with verbose output (see every test name)
uv run pytest -v

# Run with coverage report
uv run pytest --cov=. --cov-report=term-missing
```

Tests never touch the development database. `tests/conftest.py` sets `SUPPLIER_DB_FILE=test_db.json` before any app module is imported, so all TinyDB tables (`users`, `profiles`, `suppliers`) are redirected to an isolated test file. Each test module truncates its relevant tables in `setup_function()`, so tests are independent and repeatable.

## Test plan

| Module | Endpoint | Tier | Case | Assert |
|---|---|---|---|---|
| `test_register.py` | `POST /users` | Happy | Valid email + password | User created with `role: user`; linked `Profile` created |
| | | Edge | Duplicate email | Rejected with 400; only one user persisted |
| | | Failure | Password under 8 chars | 422; no user written |
| | | Failure | Missing email | 422; no user written |
| `test_login.py` | `POST /auth/login` | Happy | Correct credentials | 200; JWT decodes to correct user id |
| | | Edge | User exists but `is_active=False` | 401 (bug found and fixed — see below) |
| | | Failure | Wrong password | 401; no `access_token` in response |
| `test_token.py` | `GET /auth/me` | Happy | Valid token | 200; returns email + linked profile |
| | | Edge | Freshly issued token (near expiry window) | 200 |
| | | Failure | Expired token | 401; no user data returned |
| | | Failure | Malformed token | 401 |
| | | Failure | Missing token | 401 |
| `test_profiles.py` | `PUT /profiles/me` | Happy | Owner updates `name` | Profile field changes; linked `User` email unchanged |
| | | Edge | Empty string `phone` | Accepted (200) |
| | | Failure | No token | 401 |
| `test_users_management.py` | `GET /users` | Happy | Authenticated caller | 200; returns all users |
| | | Failure | No token | 401 |
| | `GET /users/{id}` | Failure | Nonexistent id | 404 |
| | `PUT /users/{id}` | Happy | Owner updates own email | 200 |
| | | Edge | Non-owner, non-admin updates another user | 403 |
| | | Edge | Non-admin attempts to change own `role` | 403 |
| | | Edge | Admin changes another user's `role` | 200 |
| | `DELETE /users/{id}` | Happy | Owner deletes own account | 204; user and linked profile removed |
| | | Failure | Admin deletes nonexistent id | 404 |
| `test_suppliers.py` | `/suppliers/*` | (all previous cases) | Authenticated caller (updated to attach a JWT, since these routes were protected as part of this project) | All previous assertions still hold |

## Coverage snapshot

```
Name                             Stmts   Miss  Cover   Missing
--------------------------------------------------------------
app\__init__.py                      0      0   100%
app\core\__init__.py                 0      0   100%
app\core\deps.py                    19      2    89%   27, 33
app\core\security.py                24      1    96%   22
database.py                         11      0   100%
main.py                            101     13    87%   73, 89, 98, 108-111, 118, 142, 159-162
models.py                           55      0   100%
repository.py                       44      4    91%   60-65
seed.py                             13      1    92%   69
users_repository.py                 57      4    93%   65, 68, 88, 95
--------------------------------------------------------------
TOTAL                              609     25    96%

35 passed in 15.62s
```

Authentication-related modules (`app/core/deps.py`, `app/core/security.py`, `users_repository.py`, and the auth/user/profile routes in `main.py`) all sit at **87–96% coverage**, well above the 70% requirement. The remaining uncovered lines are low-value edge branches (e.g. an update call with an empty payload, or a profile lookup for a user_id that can never actually be missing given `create_user` always creates a linked profile) that aren't reachable through the public API in any meaningful way.

## AI-assisted discovery

While writing `test_login_inactive_user_is_rejected` against the reference test plan (which specifies that a login attempt for a user with `is_active: False` should be rejected), the test initially failed. Reviewing `main.py` confirmed that the `/auth/login` route only validated the email/password pair and never checked the user's `is_active` flag — meaning a deactivated account could still authenticate and receive a valid JWT.

**Fix applied** in `main.py`:

```python
user = users_repository.find_user_by_email(form_data.username)
if user is None or not verify_password(form_data.password, user["hashed_password"]):
    raise HTTPException(status_code=401, detail="Incorrect email or password")
if not user["is_active"]:
    raise HTTPException(status_code=401, detail="Incorrect email or password")
```

This is a real example of writing the test *before* confirming the implementation matched the spec — the failing test caught a genuine authorization gap rather than a test-authoring mistake.
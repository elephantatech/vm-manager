# CLAUDE.md - VMware Web Manager

## Project Overview
VMware Web Manager is a lightweight, secure orchestration layer for VMware Workstation/Player on Windows 11. It provides a Web UI to manage VM power states and dynamically expose VM services to the local network (LAN) using a TCP proxy and automated Windows Firewall management. It also supports exposing local host services (e.g., Podman, Ollama) and persistent port blocking.

## Tech Stack
- **Language:** Python 3.11+ (managed via `uv`)
- **Web Framework:** FastAPI (async)
- **Database:** SQLite via SQLAlchemy 2.0+ (`DeclarativeBase`) (file: `vm_manager.db`)
- **Auth:** JWT (python-jose, HS256) + BCrypt (passlib), with token revocation via password versioning
- **Frontend:** Single-page vanilla JS/HTML/CSS (`static/index.html`)
- **VM Control:** VMware `vmrun.exe` via `asyncio.create_subprocess_exec`
- **Proxy:** Async TCP forwarder with Windows Firewall (`netsh advfirewall`)
- **Logging:** Structured JSON via `python-json-logger` to `vm_manager.log`
- **Linter/Formatter:** Ruff
- **Task Runner:** Taskipy (`uv run task <name>`)

## Project Structure
```
vm-manager/
├── main.py              # FastAPI app, all API endpoints, auth, lifespan, rate limiting
├── vm_control.py        # VMControl class - vmrun.exe wrapper, VM discovery
├── proxy.py             # PortRegistry, TCPProxy, ProxyManager classes
├── database.py          # SQLAlchemy ORM models + schema migrations
├── security.py          # BCrypt hashing, JWT token create/verify, secret key management
├── logger_config.py     # JSON logger setup
├── diagnose_gui.py      # Playwright-based diagnostic tool
├── static/
│   └── index.html       # SPA frontend (embedded CSS + JS, XSS-safe)
├── tests/
│   ├── conftest.py      # Shared test fixtures (engine, session, mocks)
│   ├── test_main.py     # API endpoint tests (TestClient + in-memory SQLite)
│   ├── test_middleware.py # LAN middleware accept/reject tests
│   ├── test_security.py # BCrypt, JWT, and secret key tests
│   ├── test_vm_control.py # vmrun wrapper + fallback + scan tests
│   ├── test_proxy.py    # Port registry and proxy manager tests
│   ├── test_models.py   # ORM model instantiation tests
│   └── test_e2e.py      # Playwright end-to-end browser tests
├── install.ps1          # Windows Task Scheduler setup
├── upgrade.ps1          # Service upgrade script
├── pyproject.toml       # Dependencies, scripts, and tool config
├── spec.md              # Technical specification
└── README.md            # User documentation
```

## Key Commands
```bash
# Install dependencies
uv sync

# Run the server (development)
uv run uvicorn main:app --host 0.0.0.0 --port 8000

# Task runner shortcuts (via taskipy)
uv run task test          # Run unit tests (excludes e2e)
uv run task test-all      # Run all tests including e2e
uv run task lint          # Ruff linting
uv run task format        # Ruff formatting
uv run task check         # Lint + format check + tests in one go

# Manual commands (without taskipy)

# Run all unit tests (excludes e2e)
uv run pytest tests/ -v --ignore=tests/test_e2e.py

# Run all tests including Playwright e2e
uv run pytest tests/ -v

# Run a specific test file
uv run pytest tests/test_main.py -v

# Run a single test by name
uv run pytest tests/test_main.py::test_login_success -v

# Lint (check for errors without modifying files)
uv run ruff check .

# Lint and auto-fix fixable errors
uv run ruff check . --fix

# Format (rewrites files in-place)
uv run ruff format .

# Format check only (reports unformatted files, does not modify)
uv run ruff format --check .

# Install Playwright browsers (required once before e2e tests)
uv run playwright install chromium
```

## Architecture

### Startup Sequence (main.py lifespan)
1. `init_db()` - Create all SQLAlchemy tables + run schema migrations
2. `init_secret_key()` - Resolve JWT secret (env var > DB `settings` table > generate new)
3. Resolve `vmrun_path` from DB settings or default
4. Initialize `vm_control` and `proxy_manager` module-level globals
5. `bootstrap_admin()` - Create default admin user if no users exist (with `must_change_password=True`)
6. `cleanup_stale_firewall_rules()` - Remove leftover `VMProxy_*` firewall rules
7. Restore all enabled proxies from DB

### API Endpoints
| Endpoint | Method | Permission | Body | Description |
|---|---|---|---|---|
| `/token` | POST | None | OAuth2 form | Login, returns JWT + permissions + `must_change_password` flag |
| `/api/vms` | GET | `vm:read` | - | List VMs with status |
| `/api/vms/scan` | POST | `vm:scan` | - | Discover unregistered VMs |
| `/api/vms` | POST | `vm:add` | `VMCreate` JSON | Register a VM |
| `/api/vms/{id}` | DELETE | `vm:delete` | - | Unregister VM + stop its proxies |
| `/api/vms/{id}/{action}` | POST | `vm:{action}` | - | Start/stop/restart VM (validated actions only) |
| `/api/proxies` | GET | `vm:read` | - | List all proxy rules |
| `/api/proxies` | POST | `proxy:create` | `ProxyCreate` JSON | Create proxy |
| `/api/proxies/{id}/toggle` | PUT | `proxy:toggle` | - | Enable/disable proxy |
| `/api/proxies/{id}` | DELETE | `proxy:delete` | - | Delete proxy |
| `/api/registry` | GET | `vm:read` | - | View active proxies + blocked ports |
| `/api/registry/scan` | POST | `proxy:create` | - | Scan host ports, auto-block |
| `/api/registry/block` | POST | `proxy:create` | `PortBlock` JSON | Manually block a port |
| `/api/registry/block/{port}` | DELETE | `proxy:delete` | - | Unblock a port |
| `/api/user/change-password` | POST | (auth only) | `PasswordChange` JSON | Change own password, resets `must_change_password`, increments `password_version` |
| `/api/users` | GET | `user:manage` | - | List all users |
| `/api/users` | POST | `user:manage` | `UserCreate` JSON | Create user |
| `/api/users/{id}` | DELETE | `user:manage` | - | Delete user |

### Pydantic Request Models (defined in main.py)
- `VMCreate` - `name: str`, `path: str`
- `ProxyCreate` - `host_port: int`, `target_port: int`, `vm_id: Optional[str]`, `target_host: Optional[str]`
- `PortBlock` - `port: int`, `description: str`
- `UserCreate` - `username: str`, `password: str`, `permissions: str`
- `PasswordChange` - `old_password: str`, `new_password: str`

### RBAC Roles (defined in main.py GROUPS)
- **admin** → `*` (all permissions)
- **vm_manager** → vm:read, vm:start, vm:stop, vm:restart, vm:add, vm:scan, proxy:toggle, proxy:create, proxy:delete
- **vm_operator** → vm:read, vm:start, vm:stop, vm:restart, proxy:toggle
- **viewer** → vm:read

### Database Tables
- `users` - id (int PK), username (unique), hashed_password, permissions (CSV string), must_change_password (bool), password_version (int)
- `vms` - id (UUID string PK), name, path; has-many proxies (cascade delete)
- `proxies` - id (UUID string PK), vm_id (FK nullable), target_host, host_port, vm_port, enabled
- `settings` - key (string PK), value (stores `vmrun_path`, `secret_key`, etc.)
- `reserved_ports` - port (int PK), description

### Schema Migrations
`database.py` includes a `_run_migrations(engine)` function called from `init_db()`. It uses `ALTER TABLE ... ADD COLUMN` wrapped in try/except for SQLite, allowing new columns to be added to existing databases without Alembic.

### VM Discovery (vm_control.py scan_for_vms)
Three-layer approach:
1. **Live** - `vmrun list` for currently running VMs
2. **Inventory** - Parse `C:\Users\*\AppData\Roaming\VMware\inventory.vmls`
3. **Filesystem** - Walk `Documents\Virtual Machines` across user profiles

### Proxy System (proxy.py)
- `PortRegistry` - Triple-check availability: in-memory set, DB reserved_ports, OS socket bind
- `TCPProxy` - Async TCP forwarder + Windows Firewall rule (`VMProxy_{port}`)
- `ProxyManager` - Orchestrates proxy lifecycle, port scanning via PowerShell

### Security
- **Secret key management:** Env var `VM_MANAGER_SECRET_KEY` > DB `settings.secret_key` > auto-generated 64-byte hex key
- **LAN-only middleware:** Rejects non-private IPs (127.0.0.1, 192.168.x, 10.x, 172.16-31.x) with safe parsing of 172.x range
- **JWT tokens:** Expire in 30 minutes, include `pw_ver` claim for revocation on password change
- **Token revocation:** `password_version` column on `User`; tokens with mismatched `pw_ver` are rejected
- **Rate limiting:** 5 login attempts per IP per 60-second window (HTTP 429 on exceed)
- **Forced password change:** Bootstrap admin has `must_change_password=True`; all endpoints (except `/token` and `/api/user/change-password`) return 403 until password is changed
- **VM action validation:** Only `start`, `stop`, `restart` accepted; invalid actions return 400
- **XSS protection:** Frontend `escapeHtml()` applied to all user-controlled data
- **Client-side permissions:** JWT decoded on client for permission checks; `localStorage` `_perms` set from server response
- **HTTPS support:** Optional via `SSL_CERTFILE` and `SSL_KEYFILE` env vars
- Firewall rules restricted to `remoteip=localsubnet`

## Testing
- Tests use in-memory SQLite with `StaticPool` and dependency injection overrides
- Shared test infrastructure in `tests/conftest.py` (engine, session factory, mocks)
- External calls (vmrun, subprocess, sockets) are mocked
- `test_main.py` overrides `get_db` and `get_current_user` dependencies
- `test_middleware.py` tests LAN middleware accept/reject with various IP ranges
- `test_vm_control.py` tests stop/restart soft→hard fallback and scan discovery
- `test_e2e.py` uses Playwright for browser-based end-to-end tests (requires `uv run playwright install chromium`)
- Run with: `uv run task test`

## Environment Variables
- `VM_MANAGER_SECRET_KEY` - JWT signing key (if unset, auto-generated and persisted to DB)
- `SSL_CERTFILE` - Path to SSL certificate file (optional, for HTTPS)
- `SSL_KEYFILE` - Path to SSL private key file (optional, for HTTPS)
- `LOG_LEVEL` - Logging level (default: WARNING)
- `TESTING` - Set to "1" in test environment

## Important Notes
- The app runs on port 8000 by default
- Requires administrator privileges for firewall rule management
- All initialization (DB, secret key, vmrun path, vm_control, proxy_manager, bootstrap admin) happens inside the `lifespan()` function — no module-level DB sessions
- POST endpoints use JSON request bodies (Pydantic models), not query parameters
- The frontend decodes the JWT client-side for permission checks
- Orphaned proxy cleanup: if DB insert fails after starting a proxy, the running proxy is stopped automatically

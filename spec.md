# VMware Web Manager - Technical Specification

## 1. Overview
VMware Web Manager is a lightweight, secure orchestration layer for VMware Workstation/Player on Windows 11. It provides a Web UI to manage VM power states and dynamically expose VM services to the local network (LAN) using a TCP proxy and automated Windows Firewall management. It also supports exposing local host services (e.g., Podman, Ollama) and persistent port blocking.

## 2. System Architecture
- **Language:** Python 3.11+ (Managed via `uv`)
- **Web Framework:** FastAPI (Asynchronous)
- **Database:** SQLite via SQLAlchemy 2.0+ (`DeclarativeBase`) with inline schema migrations.
- **VM Orchestration:** VMware `vmrun.exe` utility.
- **Proxy Engine:** Asynchronous Python TCP forwarder.
- **Security:** JWT-based Authentication + Role-Based Access Control (RBAC) + rate limiting + token revocation.
- **Frontend:** Single Page Application (SPA) using Vanilla JavaScript, HTML5, and CSS3 with XSS protection.
- **Hosting:** Native Windows Task Scheduler (running in **User Context**).

## 3. Core Components

### 3.1 VM Control Module (`vm_control.py`)
Interfaces with VMware via `asyncio.create_subprocess_exec`.
- **Robust Power Control:** Implements "soft" operations (Shutdown/Restart) with an automatic fallback to "hard" (Power Off/Reset) if VMware Tools is missing.
- **Multi-Layer Discovery:**
    1. **Live:** Scans active processes via `vmrun list`.
    2. **Inventory:** Parses official VMware `inventory.vmls` files across all user profiles.
    3. **Filesystem:** Fallback recursive scan of common "Virtual Machines" directories.
- **Action Validation:** Only `start`, `stop`, and `restart` actions are accepted; invalid actions are rejected with HTTP 400.

### 3.2 TCP Proxy & Port Registry (`proxy.py`)
- **Unified Proxying:** Supports both dynamic VM-linked proxies and static "Generic Host" proxies (targeting `127.0.0.1` or any IP).
- **Persistent Port Registry:**
    - Prevents host port collisions by tracking active proxies.
    - Supports **Manual and Automatic Port Blocking** via the `reserved_ports` table.
    - **Port Scanning:** Discovers occupied host ports by identifying the owning Process Name and any existing Inbound Firewall Rules.
    - **Auto-Reserve:** Discovered occupied ports are automatically inserted into the registry as "Blocked" with descriptive reasoning (e.g., `"Auto-blocked: Process: nginx | Firewall Rule: Custom Rule"`).
    - Triple-check validation (Memory + Database + OS bind test) before allocation.
- **Firewall Integration:** Executes `netsh advfirewall` commands restricted to `remoteip=localsubnet`.
- **Orphan Protection:** If a proxy's DB record fails to persist, the running proxy is automatically stopped to prevent orphaned resources.

### 3.3 Security & RBAC (`security.py`, `database.py`, `main.py`)
- **Secret Key Management:** JWT signing key resolved from environment variable (`VM_MANAGER_SECRET_KEY`), then from DB `settings` table, then auto-generated as a 64-byte hex token and persisted.
- **Authentication:** Password hashing using `Passlib` (BCrypt) and JWT session management with 30-minute expiry.
- **Token Revocation:** JWT tokens include a `pw_ver` claim tied to the user's `password_version` column. Tokens are rejected if the version mismatches (e.g., after password change).
- **Rate Limiting:** Login endpoint (`/token`) enforces a maximum of 5 attempts per IP address per 60-second window, returning HTTP 429 when exceeded.
- **Forced Password Change:** The bootstrap admin account is created with `must_change_password=True`. All API endpoints (except `/token` and `/api/user/change-password`) return HTTP 403 until the password is changed.
- **RBAC System:** Granular permissions and predefined roles (`admin`, `vm_manager`, `vm_operator`, `viewer`).
- **LAN Restriction:** Middleware validates that incoming requests originate from private IP ranges, with safe parsing of the 172.16-31.x range (malformed IPs are rejected).
- **XSS Protection:** Frontend escapes all user-controlled data before rendering via `escapeHtml()`.
- **Client-Side Permissions:** JWT is decoded client-side to extract permissions; `localStorage` permissions are set from the server login response.
- **HTTPS Support:** Optional TLS via `SSL_CERTFILE` and `SSL_KEYFILE` environment variables. A warning is logged on startup if running without SSL.

### 3.4 Database & Migrations (`database.py`)
- **ORM:** Uses SQLAlchemy 2.0+ `DeclarativeBase` pattern.
- **Tables:** `users`, `vms`, `proxies`, `settings`, `reserved_ports`.
- **Schema Migrations:** `_run_migrations(engine)` adds new columns (`must_change_password`, `password_version`) to existing databases using `ALTER TABLE ... ADD COLUMN` wrapped in try/except, enabling upgrades without Alembic.

### 3.5 Logging (`logger_config.py`)
- **Format:** Structured JSON logging.
- **Level Control:** Default `WARNING`, configurable via `LOG_LEVEL` environment variable.

## 4. API Specification

| Endpoint | Method | Body | Description |
| :--- | :--- | :--- | :--- |
| `/token` | POST | OAuth2 form | Authenticate and receive JWT token + permissions + `must_change_password` flag. Rate limited. |
| `/api/vms` | GET | - | List managed VMs and current statuses. |
| `/api/vms/scan` | POST | - | Discovery scan across live, inventory, and filesystem. |
| `/api/vms` | POST | `VMCreate` JSON | Register a new VM. |
| `/api/vms/{id}` | DELETE | - | Unregister VM and stop its proxies. |
| `/api/vms/{id}/{action}` | POST | - | Start, Stop, or Restart with fallback logic. Validates action. |
| `/api/registry` | GET | - | View all active port mappings and blocked ports. |
| `/api/registry/scan` | POST | - | Scan host ports, auto-block occupied ports. |
| `/api/registry/block` | POST | `PortBlock` JSON | Manually block/reserve a host port. |
| `/api/registry/block/{port}`| DELETE | - | Unblock a host port. |
| `/api/proxies` | GET | - | List all proxy rules. |
| `/api/proxies` | POST | `ProxyCreate` JSON | Create a new TCP proxy (VM or Generic Host target). |
| `/api/proxies/{id}/toggle`| PUT | - | Enable/Disable a proxy rule. |
| `/api/proxies/{id}` | DELETE | - | Delete a proxy rule. |
| `/api/user/change-password`| POST | `PasswordChange` JSON | Change password, clear forced change flag, increment version, return new token. |
| `/api/users` | GET | - | List all users (admin only). |
| `/api/users` | POST | `UserCreate` JSON | Create a new user with specific permissions (admin only). |
| `/api/users/{id}` | DELETE | - | Delete a user (admin only). |

## 5. Startup Sequence
1. `init_db()` - Create tables + run schema migrations.
2. `init_secret_key()` - Resolve/generate JWT secret key.
3. Resolve `vmrun_path` from DB settings or use default.
4. Initialize `vm_control` (VMControl) and `proxy_manager` (ProxyManager).
5. `bootstrap_admin()` - Create default admin if no users exist (`must_change_password=True`).
6. `cleanup_stale_firewall_rules()` - Remove leftover `VMProxy_*` firewall rules.
7. Restore all enabled proxies from DB.

## 6. Deployment Model
- **Process Management:** Hosted as a "Highest Privilege" task in Windows Task Scheduler.
- **User Context:** Runs under the **currently logged-on user** to ensure session access.
- **Lifecycle:** Starts at system boot (`ONSTART`) with `-WindowStyle Hidden`.
- **HTTPS:** Enable by setting `SSL_CERTFILE` and `SSL_KEYFILE` environment variables.
- **Testing:** Validated by 46+ unit tests, LAN middleware tests, and Playwright end-to-end browser tests.

## 7. Testing & Code Quality

### Task Runner (via taskipy)
```bash
uv run task test          # Run unit tests (excludes e2e)
uv run task test-all      # Run all tests including Playwright e2e
uv run task lint          # Ruff linting
uv run task format        # Ruff formatting
uv run task check         # Lint + format check + tests in one go
```

### Manual Commands
```bash
# Run all unit tests (excludes e2e)
uv run pytest tests/ -v --ignore=tests/test_e2e.py

# Run all tests including e2e
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

# Run e2e tests only
uv run pytest tests/test_e2e.py -v
```

### Test Files
| File | Coverage |
| :--- | :--- |
| `test_main.py` | API endpoints, login, rate limiting, password change, user CRUD, VM actions, proxy CRUD |
| `test_middleware.py` | LAN middleware accept/reject for private, public, and malformed IPs |
| `test_security.py` | BCrypt hashing, JWT creation, password version in tokens, secret key resolution |
| `test_vm_control.py` | Start/stop/restart with soft→hard fallback, scan three-layer discovery |
| `test_proxy.py` | Port registry, proxy manager start/stop/duplicate, port scanning |
| `test_models.py` | ORM model instantiation including new columns |
| `test_e2e.py` | Playwright browser tests: login, forced password change, dashboard, navigation |

## 8. Environment Variables
| Variable | Required | Description |
| :--- | :--- | :--- |
| `VM_MANAGER_SECRET_KEY` | No | JWT signing key. If unset, auto-generated and persisted to DB. |
| `SSL_CERTFILE` | No | Path to SSL certificate file for HTTPS. |
| `SSL_KEYFILE` | No | Path to SSL private key file for HTTPS. |
| `LOG_LEVEL` | No | Logging level (default: `WARNING`). |
| `TESTING` | No | Set to `1` in test environment. |

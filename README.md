# VMware Web Manager

A robust Web UI and API for managing VMware Workstation/Player VMs on Windows 11. It allows you to control power states and expose VM ports to your local network (LAN) automatically. It also includes support for local services (Podman, Ollama) and persistent port blocking.

## Key Features
- **Remote Power Control:** Start, Stop, and Restart VMs with automatic "hard" fallbacks.
- **Smart Discovery Scan:** Multi-layered scan across all user profiles to find your VMs.
- **Auto Port Forwarding:** Expose VM services (SSH, Web, etc.) to your LAN with one click.
- **Host Services Expose:** Easily proxy local services (e.g., Podman, Ollama, local web apps) to your LAN.
- **Persistent Port Registry:** Manually block or reserve ports to prevent conflicts.
- **RBAC Security:** Multi-user support with granular permissions and roles (Admin, Operator, etc.).
- **SQLite Persistence:** All configurations, users, and proxies are stored in a persistent database.
- **Background Service:** Runs silently as a Windows Task in your user context.
- **Rate-Limited Login:** Protects against brute-force attacks (5 attempts per 60 seconds per IP).
- **Forced Password Change:** Bootstrap admin must change password before accessing any resource.
- **Token Revocation:** Password changes instantly invalidate all existing tokens.
- **Optional HTTPS:** TLS support via environment variables.

## Prerequisites
- **Windows 11** Host.
- **VMware Workstation/Player** installed.
- **[uv](https://github.com/astral-sh/uv)** installed.
- **Administrative Privileges** (required for firewall rule management).

## Installation & Setup

### 1. Install Dependencies
```bash
cd vm-manager/vm-manager
uv sync
```

### 2. Run the Server (Development)
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. Install as Background Service
Run the installer from an **Administrator PowerShell**:
```powershell
powershell.exe -ExecutionPolicy Bypass -File install.ps1
```

### 4. First Login
On the first start, the system creates a default account:
- **Username:** `admin`
- **Password:** `admin`

You will be required to change the password before accessing any other feature.

## Usage
1. Navigate to `http://<YOUR-HOST-IP>:8000`.
2. Log in with `admin` / `admin`.
3. **Change your password** (required on first login).
4. **Expose Host Services:** Use the "Host Services" section to proxy local apps (e.g., Target `127.0.0.1:11434` for Ollama).
5. **Block Ports:** Use the "Port Registry" section to reserve ports (e.g., reserve `3306` for a local SQL server).
6. **Scan for VMs:** Automatically find and add your existing virtual machines.

## Security
- **RBAC:** Access to every feature is controlled by permissions (`admin`, `vm_manager`, `vm_operator`, `viewer`).
- **LAN Middleware:** The server only accepts connections from private IP ranges (127.0.0.1, 192.168.x, 10.x, 172.16-31.x).
- **Firewall:** Proxy rules are created with `remoteip=localsubnet` restriction.
- **JWT Tokens:** 30-minute expiry with password-version-based revocation.
- **Rate Limiting:** Login endpoint enforces 5 attempts per IP per 60-second window.
- **HTTPS:** Set `SSL_CERTFILE` and `SSL_KEYFILE` environment variables to enable TLS.

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| `VM_MANAGER_SECRET_KEY` | Auto-generated | JWT signing key. If unset, a random key is generated and persisted to DB. |
| `SSL_CERTFILE` | *(none)* | Path to SSL certificate file for HTTPS. |
| `SSL_KEYFILE` | *(none)* | Path to SSL private key file for HTTPS. |
| `LOG_LEVEL` | `WARNING` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

## Development

### Task Runner Commands
```bash
uv run task test          # Run unit tests (excludes e2e)
uv run task test-all      # Run all tests including Playwright e2e
uv run task lint          # Run ruff linting
uv run task format        # Run ruff formatting
uv run task check         # Lint + format check + tests in one go
```

### Manual Commands (without taskipy)
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
```

### Playwright E2E Tests
```bash
# Install Playwright browsers (required once)
uv run playwright install chromium

# Run e2e tests via task runner
uv run task test-all

# Or run e2e tests manually
uv run pytest tests/test_e2e.py -v
```

### Upgrade
Run `./upgrade.ps1` to apply code changes to a running installation.

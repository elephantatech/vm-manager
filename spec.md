# VMware Web Manager - Technical Specification

## 1. Overview
VMware Web Manager is a lightweight, secure orchestration layer for VMware Workstation/Player on Windows 11. It provides a Web UI to manage VM power states and dynamically expose VM services to the local network (LAN) using a TCP proxy and automated Windows Firewall management. It also supports exposing local host services (e.g., Podman, Ollama) and persistent port blocking.

## 2. System Architecture
- **Language:** Python 3.11+ (Managed via `uv`)
- **Web Framework:** FastAPI (Asynchronous)
- **Database:** SQLite via SQLAlchemy (Persistent Storage)
- **VM Orchestration:** VMware `vmrun.exe` utility.
- **Proxy Engine:** Asynchronous Python TCP forwarder.
- **Security:** JWT-based Authentication + Role-Based Access Control (RBAC).
- **Frontend:** Single Page Application (SPA) using Vanilla JavaScript, HTML5, and CSS3.
- **Hosting:** Native Windows Task Scheduler (running in **User Context**).

## 3. Core Components

### 3.1 VM Control Module (`vm_control.py`)
Interfaces with VMware via `asyncio.create_subprocess_exec`.
- **Robust Power Control:** Implements "soft" operations (Shutdown/Restart) with an automatic fallback to "hard" (Power Off/Reset) if VMware Tools is missing.
- **Multi-Layer Discovery:** 
    1. **Live:** Scans active processes via `vmrun list`.
    2. **Inventory:** Parses official VMware `inventory.vmls` files across all user profiles.
    3. **Filesystem:** Fallback recursive scan of common "Virtual Machines" directories.

### 3.2 TCP Proxy & Port Registry (`proxy.py`)
- **Unified Proxying:** Supports both dynamic VM-linked proxies and static "Generic Host" proxies (targeting `127.0.0.1` or any IP).
- **Persistent Port Registry:** 
    - Prevents host port collisions by tracking active proxies.
    - Supports **Manual and Automatic Port Blocking** via the `reserved_ports` table.
    - **Port Scanning:** Discovers occupied host ports by identifying the owning Process Name and any existing Inbound Firewall Rules.
    - **Auto-Reserve:** Discovered occupied ports are automatically inserted into the registry as "Blocked" with descriptive reasoning (e.g., `"Auto-blocked: Process: nginx | Firewall Rule: Custom Rule"`).
    - Triple-check validation (Memory + Database + OS bind test) before allocation.
- **Firewall Integration:** Executes `netsh advfirewall` commands restricted to `remoteip=localsubnet`.

### 3.3 Security & RBAC (`database.py`, `main.py`)
- **Authentication:** Password hashing using `Passlib` (BCrypt) and JWT session management.
- **RBAC System:** Granular permissions and predefined roles (`admin`, `vm_manager`, `vm_operator`, `viewer`).
- **LAN Restriction:** Middleware validates that incoming requests originate from private IP ranges.

### 3.4 Logging (`logger_config.py`)
- **Format:** Structured JSON logging.
- **Level Control:** Default `WARNING`, configurable via `LOG_LEVEL` environment variable.

## 4. API Specification

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/token` | POST | Authenticate and receive JWT token + permissions. |
| `/api/vms` | GET | List managed VMs and current statuses. |
| `/api/vms/scan` | POST | Discovery scan across live, inventory, and filesystem. |
| `/api/vms/{id}/{action}` | POST | Start, Stop, or Restart with fallback logic. |
| `/api/registry` | GET | View all active port mappings and blocked ports. |
| `/api/registry/block` | POST | Manually block/reserve a host port. |
| `/api/registry/block/{port}`| DELETE | Unblock a host port. |
| `/api/proxies` | POST | Create a new TCP proxy (VM or Generic Host target). |
| `/api/proxies/{id}/toggle`| PUT | Enable/Disable a proxy rule. |
| `/api/user/change-password`| POST | Change the currently logged-in user's password. |
| `/api/users` | POST | Create a new user with specific permissions (Admin only). |

## 5. Deployment Model
- **Process Management:** Hosted as a "Highest Privilege" task in Windows Task Scheduler.
- **User Context:** Runs under the **currently logged-on user** to ensure session access.
- **Lifecycle:** Starts at system boot (`ONSTART`) with `-WindowStyle Hidden`.
- **Testing:** Validated by comprehensive unit tests and Playwright diagnostics.

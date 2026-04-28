# VMware Web Manager - Technical Specification

## 1. Overview
VMware Web Manager is a lightweight, secure orchestration layer for VMware Workstation/Player on Windows 11. It provides a Web UI to manage VM power states and dynamically expose VM services to the local network (LAN) using a TCP proxy and automated Windows Firewall management.

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
- **TCP Forwarder:** Asynchronous pipe between host ports and guest ports.
- **Port Registry:** Manages host port allocations to prevent collisions.
- **Firewall Integration:** Executes `netsh advfirewall` commands restricted to `remoteip=localsubnet`.

### 3.3 Security & RBAC (`database.py`, `main.py`)
- **Authentication:** Password hashing using `Passlib` (BCrypt).
- **RBAC System:** Granular permissions (e.g., `vm:start`, `proxy:create`) and predefined roles:
    - `admin`: Full access (`*`).
    - `vm_manager`: Manage VMs and Ports.
    - `vm_operator`: Power control and port toggling.
    - `viewer`: Read-only access.
- **Bootstrapping:** Automatically creates a default `admin` / `admin` account if no users exist.

### 3.4 Logging (`logger_config.py`)
- **Format:** Structured JSON logging.
- **Level Control:** Default `WARNING`, configurable via `LOG_LEVEL` env var.

## 4. API Specification

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/token` | POST | Authenticate and receive JWT token + permissions. |
| `/api/vms` | GET | List managed VMs and current statuses. |
| `/api/vms/scan` | POST | Discovery scan across live, inventory, and filesystem. |
| `/api/vms/{id}/{action}` | POST | Start, Stop, or Restart with fallback logic. |
| `/api/registry` | GET | View all host port mappings. |
| `/api/proxies` | POST | Create a new TCP proxy rule. |
| `/api/user/change-password`| POST | Change the currently logged-in user's password. |
| `/api/users` | POST | Create a new user with specific permissions (Admin only). |

## 5. Deployment Model
- **Process Management:** Hosted as a "Highest Privilege" task in Windows Task Scheduler.
- **User Context:** Runs under the **currently logged-on user** to ensure access to the hypervisor session.
- **Lifecycle:** Starts at system boot (`ONSTART`) with `-WindowStyle Hidden`.

# VMware Web Manager - Technical Specification

## 1. Overview
VMware Web Manager is a lightweight, secure orchestration layer for VMware Workstation/Player on Windows 11. it provides a Web UI to manage VM power states and dynamically expose VM services (like SSH, Web, or Databases) to the local network (LAN) using a TCP proxy and automated Windows Firewall management.

## 2. System Architecture
- **Language:** Python 3.11+ (Managed via `uv`)
- **Web Framework:** FastAPI (Asynchronous)
- **VM Orchestration:** VMware `vmrun.exe` utility.
- **Proxy Engine:** Asynchronous Python TCP forwarder.
- **Security:** JWT-based Authentication + Windows Defender Firewall automation.
- **Frontend:** Single Page Application (SPA) using Vanilla JavaScript, HTML5, and CSS3.
- **Storage:** File-based JSON storage (`config.json`).
- **Hosting:** Native Windows Task Scheduler (running as `SYSTEM`).

## 3. Core Components

### 3.1 VM Control Module (`vm_control.py`)
Interfaces with VMware via `asyncio.create_subprocess_exec`.
- **Capabilities:** Start (headless), Stop (soft), Restart (soft), Status Check, and Guest IP Resolution.
- **Dynamic IP Resolution:** Uses `getGuestIPAddress` to handle VMs with DHCP addresses.

### 3.2 TCP Proxy & Port Registry (`proxy.py`)
- **TCP Forwarder:** High-performance asynchronous pipe between host ports and guest ports.
- **Port Registry:** Prevents host port collisions and verifies port availability before binding.
- **Firewall Integration:** Automatically executes `netsh advfirewall` commands to open/close ports. Rules are restricted to `remoteip=localsubnet` to prevent exposure beyond the LAN.

### 3.3 Security & Authentication (`security.py`, `main.py`)
- **Authentication:** Password hashing using `Passlib` (BCrypt) and session management via JWT (`python-jose`).
- **LAN Restriction:** Middleware validates that incoming HTTP requests originate from private IP ranges (127.0.0.1, 192.168.x.x, 10.x.x.x, etc.).
- **Privilege Validation:** On startup, the system verifies Administrative rights using `ctypes`.

### 3.4 Logging (`logger_config.py`)
- **Format:** Structured JSON logging for machine readability.
- **Destination:** `vm_manager.log`.
- **Captured Data:** API requests, `vmrun` command outputs, firewall changes, and proxy connection errors.

## 4. API Specification

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/token` | POST | Authenticate and receive JWT token. |
| `/api/vms` | GET | List all managed VMs and their current statuses. |
| `/api/vms` | POST | Register a new VM by providing `.vmx` path and name. |
| `/api/vms/{id}` | DELETE | Remove a VM from management. |
| `/api/vms/{id}/start` | POST | Power on the virtual machine (Headless). |
| `/api/vms/{id}/stop` | POST | Soft shutdown of the virtual machine. |
| `/api/vms/{id}/restart`| POST | Soft reboot of the virtual machine. |
| `/api/proxies` | POST | Create a new TCP proxy rule for a specific VM. |
| `/api/proxies/{id}/toggle`| PUT | Enable/Disable a proxy rule (opens/closes firewall). |
| `/api/proxies/{id}` | DELETE | Remove a proxy rule configuration. |

## 5. Deployment Model
- **Process Management:** Hosted as a "Highest Privilege" task in Windows Task Scheduler.
- **Lifecycle:** Starts at system boot (`ONSTART`), running in the background under the `SYSTEM` account.
- **Dependencies:** Managed via `uv` for reproducible environments and `ruff` for code quality.

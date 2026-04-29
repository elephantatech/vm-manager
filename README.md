# VMware Web Manager

A robust Web UI and API for managing VMware Workstation/Player VMs on Windows 11. It allows you to control power states and expose VM ports to your local network (LAN) automatically. It also includes support for local services (Podman, Ollama) and persistent port blocking.

## 🚀 Key Features
- **Remote Power Control:** Start, Stop, and Restart VMs with automatic "hard" fallbacks.
- **Smart Discovery Scan:** Multi-layered scan across all user profiles to find your VMs.
- **Auto Port Forwarding:** Expose VM services (SSH, Web, etc.) to your LAN with one click.
- **Host Services Expose:** Easily proxy local services (e.g., Podman, Ollama, local web apps) to your LAN.
- **Persistent Port Registry:** Manually block or reserve ports to prevent conflicts.
- **RBAC Security:** Multi-user support with granular permissions and roles (Admin, Operator, etc.).
- **SQLite Persistence:** All configurations, users, and proxies are stored in a persistent database.
- **Background Service:** Runs silently as a Windows Task in your user context.

## 📋 Prerequisites
- **Windows 11** Host.
- **VMware Workstation/Player** installed.
- **[uv](https://github.com/astral-sh/uv)** installed.
- **Administrative Privileges**.

## 🛠️ Installation & Setup

### 1. Initialize Service
On the first start, the system creates a default account:
- **Username:** `admin`
- **Password:** `admin`

### 2. Install as Background Service
Run the installer from an **Administrator PowerShell**:
```powershell
cd vm-manager/vm-manager
powershell.exe -ExecutionPolicy Bypass -File install.ps1
```

## 📱 Usage
1. Navigate to `http://<YOUR-HOST-IP>:8000`.
2. Log in with `admin` / `admin`.
3. **Change your password immediately** via the "Settings / Profile" button.
4. **Expose Host Services:** Use the "Host Services" section to proxy local apps (e.g., Target `127.0.0.1:11434` for Ollama).
5. **Block Ports:** Use the "Port Registry" section to reserve ports (e.g., reserve `3306` for a local SQL server).
6. **Scan for VMs:** Automatically find and add your existing virtual machines.

## 🔒 Security
- **RBAC:** Access to every feature is controlled by permissions.
- **LAN Middleware:** The server only accepts connections from the local network.
- **Firewall:** Rules are created with `remoteip=localsubnet` restriction.

## 🛠️ Development
- **Tests:** `uv run pytest`
- **Upgrade:** Run `./upgrade.ps1` to apply code changes.
- **Formatting:** Code is formatted with `ruff format`.

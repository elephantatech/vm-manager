# VMware Web Manager

A robust Web UI and API for managing VMware Workstation/Player VMs on Windows 11. It allows you to control power states and expose VM ports to your local network (LAN) automatically.

## 🚀 Key Features
- **Remote Power Control:** Start, Stop, and Restart VMs with automatic "hard" fallbacks.
- **Smart Discovery Scan:** Multi-layered scan across all user profiles to find your VMs.
- **Auto Port Forwarding:** Expose VM services (SSH, Web, etc.) to your LAN with one click.
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
The manager now runs entirely via SQLite. On the first start, it creates a default account:
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
4. **Scan for VMs** to populate your dashboard.
5. **Manage Users:** If you are an Admin, you can create new users with specific roles (Manager, Operator, Viewer).

## 🔒 Security
- **RBAC:** Access to every feature is controlled by permissions.
- **LAN Middleware:** The server only accepts connections from the local network.
- **Firewall:** Rules are created with `remoteip=localsubnet` restriction.

## 🛠️ Development
- **Tests:** `uv run pytest`
- **Upgrade:** Run `./upgrade.ps1` to apply code changes.
- **Logs:** Default level is `WARNING`. Change via `LOG_LEVEL` environment variable.

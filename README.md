# VMware Web Manager

A robust Web UI and API for managing VMware Workstation/Player VMs on Windows 11. It allows you to control power states and expose VM ports to your local network (LAN) automatically.

## 🚀 Key Features
- **Remote Power Control:** Start, Stop, and Restart VMs from any device on your LAN.
- **Auto Port Forwarding:** Expose VM services (SSH, Web, etc.) to your LAN with one click.
- **Dynamic IP Handling:** Automatically tracks VM IP changes (DHCP).
- **LAN-Only Security:** Firewall rules and API access are strictly restricted to your local network.
- **Background Service:** Runs as a silent Windows background task.
- **JSON Logging:** Modern, machine-readable logs.

## 📋 Prerequisites
- **Windows 11** Host.
- **VMware Workstation** or **VMware Player** installed.
- **[uv](https://github.com/astral-sh/uv)** installed (Python project manager).
- **Administrative Privileges** (Required for Firewall management).

## 🛠️ Installation & Setup

### 1. Bootstrap Credentials
The first time you run the manager, you must set an admin username and password. This must be done manually in an elevated terminal:

1. Open **PowerShell as Administrator**.
2. Navigate to the project folder:
   ```powershell
   cd vm-manager
   ```
3. Run the manager:
   ```powershell
   uv run uvicorn main:app --port 8000
   ```
4. Follow the console prompts to create your admin account.
5. Press `Ctrl+C` to stop the server once credentials are saved.

### 2. Install as Background Service
To make the manager run automatically every time your computer starts:

1. In the **Administrator PowerShell**, run:
   ```powershell
   ./install.ps1
   ```
2. The manager is now running in the background as a Windows Task.

## 📱 Usage
1. Open a browser on any device in your LAN.
2. Navigate to `http://<YOUR-HOST-IP>:8000`.
3. Log in with your admin credentials.
4. Add your VMs by providing the full path to their `.vmx` files.
5. Use the "Expose Port" button to map a Host port to a VM port.

## 🔒 Security Notes
- **Firewall:** Every time you enable a proxy port, a temporary Windows Firewall rule is created with `remoteip=localsubnet`.
- **JWT:** API access is secured via JSON Web Tokens.
- **LAN Middleware:** The server rejects any HTTP requests that do not originate from private/local IP ranges.

## 🛠️ Development
- **Linting:** `uv run ruff check .`
- **Formatting:** `uv run ruff format .`
- **Logs:** View structured logs in `vm_manager.log`.

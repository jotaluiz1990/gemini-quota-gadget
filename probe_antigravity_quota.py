import json
import re
import subprocess
import urllib.request
from typing import Any, Dict, List, Optional


def fetch_antigravity_live_quota() -> Optional[Dict[str, Any]]:
    """Descobre o processo language_server.exe ativo, extrai o token CSRF e consulta as cotas reais."""
    try:
        # 1. Consulta o processo e sua linha de comando
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | "
            "Select-Object ProcessId, CommandLine | ConvertTo-Json"
        )
        proc_output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            errors="ignore",
        ).strip()

        if not proc_output:
            return None

        proc_data = json.loads(proc_output)
        if isinstance(proc_data, list):
            proc_data = proc_data[0]

        pid = proc_data.get("ProcessId")
        cmdline = proc_data.get("CommandLine", "")

        # 2. Extrai CSRF Token
        csrf_match = re.search(r"--csrf_token\s+([a-f0-9\-]+)", cmdline)
        if not csrf_match:
            return None
        csrf_token = csrf_match.group(1)

        # 3. Descobre portas TCP em escuta para o PID
        ports_cmd = (
            f"Get-NetTCPConnection -OwningProcess {pid} -State Listen "
            "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort"
        )
        ports_output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ports_cmd],
            text=True,
            errors="ignore",
        ).strip()

        ports = [int(p) for p in ports_output.split() if p.isdigit()]

        # 4. Envia requisição RPC Connect
        for port in ports:
            for proto in ["http", "https"]:
                url = f"{proto}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
                req = urllib.request.Request(
                    url,
                    data=b"{}",
                    headers={
                        "Content-Type": "application/json",
                        "x-codeium-csrf-token": csrf_token,
                        "Connect-Protocol-Version": "1",
                    },
                )
                try:
                    import ssl
                    ctx = ssl._create_unverified_context() if proto == "https" else None
                    with urllib.request.urlopen(req, timeout=1.5, context=ctx) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            return data.get("response", {})
                except Exception:
                    continue

        return None
    except Exception as e:
        print(f"Erro na descoberta: {e}")
        return None


if __name__ == "__main__":
    quota = fetch_antigravity_live_quota()
    if quota:
        print("=== COTA REAL DO ANTIGRAVITY RECUPERADA ===")
        for group in quota.get("groups", []):
            print(f"\nGrupo: {group.get('displayName')}")
            for b in group.get("buckets", []):
                fraction = b.get("remainingFraction", 0)
                pct = round(fraction * 100, 1)
                print(f"  - {b.get('displayName')} ({b.get('window')}): {pct}% restante | Reset: {b.get('resetTime')}")
    else:
        print("Não foi possível recuperar a cota.")

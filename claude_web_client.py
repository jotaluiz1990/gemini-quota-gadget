"""Cliente para consulta e monitoramento de cotas do Anthropic Claude Web (claude.ai).

Utiliza sessão autenticada via cookies de navegador (sessionKey) e os endpoints
internos (/api/organizations e /api/organizations/{org_id}/usage) para extrair os limites
de uso das janelas de 5 horas e limite semanal do plano Pro / Team.
"""

from datetime import datetime, timezone
import json
import time
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class ClaudeWebClient:
    """Cliente para obter cotas da interface web do Claude."""

    def __init__(self, cookie_string: str = "", on_cookie_update: Optional[Callable[[str], None]] = None):
        self.cookie_string = cookie_string.strip()
        self.cookie_dict: Dict[str, str] = self._parse_cookie_string(self.cookie_string)
        self.on_cookie_update = on_cookie_update
        self.org_id: Optional[str] = None
        self.plan_type: str = "PRO"
        self.org_name: str = "Claude"
        self.cached_quota: Optional[Dict[str, Any]] = None
        self.last_fetch: float = 0
        self.last_error: Optional[str] = None

    @staticmethod
    def _parse_cookie_string(s: str) -> Dict[str, str]:
        """Converte string de cabeçalho Cookie em dicionário chave-valor."""
        res: Dict[str, str] = {}
        if not s:
            return res
        for part in s.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                res[k.strip()] = v.strip()
            elif part:
                res["sessionKey"] = part
        return res

    def _get_cookie_header(self) -> str:
        """Gera string formatada para cabeçalho HTTP Cookie a partir do dicionário atual."""
        if not self.cookie_dict:
            return self.cookie_string
        return "; ".join([f"{k}={v}" for k, v in self.cookie_dict.items()])

    def set_cookies(self, cookie_string: str):
        """Atualiza a string de cookies e invalida estado anterior."""
        new_val = cookie_string.strip()
        if new_val != self.cookie_string:
            self.cookie_string = new_val
            self.cookie_dict = self._parse_cookie_string(new_val)
            self.org_id = None
            self.cached_quota = None
            self.last_error = None

    def _process_response_headers(self, headers) -> bool:
        """Captura cabeçalhos Set-Cookie e atualiza cookies dinamicamente."""
        if not headers:
            return False
        set_cookies = []
        if hasattr(headers, "get_all"):
            set_cookies = headers.get_all("Set-Cookie") or []
        elif hasattr(headers, "getheaders"):
            set_cookies = headers.getheaders("Set-Cookie") or []

        if not set_cookies:
            return False

        changed = False
        for sc in set_cookies:
            main_part = sc.split(";")[0].strip()
            if "=" in main_part:
                k, v = main_part.split("=", 1)
                k = k.strip()
                v = v.strip()
                if self.cookie_dict.get(k) != v:
                    self.cookie_dict[k] = v
                    changed = True

        if changed:
            self.cookie_string = self._get_cookie_header()
            if self.on_cookie_update:
                try:
                    self.on_cookie_update(self.cookie_string)
                except Exception:
                    pass
        return changed

    def _normalize_cookie_header(self) -> str:
        """Garante que a string de cookies contenha sessionKey."""
        header = self._get_cookie_header().strip()
        if not header:
            return ""
        if "=" not in header:
            return f"sessionKey={header}"
        return header

    def _fetch_organization_id(self) -> bool:
        """Obtém a lista de organizações do usuário e seleciona a organização ativa."""
        cookie_header = self._normalize_cookie_header()
        if not cookie_header:
            self.last_error = "Cookies não configurados"
            return False

        req = urllib.request.Request(
            "https://claude.ai/api/organizations",
            headers={
                "User-Agent": USER_AGENT,
                "Cookie": cookie_header,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://claude.ai/",
                "Origin": "https://claude.ai",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._process_response_headers(resp.headers)
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(data, list) and len(data) > 0:
                    chosen_org = data[0]
                    for org in data:
                        settings = org.get("settings", {})
                        if isinstance(settings, dict) and settings.get("is_default"):
                            chosen_org = org
                            break

                    self.org_id = chosen_org.get("uuid")
                    self.org_name = chosen_org.get("name", "Claude")

                    caps = chosen_org.get("capabilities", [])
                    if "claude_team" in caps:
                        self.plan_type = "TEAM"
                    elif "claude_enterprise" in caps:
                        self.plan_type = "ENTERPRISE"
                    elif "claude_pro" in caps or "chat" in caps:
                        self.plan_type = "PRO"
                    else:
                        self.plan_type = "PRO"

                    if self.org_id:
                        return True

                self.last_error = "Nenhuma organização encontrada para esta conta Claude."
                return False
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.last_error = "Sessão inválida ou expirada. Faça login no Claude em ⚙"
            else:
                self.last_error = f"Erro HTTP {e.code} ao acessar claude.ai"
            return False
        except Exception as e:
            self.last_error = f"Falha de conexão com claude.ai: {e}"
            return False

    def fetch_quota(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Consulta o endpoint de uso /api/organizations/{org_id}/usage."""
        cookie_header = self._normalize_cookie_header()
        if not cookie_header:
            return None

        if not force_refresh and self.cached_quota and (time.time() - self.last_fetch < 15):
            return self.cached_quota

        if not self.org_id and not self._fetch_organization_id():
            return None

        url = f"https://claude.ai/api/organizations/{self.org_id}/usage"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Cookie": cookie_header,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://claude.ai/settings/usage",
                "Origin": "https://claude.ai",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._process_response_headers(resp.headers)
                raw_json = json.loads(resp.read().decode("utf-8", errors="ignore"))
                parsed = self._parse_usage_response(raw_json)
                if parsed:
                    self.cached_quota = parsed
                    self.last_fetch = time.time()
                    self.last_error = None
                    return parsed
                else:
                    self.last_error = "Estrutura de cotas inesperada recebida do Claude"
                    return None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                if self._fetch_organization_id():
                    return self.fetch_quota(force_refresh=True)
                self.last_error = "Sessão expirada. Faça login novamente no Claude (abra ⚙)"
            else:
                self.last_error = f"Erro HTTP {e.code} na consulta de cotas"
            return None
        except Exception as e:
            self.last_error = f"Falha ao consultar cotas do Claude: {e}"
            return None

    def _parse_usage_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extrai e normaliza as métricas das janelas de 5 horas e 7 dias."""
        result = {
            "plan": self.plan_type,
            "org_name": self.org_name,
            "five_hour_used_pct": 0.0,
            "five_hour_remaining_pct": 100.0,
            "five_hour_reset_text": "",
            "five_hour_reset_epoch": None,
            "weekly_used_pct": 0.0,
            "weekly_remaining_pct": 100.0,
            "weekly_reset_text": "",
            "weekly_reset_epoch": None,
            "sonnet_used_pct": None,
            "opus_used_pct": None,
            "raw": data,
        }

        # 1. Janela de 5 horas (five_hour)
        fh = data.get("five_hour")
        if isinstance(fh, dict):
            raw_util = fh.get("utilization", 0.0)
            util_float = float(raw_util) if raw_util is not None else 0.0
            used_pct = round(util_float * 100 if util_float <= 1.0 else util_float, 1)
            used_pct = max(0.0, min(100.0, used_pct))
            rem_pct = round(max(0.0, 100.0 - used_pct), 1)

            result["five_hour_used_pct"] = used_pct
            result["five_hour_remaining_pct"] = rem_pct

            resets_at = fh.get("resets_at")
            if resets_at:
                txt, epoch = self._format_reset_time(resets_at)
                result["five_hour_reset_text"] = txt
                result["five_hour_reset_epoch"] = epoch

        # 2. Janela Semanal (seven_day)
        sd = data.get("seven_day")
        if isinstance(sd, dict):
            raw_util = sd.get("utilization", 0.0)
            util_float = float(raw_util) if raw_util is not None else 0.0
            used_pct = round(util_float * 100 if util_float <= 1.0 else util_float, 1)
            used_pct = max(0.0, min(100.0, used_pct))
            rem_pct = round(max(0.0, 100.0 - used_pct), 1)

            result["weekly_used_pct"] = used_pct
            result["weekly_remaining_pct"] = rem_pct

            resets_at = sd.get("resets_at")
            if resets_at:
                txt, epoch = self._format_reset_time(resets_at)
                result["weekly_reset_text"] = txt
                result["weekly_reset_epoch"] = epoch

        # 3. Model-specific breakdown if available (seven_day_consumption)
        sdc = data.get("seven_day_consumption")
        if isinstance(sdc, dict):
            sonnet = sdc.get("sonnet")
            if isinstance(sonnet, dict) and "utilization" in sonnet:
                u = float(sonnet["utilization"])
                result["sonnet_used_pct"] = round(u * 100 if u <= 1.0 else u, 1)
            opus = sdc.get("opus")
            if isinstance(opus, dict) and "utilization" in opus:
                u = float(opus["utilization"])
                result["opus_used_pct"] = round(u * 100 if u <= 1.0 else u, 1)

        return result

    @staticmethod
    def _format_reset_time(iso_str: str) -> Tuple[str, Optional[float]]:
        """Converte ISO timestamp em contagem regressiva e data/hora formatada."""
        try:
            s = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s).astimezone()
            now = datetime.now().astimezone()
            epoch = dt.timestamp()

            diff = dt - now
            total_sec = max(0, int(diff.total_seconds()))
            days = total_sec // 86400
            hours = (total_sec % 86400) // 3600
            minutes = (total_sec % 3600) // 60

            if days > 0:
                cd = f"{days}d {hours}h"
            elif hours > 0:
                cd = f"{hours}h {minutes}m"
            else:
                cd = f"{minutes}m"

            date_str = dt.strftime("%d/%m às %H:%M")
            return f"Reseta em {cd} • {date_str}", epoch
        except Exception:
            return f"Reseta em {iso_str}", None

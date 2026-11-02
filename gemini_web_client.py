"""Cliente para consulta e monitoramento de cotas do Google Gemini Web (gemini.google.com).

Utiliza sessão autenticada via cookies de navegador (__Secure-1PSID) e o endpoint
interno batchexecute (RPC jSf9Qc) para extrair os limites de uso do plano PRO/Advanced.
"""

from datetime import datetime, timezone
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class GeminiWebClient:
    """Cliente para obter cotas da interface web do Gemini."""

    def __init__(self, cookie_string: str = ""):
        self.cookie_string = cookie_string.strip()
        self.at_token: Optional[str] = None
        self.f_sid: Optional[str] = None
        self.cached_quota: Optional[Dict[str, Any]] = None
        self.last_fetch: float = 0
        self.last_error: Optional[str] = None

    def set_cookies(self, cookie_string: str):
        """Atualiza a string de cookies e invalida tokens antigos."""
        new_val = cookie_string.strip()
        if new_val != self.cookie_string:
            self.cookie_string = new_val
            self.at_token = None
            self.f_sid = None
            self.cached_quota = None
            self.last_error = None

    def _normalize_cookie_header(self) -> str:
        """Garante que a string de cookies esteja formatada para cabeçalho HTTP."""
        c = self.cookie_string.strip()
        if not c:
            return ""
        # Se o usuário colou apenas o valor do 1PSID sem a chave
        if "=" not in c:
            return f"__Secure-1PSID={c}"
        return c

    def _fetch_tokens(self) -> bool:
        """Carrega a página inicial do Gemini Web para extrair o token SNlM0e (at) e f.sid."""
        cookie_header = self._normalize_cookie_header()
        if not cookie_header:
            self.last_error = "Cookies não configurados"
            return False

        req = urllib.request.Request(
            "https://gemini.google.com/app",
            headers={
                "User-Agent": USER_AGENT,
                "Cookie": cookie_header,
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

                # Extrai token de CSRF do Google (SNlM0e)
                m_at = re.search(r'"SNlM0e":"([^"]+)"', html)
                if m_at:
                    self.at_token = m_at.group(1)

                m_fsid = re.search(r'"FdrFJe":"([^"]+)"', html)
                if m_fsid:
                    self.f_sid = m_fsid.group(1)

                if self.at_token:
                    return True

                self.last_error = "Não foi possível extrair o token SNlM0e. O cookie pode estar expirado."
                return False
        except urllib.error.HTTPError as e:
            self.last_error = f"Erro HTTP {e.code} ao acessar gemini.google.com"
            return False
        except Exception as e:
            self.last_error = f"Falha de conexão com Gemini Web: {e}"
            return False

    def fetch_quota(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Consulta o endpoint batchexecute (RPC jSf9Qc) para obter os dados de uso."""
        cookie_header = self._normalize_cookie_header()
        if not cookie_header:
            return None

        # Garante que temos o token at
        if not self.at_token and not self._fetch_tokens():
            return None

        # Constrói a requisição batchexecute
        rpc_url = (
            "https://gemini.google.com/_/BardChatUi/data/batchexecute?"
            "rpcids=jSf9Qc&source-path=%2Fapp&_reqid=100000&rt=c"
        )
        if self.f_sid:
            rpc_url += f"&f.sid={urllib.parse.quote(self.f_sid)}"

        # Payload para RPC jSf9Qc
        req_payload = [[["jSf9Qc", "[]", None, "generic"]]]
        form_data = {
            "f.req": json.dumps(req_payload),
            "at": self.at_token,
        }
        encoded_data = urllib.parse.urlencode(form_data).encode("utf-8")

        req = urllib.request.Request(
            rpc_url,
            data=encoded_data,
            headers={
                "User-Agent": USER_AGENT,
                "Cookie": cookie_header,
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
                "Referer": "https://gemini.google.com/",
                "Origin": "https://gemini.google.com",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_text = resp.read().decode("utf-8", errors="ignore")
                parsed = self._parse_batchexecute_response(raw_text)
                if parsed:
                    self.cached_quota = parsed
                    self.last_fetch = time.time()
                    self.last_error = None
                    return parsed
                else:
                    # Token pode ter expirado, tenta renovar uma vez
                    if self._fetch_tokens():
                        form_data["at"] = self.at_token
                        retry_data = urllib.parse.urlencode(form_data).encode("utf-8")
                        req2 = urllib.request.Request(rpc_url, data=retry_data, headers=req.headers)
                        with urllib.request.urlopen(req2, timeout=8) as resp2:
                            raw_text2 = resp2.read().decode("utf-8", errors="ignore")
                            parsed2 = self._parse_batchexecute_response(raw_text2)
                            if parsed2:
                                self.cached_quota = parsed2
                                self.last_fetch = time.time()
                                self.last_error = None
                                return parsed2

                    self.last_error = "Resposta vazia do batchexecute (jSf9Qc)"
                    return None
        except Exception as e:
            self.last_error = f"Erro na requisição RPC: {e}"
            return None

    def _parse_batchexecute_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Processa a resposta em lote do Google e extrai as cotas atuais e semanais."""
        try:
            # Respostas do batchexecute começam com prefixo anti-XSSI )]}'
            clean_text = text.replace(")]}'", "").strip()
            lines = clean_text.split("\n")

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    # Linhas contêm arrays no formato [[ "wrb.fr", "jSf9Qc", "...", ... ]]
                    data = json.loads(line)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, list) and len(item) > 2 and item[1] == "jSf9Qc":
                                inner_str = item[2]
                                if inner_str:
                                    inner_json = json.loads(inner_str)
                                    return self._extract_limits_from_json(inner_json)
                except Exception:
                    continue
            return None
        except Exception as e:
            print(f"Erro ao decodificar batchexecute: {e}")
            return None

    def _extract_limits_from_json(self, data: Any) -> Dict[str, Any]:
        """Extrai os limites e porcentagens da árvore JSON do RPC jSf9Qc."""
        result = {
            "plan": "PRO",
            "current_remaining_pct": 100.0,
            "current_used_pct": 0.0,
            "current_reset_text": "",
            "weekly_remaining_pct": 100.0,
            "weekly_used_pct": 0.0,
            "weekly_reset_text": "",
            "raw": data,
        }

        try:
            # Estrutura do jSf9Qc: [status, buckets_list, ...]
            # Cada bucket: [bucket_id, used_fraction, window_type, [[reset_ts_sec, nanos]]]
            buckets = None
            if isinstance(data, list):
                if len(data) > 1 and isinstance(data[1], list):
                    buckets = data[1]
                else:
                    for item in data:
                        if isinstance(item, list) and len(item) > 0 and isinstance(item[0], list):
                            buckets = item
                            break

            if buckets:
                for b in buckets:
                    if not isinstance(b, list) or len(b) < 3:
                        continue
                    used_frac = float(b[1]) if isinstance(b[1], (int, float)) else 0.0
                    win_type = b[2]
                    used_pct = round(used_frac * 100, 1)
                    rem_pct = round(max(0.0, min(100.0, (1.0 - used_frac) * 100)), 1)

                    # Formata contagem regressiva e data/hora do reset
                    reset_text = ""
                    if len(b) > 3 and isinstance(b[3], list) and len(b[3]) > 0:
                        ts_info = b[3][0]
                        if isinstance(ts_info, list) and len(ts_info) > 0:
                            ts_sec = ts_info[0]
                            if isinstance(ts_sec, (int, float)) and ts_sec > 1000000000:
                                dt_local = datetime.fromtimestamp(ts_sec, timezone.utc).astimezone()
                                now_local = datetime.now().astimezone()
                                diff = dt_local - now_local
                                total_sec = max(0, int(diff.total_seconds()))
                                days = total_sec // 86400
                                hours = (total_sec % 86400) // 3600
                                minutes = (total_sec % 3600) // 60
                                cd = f"{days}d {hours}h" if days > 0 else f"{hours}h {minutes}m"
                                date_str = dt_local.strftime("%d/%m às %H:%M")
                                reset_text = f"Reseta em {cd} • {date_str}"

                    # win_type == 1 é Uso Atual (janela curta); win_type == 2 é Limite Semanal
                    if win_type == 1:
                        result["current_used_pct"] = used_pct
                        result["current_remaining_pct"] = rem_pct
                        if reset_text:
                            result["current_reset_text"] = reset_text
                    elif win_type == 2:
                        result["weekly_used_pct"] = used_pct
                        result["weekly_remaining_pct"] = rem_pct
                        if reset_text:
                            result["weekly_reset_text"] = reset_text

        except Exception as e:
            print(f"Erro ao extrair limites do jSf9Qc: {e}")

        return result

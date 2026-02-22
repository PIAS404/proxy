# bestproxy_client.py
import os
import requests
from typing import Any, Dict, Optional
from endpoints import ENDPOINTS

class BestProxyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        # Provider অনুযায়ী header বদলাতে হতে পারে
        # Common patterns: Authorization: Bearer <key> OR X-API-Key: <key> OR app_key=<key>
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def call(self, name: str, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if name not in ENDPOINTS:
            return {"ok": False, "error": f"Endpoint '{name}' not configured"}

        meta = ENDPOINTS[name]
        method = meta["method"].upper()
        path = meta["path"]

        url = path if path.startswith("http") else f"{self.base_url}{path}"

        try:
            r = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                params=params,
                json=json,
                timeout=self.timeout
            )
            # try json
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text}

            # normalize
            if r.status_code >= 400:
                return {"ok": False, "status": r.status_code, "data": data}

            return {"ok": True, "status": r.status_code, "data": data}

        except requests.RequestException as e:
            return {"ok": False, "error": str(e)}

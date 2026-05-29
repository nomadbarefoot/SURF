"""Small reusable SURF HTTP client wrapper."""
import os
from typing import Any, Dict, Optional

import httpx


class SurfClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.base_url = (base_url or os.getenv("SURF_BASE_URL") or "http://127.0.0.1:17777").rstrip("/")
        self.token = token if token is not None else os.getenv("SURF_API_TOKEN")
        self.headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client = httpx.Client(timeout=180.0)

    def close(self) -> None:
        self.client.close()

    def create_session(self, profile_id: str = "agent-default", headed: bool = False) -> str:
        payload: Dict[str, Any] = {
            "config": {
                "profile_id": profile_id,
                "persist_profile": True,
                "headed": headed,
                "block_mode": "conservative",
                "content_mode": "compact",
            }
        }
        response = self.client.post(f"{self.base_url}/sessions/", headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()["session_id"]

    def navigate(self, session_id: str, url: str) -> Dict[str, Any]:
        response = self.client.post(
            f"{self.base_url}/browser/navigate",
            headers=self.headers,
            json={"session_id": session_id, "url": url, "wait_until": "domcontentloaded", "timeout": 90000},
        )
        response.raise_for_status()
        return response.json()["data"]

    def observe(self, session_id: str, mode: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"session_id": session_id, "max_text_length": 4000, "max_items": 50}
        if mode:
            payload["content_mode"] = mode
        response = self.client.post(f"{self.base_url}/browser/observe", headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()["data"]

    def fetch_json(self, session_id: str, url: str, backend: str = "browser") -> Any:
        response = self.client.post(
            f"{self.base_url}/fetch/request",
            headers=self.headers,
            json={"method": "GET", "url": url, "backend": backend, "session_id": session_id, "timeout": 60000},
        )
        response.raise_for_status()
        return response.json()["data"]["json"]

    def close_session(self, session_id: str) -> None:
        self.client.delete(f"{self.base_url}/sessions/{session_id}", headers=self.headers)


if __name__ == "__main__":
    surf = SurfClient()
    session = surf.create_session()
    try:
        surf.navigate(session, "https://example.com")
        print(surf.observe(session)["title"])
    finally:
        surf.close_session(session)
        surf.close()

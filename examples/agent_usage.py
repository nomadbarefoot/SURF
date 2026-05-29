"""Minimal SURF client for agents and one-off scripts.

Run SURF first:
    SURF_HOST=127.0.0.1 SURF_PORT=6670 .venv/bin/uvicorn main:app --host 127.0.0.1 --port 6670
"""
import json
import os
import time

import httpx


BASE_URL = os.getenv("SURF_BASE_URL", "http://127.0.0.1:6670")


def main() -> None:
    with httpx.Client(timeout=180.0) as client:
        token = login(client)
        headers = {"Authorization": f"Bearer {token}"}
        session_id = create_session(client, headers)

        try:
            navigate(client, headers, session_id, "https://www.nseindia.com/")
            observation = observe(client, headers, session_id)
            print("Observed:", observation["title"])
            print("Links:", len(observation.get("links", [])))

            # Warm BSE before using its API, so browser cookies and origin context exist.
            navigate(client, headers, session_id, "https://www.bseindia.com/")

            nse_actions = fetch_json(
                client,
                headers,
                session_id,
                "https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=RELIANCE",
            )
            bse_actions = fetch_json(
                client,
                headers,
                session_id,
                "https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w?scripcode=500325",
                extra_headers={"Referer": "https://www.bseindia.com/"},
            )

            print("NSE RELIANCE corporate actions:")
            print(json.dumps(nse_actions[:3], indent=2))
            print("BSE RELIANCE corporate actions:")
            print(json.dumps(bse_actions.get("Table2", [])[:3], indent=2))
        finally:
            close_session(client, headers, session_id)


def login(client: httpx.Client) -> str:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": "agent", "password": "password123"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def create_session(client: httpx.Client, headers: dict[str, str]) -> str:
    response = client.post(
        f"{BASE_URL}/sessions/",
        headers=headers,
        json={
            "config": {
                "profile_id": "agent-default",
                "headed": True,
                "persist_profile": True,
                "stealth_strategy": "minimal",
            }
        },
    )
    response.raise_for_status()
    return response.json()["session_id"]


def navigate(client: httpx.Client, headers: dict[str, str], session_id: str, url: str) -> dict:
    response = client.post(
        f"{BASE_URL}/browser/navigate",
        headers=headers,
        json={
            "session_id": session_id,
            "url": url,
            "wait_until": "domcontentloaded",
            "timeout": 90000,
        },
    )
    response.raise_for_status()
    data = response.json()["data"]
    time.sleep(1)
    return data


def observe(client: httpx.Client, headers: dict[str, str], session_id: str) -> dict:
    response = client.post(
        f"{BASE_URL}/browser/observe",
        headers=headers,
        json={"session_id": session_id, "max_text_length": 4000, "max_items": 50},
    )
    response.raise_for_status()
    return response.json()["data"]


def fetch_json(
    client: httpx.Client,
    headers: dict[str, str],
    session_id: str,
    url: str,
    extra_headers: dict[str, str] | None = None,
):
    response = client.post(
        f"{BASE_URL}/fetch/request",
        headers=headers,
        json={
            "method": "GET",
            "url": url,
            "backend": "curl_cffi",
            "session_id": session_id,
            "headers": extra_headers,
            "timeout": 60000,
        },
    )
    response.raise_for_status()
    return response.json()["data"]["json"]


def close_session(client: httpx.Client, headers: dict[str, str], session_id: str) -> None:
    client.delete(f"{BASE_URL}/sessions/{session_id}", headers=headers)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Minimal SURF browser automation example."""
import asyncio
import os

import httpx


BASE_URL = os.getenv("SURF_BASE_URL", "http://127.0.0.1:17777")


async def main():
    token = os.getenv("SURF_API_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient(timeout=60.0) as client:
        session = await client.post(
            f"{BASE_URL}/sessions/",
            headers=headers,
            json={"config": {"profile_id": "example", "persist_profile": True}},
        )
        session.raise_for_status()
        session_id = session.json()["session_id"]

        try:
            nav = await client.post(
                f"{BASE_URL}/browser/navigate",
                headers=headers,
                json={"session_id": session_id, "url": "https://example.com", "wait_until": "domcontentloaded"},
            )
            nav.raise_for_status()
            print(f"Status: {nav.json()['data']['status']}")

            obs = await client.post(
                f"{BASE_URL}/browser/observe",
                headers=headers,
                json={"session_id": session_id, "max_text_length": 1000, "max_items": 20},
            )
            obs.raise_for_status()
            print(f"Title: {obs.json()['data']['title']}")
        finally:
            await client.delete(f"{BASE_URL}/sessions/{session_id}", headers=headers)


if __name__ == "__main__":
    asyncio.run(main())

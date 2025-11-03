#!/usr/bin/env python3
"""Example SURF browser automation"""

import asyncio
import httpx
import json

BASE_URL = "http://localhost:6660"

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Login
        print("🔐 Logging in...")
        login = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "testuser", "password": "testpass123"}
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create session
        print("📱 Creating session...")
        session = await client.post(
            f"{BASE_URL}/sessions/",
            headers=headers,
            json={"headless": True}
        )
        session_id = session.json()["session_id"]
        print(f"   Session ID: {session_id}")
        
        try:
            # Navigate
            print("🌐 Navigating to example.com...")
            nav = await client.post(
                f"{BASE_URL}/browser/navigate",
                headers=headers,
                json={
                    "session_id": session_id,
                    "url": "https://example.com",
                    "wait_until": "networkidle"
                }
            )
            print(f"   Status: {nav.json()['data']['status']}")
            
            # Extract title
            print("📄 Extracting content...")
            extract = await client.post(
                f"{BASE_URL}/browser/extract",
                headers=headers,
                json={
                    "session_id": session_id,
                    "extract_type": "text",
                    "selector": "h1"
                }
            )
            title = extract.json()["data"]["content"]
            print(f"   Title: {title}")
            
        finally:
            # Cleanup
            print("🧹 Closing session...")
            await client.delete(
                f"{BASE_URL}/sessions/{session_id}",
                headers=headers
            )
            print("✅ Done!")

if __name__ == "__main__":
    asyncio.run(main())

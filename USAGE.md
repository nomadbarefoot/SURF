# SURF Browser Service - Usage Guide

## Quick Start

### 1. Start the Server

```bash
# Activate virtual environment
source venv/bin/activate

# Start server (already running on port 6660)
python start_surf.py
```

Server will be available at: `http://localhost:6660`

## Authentication

Most endpoints require authentication. First, get a JWT token:

### Login

```bash
curl -X POST http://localhost:6660/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "testpass123"
  }'
```

Response:
```json
{
  "success": true,
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpVVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "username": "testuser",
    "scopes": ["browser:read", "browser:write", "sessions:manage"]
  }
}
```

Save the `access_token` for subsequent requests.

## Basic Workflow

### Step 1: Create a Session

```bash
TOKEN="your-access-token-here"

curl -X POST http://localhost:6660/sessions/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "headless": true,
    "stealth": true
  }'
```

Response:
```json
{
  "success": true,
  "session_id": "sess_abc123...",
  "config": {...},
  "expires_at": "2025-11-03T01:00:00"
}
```

Save the `session_id` for browser operations.

### Step 2: Navigate to a URL

```bash
SESSION_ID="sess_abc123..."

curl -X POST http://localhost:6660/browser/navigate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "url": "https://example.com",
    "wait_until": "networkidle",
    "timeout": 30000
  }'
```

### Step 3: Extract Content

```bash
# Extract text from body
curl -X POST http://localhost:6660/browser/extract \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "extract_type": "text",
    "selector": "body",
    "timeout": 10000
  }'

# Extract links
curl -X POST http://localhost:6660/browser/extract \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "extract_type": "links",
    "selector": "a"
  }'

# Extract images
curl -X POST http://localhost:6660/browser/extract \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "extract_type": "images",
    "selector": "img"
  }'
```

### Step 4: Interact with Elements

```bash
# Click an element
curl -X POST http://localhost:6660/browser/interact \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "action": "click",
    "selector": "button.submit",
    "timeout": 5000
  }'

# Type text
curl -X POST http://localhost:6660/browser/interact \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "action": "type",
    "selector": "input[name=\"search\"]",
    "value": "search query",
    "timeout": 5000
  }'

# Scroll
curl -X POST http://localhost:6660/browser/interact \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "action": "scroll",
    "selector": "body",
    "options": {"direction": "down", "pixels": 500}
  }'
```

### Step 5: Take Screenshots

```bash
# Full page screenshot
curl -X POST http://localhost:6660/browser/screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "full_page": true,
    "path": "screenshot.png"
  }'

# Element screenshot
curl -X POST http://localhost:6660/browser/screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "selector": ".header",
    "path": "header.png"
  }'
```

### Step 6: Cleanup

```bash
# Close session
curl -X DELETE http://localhost:6660/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN"
```

## Python Example

```python
import asyncio
import httpx

BASE_URL = "http://localhost:6660"

async def example_usage():
    async with httpx.AsyncClient() as client:
        # 1. Login
        login_response = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "testuser", "password": "testpass123"}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Create session
        session_response = await client.post(
            f"{BASE_URL}/sessions/",
            headers=headers,
            json={"headless": True, "stealth": True}
        )
        session_id = session_response.json()["session_id"]
        
        # 3. Navigate
        await client.post(
            f"{BASE_URL}/browser/navigate",
            headers=headers,
            json={
                "session_id": session_id,
                "url": "https://example.com",
                "wait_until": "networkidle"
            }
        )
        
        # 4. Extract content
        extract_response = await client.post(
            f"{BASE_URL}/browser/extract",
            headers=headers,
            json={
                "session_id": session_id,
                "extract_type": "text",
                "selector": "body"
            }
        )
        content = extract_response.json()
        print(content["data"]["content"][:200])  # First 200 chars
        
        # 5. Cleanup
        await client.delete(
            f"{BASE_URL}/sessions/{session_id}",
            headers=headers
        )

# Run
asyncio.run(example_usage())
```

## Advanced Features

### Extract Structured Data

```bash
curl -X POST http://localhost:6660/browser/extract-structured \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "content_type": "news",
    "selector": "body"
  }'
```

### Detect CAPTCHA

```bash
curl -X POST http://localhost:6660/browser/detect-captcha \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'"
  }'
```

### Batch Operations

```bash
curl -X POST http://localhost:6660/browser/batch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "operations": [
      {"type": "navigate", "url": "https://site1.com"},
      {"type": "extract", "extract_type": "text", "selector": "body"},
      {"type": "navigate", "url": "https://site2.com"},
      {"type": "extract", "extract_type": "links", "selector": "a"}
    ],
    "parallel": false
  }'
```

## Available Endpoints

### Authentication
- `POST /auth/login` - Get JWT token
- `POST /auth/api-key` - Create API key
- `GET /auth/me` - Get current user info

### Sessions
- `POST /sessions/` - Create session
- `GET /sessions/{session_id}` - Get session info
- `GET /sessions` - List all sessions
- `DELETE /sessions/{session_id}` - Close session

### Browser Operations
- `POST /browser/navigate` - Navigate to URL
- `POST /browser/extract` - Extract content (text, html, links, images, table)
- `POST /browser/interact` - Interact with elements (click, type, scroll, hover)
- `POST /browser/screenshot` - Take screenshot
- `POST /browser/extract-structured` - Extract structured data
- `POST /browser/detect-captcha` - Detect CAPTCHA
- `POST /browser/batch` - Execute multiple operations

### Health
- `GET /health/` - Health check
- `GET /health/ready` - Readiness check
- `GET /health/live` - Liveness check
- `GET /health/metrics` - Detailed metrics

## Extract Types

- `text` - Plain text content
- `html` - HTML content
- `links` - All links (href attributes)
- `images` - All images (src attributes)
- `table` - Table data (rows and cells)

## Wait Until Options

- `load` - Wait for load event
- `domcontentloaded` - Wait for DOMContentLoaded
- `networkidle` - Wait for network idle (default)
- `commit` - Wait for navigation commit

## Tips

1. **Session Management**: Sessions expire after TTL (default 5 minutes). Create new sessions as needed.

2. **Error Handling**: All endpoints return structured error responses. Check `success` field.

3. **Timeouts**: Set appropriate timeouts for slow-loading pages.

4. **Stealth Mode**: Enabled by default - helps avoid detection.

5. **Session Limits**: Default max 20 concurrent sessions. Check `/health/metrics` for usage.

## Complete Example Script

Save as `example.py`:

```python
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
            
            # Get links
            links = await client.post(
                f"{BASE_URL}/browser/extract",
                headers=headers,
                json={
                    "session_id": session_id,
                    "extract_type": "links",
                    "selector": "a"
                }
            )
            link_count = len(links.json()["data"]["content"])
            print(f"   Found {link_count} links")
            
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
```

Run:
```bash
python example.py
```


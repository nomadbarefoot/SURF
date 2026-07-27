# surf_fetch sample

Served by: deployed `surf` docker container (127.0.0.1:17777)

Tool: `POST /fetch/request`

Request: `{"method": "GET", "url": "https://api.github.com/rate_limit"}`

Response bytes (pretty JSON): 1006

## Exact payload delivered to the agent

```json
{
  "success": true,
  "data": {
    "status": 200,
    "url": "https://api.github.com/rate_limit",
    "content_type": "application/json; charset=utf-8",
    "json": {
      "resources": {
        "code_search": {
          "limit": 60,
          "remaining": 60,
          "reset": 1785195214,
          "used": 0
        },
        "core": {
          "limit": 60,
          "remaining": 60,
          "reset": 1785195214,
          "used": 0
        },
        "graphql": {
          "limit": 0,
          "remaining": 0,
          "reset": 1785195214,
          "used": 0
        },
        "integration_manifest": {
          "limit": 5000,
          "remaining": 5000,
          "reset": 1785195214,
          "used": 0
        },
        "search": {
          "limit": 10,
          "remaining": 10,
          "reset": 1785191674,
          "used": 0
        }
      },
      "rate": {
        "limit": 60,
        "remaining": 60,
        "reset": 1785195214,
        "used": 0
      }
    }
  }
}
```

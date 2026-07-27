# surf_search sample

Served by: deployed `surf` docker container (127.0.0.1:17777)

Tool: `POST /search/query`

Request: `{"query": "how to handle github api secondary rate limits", "max_results": 3}`

Response bytes (pretty JSON): 7408

## Exact payload delivered to the agent

```json
{
  "success": true,
  "results": [
    {
      "title": "Rate limits for the REST API",
      "snippet": "## About secondary rate limits. In addition to primary rate limits, GitHub enforces secondary rate limits in order to prevent abuse and keep the API available for all users. You may encounter a secondary rate limit if you:. * *Make too many concurrent requests.* No more than 100 concurrent requests are allowed. This limit is shared across the REST API and GraphQL API. * *Make too many requests to a single endpoint per minute.* No more than 900 points per minute are allowed for REST API endpoints, and no more than 2,000 points per minute are allowed for the GraphQL API endpoint. For more information about points, see [Calculating points for the secondary rate limit](#calculating-points-for-the-secondary-rate-limit). * *Make too many requests per minute.* No more than 90 seconds of CPU time per 60 seconds of real time is allowed. No more than 60 seconds of this CPU time may be for the GraphQL API. You can roughly estimate the CPU time by measuring the total response time for your API requests. * *Make too many requests that consume excessive compute resources in a short period of time.*. * *Create too much content on GitHub in a short amount of time.* In general, no more than 80 content-generating requests per minute and no more than 500 content-generating requests per hour are allowed. Some endpoints have lower content creation limits. Content creation limits include actions taken on the GitHub web interface as well as via the REST API and GraphQL API. * *Make too many OAuth access token requests in a short period of time.* No more than 2,000 OAuth access token requests per hour are allowed for GitHub Apps and OAuth apps. These secondary rate limits are subject to change without notice. You may also encounter a secondary rate limit for undisclosed reasons. ### Calculating points for the secondary rate limit. Some secondary rate limits are determined by the point values of requests. For GraphQL requests, these point values are separate from the point value calculations for the primary rate limit. You can also call the `GET /rate_limit` endpoint to check your rate limit. Calling this endpoint does not count against your primary rate limit, but it can count against your secondary rate limit. See [REST API endpoints for rate limits](/en/rest/rate-limit/rate-limit). When possible, you should use the rate limit response headers instead of calling the API to check your rate limit. There is not a way to check the status of your secondary rate limit. ## Exceeding the rate limit. If you exceed your primary rate limit, you will receive a `403` or `429` response, and the `x-ratelimit-remaining` header will be `0`. You should not retry your request until after the time specified by the `x-ratelimit-reset` header. If you exceed a secondary rate limit, you will receive a `403` or `429` response and an error message that indicates that you exceeded a secondary rate limit. If the `retry-after` response header is present, you should not retry your request until after that many seconds has elapsed. If the `x-ratelimit-remaining` header is `0`, you should not retry your request until after the time, in UTC epoch seconds, specified by the `x-ratelimit-reset` header. Otherwise, wait for at least one minute before retrying. If your request continues to fail due to a secondary rate limit, wait for an exponentially increasing amount of time between retries, and throw an error after a specific number of retries",
      "url": "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api",
      "source": "exa",
      "published": null,
      "relevance": 0.884
    },
    {
      "title": "",
      "snippet": "GitHub enforces rate limits to ensure that the API stays available for all users. For more information, see [Rate limits for the REST API](/en/rest/using-the-rest-api/rate-limits-for-the-rest-api). If you exceed your primary rate limit, you will receive a `403 Forbidden` or `429 Too Many Requests ` response, and the `x-ratelimit-remaining` header will be `0`. If you exceed a secondary rate limit, you will receive a `403 Forbidden` or `429 Too Many Requests ` response and an error message that indicates that you exceeded a secondary rate limit. If you receive a rate limit error, you should stop making requests temporarily according to these guidelines:. * If the `retry-after` response header is present, you should not retry your request until after that many seconds has elapsed. * If the `x-ratelimit-remaining` header is `0`, you should not make another request until after the time specified by the `x-ratelimit-reset` header. The `x-ratelimit-reset` header is in UTC epoch seconds. * Otherwise, wait for at least one minute before retrying. If your request continues to fail due to a secondary rate limit, wait for an exponentially increasing amount of time between retries, and throw an error after a specific number of retries. Continuing to make requests while you are rate limited may result in the banning of your integration. For more information about how to avoid exceeding the rate limits, see [Best practices for using the REST API](/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)",
      "url": "https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api?apiVersion=2026-03-10",
      "source": "exa",
      "published": null,
      "relevance": 0.871
    },
    {
      "title": "",
      "snippet": "You should subscribe to webhook events instead of polling the API for data. This will help your integration stay within the API rate limit. For more information, see Webhooks documentation. Authenticated requests have a higher primary rate limit than unauthenticated requests. To avoid exceeding the rate limit, you should make authenticated requests. For more information, see Rate limits for the REST API. ## Avoid concurrent requests. To avoid exceeding secondary rate limits, you should make requests serially instead of concurrently. To achieve this, you can implement a queue system for requests. ## Pause between mutative requests. If you are making a large number of `POST`, `PATCH`, `PUT`, or `DELETE` requests, wait at least one second between each request. This will help you avoid secondary rate limits. ## Handle rate limit errors appropriately. If you receive a rate limit error, you should stop making requests temporarily according to these guidelines:. - If the `retry-after` response header is present, you should not retry your request until after that many seconds has elapsed. - If the `x-ratelimit-remaining` header is `0`, you should not make another request until after the time specified by the `x-ratelimit-reset` header. The `x-ratelimit-reset` header is in UTC epoch seconds. - Otherwise, wait for at least one minute before retrying. If your request continues to fail due to a secondary rate limit, wait for an exponentially increasing amount of time between retries, and throw an error after a specific number of retries. Continuing to make requests while you are rate limited may result in the banning of your integration",
      "url": "https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api?apiVersion=2026-03-10",
      "source": "exa",
      "published": null,
      "relevance": 0.831
    }
  ]
}
```

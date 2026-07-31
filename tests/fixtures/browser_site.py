"""Local browser test fixtures served by a small HTTP server."""
from __future__ import annotations

from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import AsyncIterator


FIXTURE_INDEX = """
<!doctype html>
<html>
<head><title>Fixture Index</title></head>
<body>
<h1>SURF Browser Fixtures</h1>
<ul>
  <li><a href="/spa-hydrate">SPA hydration</a></li>
  <li><a href="/spa-router">SPA History router</a></li>
  <li><a href="/lazy-scroll">Lazy scroll</a></li>
  <li><a href="/challenge-delay">Challenge-like delay</a></li>
  <li><a href="/download.txt">Direct text download</a></li>
</ul>
</body>
</html>
"""

HYDRATE_PAGE = """
<!doctype html>
<html>
<head><title>SPA Hydrate</title></head>
<body>
<div id="app">Loading...</div>
<script>
  setTimeout(() => {
    document.getElementById('app').innerHTML = '<h1 data-testid="hydrated">Hydrated Content</h1><p>This content appears after hydration.</p>';
  }, 1200);
</script>
</body>
</html>
"""

ROUTER_PAGE = """
<!doctype html>
<html>
<head><title>SPA Router</title></head>
<body>
<div id="app">
  <nav>
    <a href="/route-a" id="link-a">Go to A</a>
    <a href="/route-b" id="link-b">Go to B</a>
  </nav>
  <main id="main">Home</main>
</div>
<script>
  function render(path) {
    const main = document.getElementById('main');
    if (path === '/route-a') main.innerHTML = '<h1 data-testid="route-a">Route A</h1>';
    else if (path === '/route-b') main.innerHTML = '<h1 data-testid="route-b">Route B</h1>';
    else main.innerHTML = '<h1>Home</h1>';
  }
  document.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      history.pushState({}, '', a.getAttribute('href'));
      render(window.location.pathname);
    });
  });
  window.addEventListener('popstate', () => render(window.location.pathname));
</script>
</body>
</html>
"""

LAZY_SCROLL_PAGE = """
<!doctype html>
<html>
<head><title>Lazy Scroll</title></head>
<body>
<div id="items"></div>
<div id="sentinel" style="height:1px;"></div>
<script>
  let count = 0;
  function loadMore() {
    if (count >= 20) return;
    const items = document.getElementById('items');
    for (let i = 0; i < 5; i++) {
      count++;
      const p = document.createElement('p');
      p.textContent = 'Item ' + count;
      p.className = 'item';
      items.appendChild(p);
    }
  }
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => { if (e.isIntersecting) loadMore(); });
  });
  observer.observe(document.getElementById('sentinel'));
  loadMore();
</script>
<style>.item { height: 200px; }</style>
</body>
</html>
"""

CHALLENGE_DELAY_PAGE = """
<!doctype html>
<html>
<head><title>Just a moment...</title></head>
<body>
<div id="challenge">Checking your browser...</div>
<script>
  setTimeout(() => {
    document.getElementById('challenge').innerHTML = '<h1>Welcome</h1><p>Challenge cleared.</p>';
    document.title = 'Welcome';
  }, 2500);
</script>
</body>
</html>
"""


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, "text/html", FIXTURE_INDEX)
        elif path == "/spa-hydrate":
            self._send(200, "text/html", HYDRATE_PAGE)
        elif path == "/spa-router":
            self._send(200, "text/html", ROUTER_PAGE)
        elif path in ("/route-a", "/route-b"):
            self._send(200, "text/html", ROUTER_PAGE)
        elif path == "/lazy-scroll":
            self._send(200, "text/html", LAZY_SCROLL_PAGE)
        elif path == "/challenge-delay":
            self._send(200, "text/html", CHALLENGE_DELAY_PAGE)
        elif path == "/download.txt":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", "attachment; filename=download.txt")
            self.end_headers()
            self.wfile.write(b"This is a downloaded text file.")
        elif path == "/plain-doc":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Plain document content here.")
        else:
            self._send(404, "text/plain", "Not found")

    def _send(self, status: int, content_type: str, body: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


@asynccontextmanager
async def run_fixture_server(host: str = "127.0.0.1", port: int = 0) -> AsyncIterator[str]:
    """Run the fixture server in a background thread and yield its base URL."""
    server = ThreadingHTTPServer((host, port), _FixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        actual_port = server.server_address[1]
        yield f"http://{host}:{actual_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)

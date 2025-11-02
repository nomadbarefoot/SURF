"""
Advanced Anti-Detection and Stealth Utilities
Implements proxy rotation, user agent pools, human mimicry, and fingerprint masking
"""

import random
import time
import asyncio
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from playwright.async_api import Page, BrowserContext
import structlog

logger = structlog.get_logger()

@dataclass
class ProxyConfig:
    """Proxy configuration"""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: str = "http"
    
    @property
    def url(self) -> str:
        """Get proxy URL"""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"

class ProxyRotator:
    """Intelligent proxy rotation system"""
    
    def __init__(self, proxies: List[ProxyConfig]):
        self.proxies = proxies
        self.current_index = 0
        self.failed_proxies = set()
        self.proxy_stats = {i: {"success": 0, "failures": 0, "last_used": 0.0} for i in range(len(proxies))}
    
    def get_next_proxy(self) -> Optional[ProxyConfig]:
        """Get next available proxy with intelligent selection"""
        available_proxies = [
            (i, proxy) for i, proxy in enumerate(self.proxies) 
            if i not in self.failed_proxies
        ]
        
        if not available_proxies:
            # Reset failed proxies if all are marked as failed
            self.failed_proxies.clear()
            available_proxies = list(enumerate(self.proxies))
        
        if not available_proxies:
            return None
        
        # Weighted selection based on success rate and recency
        weights = []
        current_time = time.time()
        
        for i, proxy in available_proxies:
            stats = self.proxy_stats[i]
            success_rate = stats["success"] / max(stats["success"] + stats["failures"], 1)
            recency_factor = 1.0 / (1.0 + (current_time - stats["last_used"]) / 3600.0)  # Decay over 1 hour
            weight = success_rate * 0.7 + recency_factor * 0.3
            weights.append(weight)
        
        # Select proxy based on weights
        selected_index = random.choices(range(len(available_proxies)), weights=weights)[0]
        proxy_index, proxy = available_proxies[selected_index]
        
        self.current_index = proxy_index
        self.proxy_stats[proxy_index]["last_used"] = current_time
        
        return proxy
    
    def mark_success(self, proxy_index: int):
        """Mark proxy as successful"""
        self.proxy_stats[proxy_index]["success"] += 1
        if proxy_index in self.failed_proxies:
            self.failed_proxies.remove(proxy_index)
    
    def mark_failure(self, proxy_index: int):
        """Mark proxy as failed"""
        self.proxy_stats[proxy_index]["failures"] += 1
        if self.proxy_stats[proxy_index]["failures"] > 3:
            self.failed_proxies.add(proxy_index)

class UserAgentPool:
    """Enhanced user agent rotation with device-specific patterns"""
    
    def __init__(self):
        self.user_agents = {
            "windows_chrome": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            ],
            "mac_chrome": [
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ],
            "linux_chrome": [
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            ],
            "windows_firefox": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            ],
            "mac_safari": [
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
            ],
            "mobile_chrome": [
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1.2 Mobile/15E148 Safari/604.1",
                "Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            ]
        }
        
        # Flatten all user agents
        self.all_user_agents = []
        for category, agents in self.user_agents.items():
            self.all_user_agents.extend(agents)
    
    def get_random_user_agent(self, category: Optional[str] = None) -> str:
        """Get random user agent from specified category or all"""
        if category and category in self.user_agents:
            return random.choice(self.user_agents[category])
        return random.choice(self.all_user_agents)
    
    def get_user_agent_with_device_info(self) -> Tuple[str, Dict[str, Any]]:
        """Get user agent with associated device information"""
        category = random.choice(list(self.user_agents.keys()))
        user_agent = random.choice(self.user_agents[category])
        
        device_info = {
            "category": category,
            "platform": self._extract_platform(category),
            "browser": self._extract_browser(category),
            "is_mobile": "mobile" in category
        }
        
        return user_agent, device_info
    
    def _extract_platform(self, category: str) -> str:
        """Extract platform from category"""
        if "windows" in category:
            return "Windows"
        elif "mac" in category:
            return "macOS"
        elif "linux" in category:
            return "Linux"
        elif "mobile" in category or "iphone" in category or "android" in category:
            return "Mobile"
        return "Unknown"
    
    def _extract_browser(self, category: str) -> str:
        """Extract browser from category"""
        if "chrome" in category:
            return "Chrome"
        elif "firefox" in category:
            return "Firefox"
        elif "safari" in category:
            return "Safari"
        return "Unknown"

class AdaptiveRateLimiter:
    """Adaptive rate limiting that adjusts based on success/failure patterns"""
    
    def __init__(self, 
                 base_delay: float = 2.0,
                 min_delay: float = 0.5,
                 max_delay: float = 10.0,
                 success_increment: float = 0.1,
                 failure_decrement: float = 0.2):
        self.success_rate = 1.0
        self.base_delay = base_delay
        self.current_delay = base_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.success_increment = success_increment
        self.failure_decrement = failure_decrement
        self.total_requests = 0
        self.successful_requests = 0
        
    def get_next_delay(self, success: bool) -> float:
        """Calculate next delay based on success/failure"""
        self.total_requests += 1
        
        if success:
            self.successful_requests += 1
            self.success_rate = min(1.0, self.success_rate + self.success_increment)
            self.current_delay = max(self.min_delay, self.current_delay * 0.9)
        else:
            self.success_rate = max(0.1, self.success_rate - self.failure_decrement)
            self.current_delay = min(self.max_delay, self.current_delay * 2.0)
        
        # Add random jitter to avoid synchronized requests
        jitter = random.uniform(0, 1.0)
        return self.current_delay + jitter
    
    async def wait_if_needed(self, success: bool) -> None:
        """Wait for the calculated delay if needed"""
        delay = self.get_next_delay(success)
        if delay > 0:
            await asyncio.sleep(delay)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiter statistics"""
        return {
            "success_rate": self.success_rate,
            "current_delay": self.current_delay,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failure_rate": 1.0 - self.success_rate
        }

class HumanMouseMovement:
    """Enhanced human-like mouse movement simulation using Bezier curves"""
    
    @staticmethod
    def generate_bezier_path(start: Tuple[int, int], 
                            end: Tuple[int, int], 
                            num_points: int = 20) -> List[Tuple[int, int]]:
        """Generate a smooth Bezier curve path between two points"""
        # Add random control points for more natural movement
        control_x = (start[0] + end[0]) / 2 + random.randint(-50, 50)
        control_y = (start[1] + end[1]) / 2 + random.randint(-30, 30)
        
        path = []
        for i in range(num_points):
            t = i / (num_points - 1)
            # Quadratic Bezier curve formula
            x = (1-t)**2 * start[0] + 2*(1-t)*t * control_x + t**2 * end[0]
            y = (1-t)**2 * start[1] + 2*(1-t)*t * control_y + t**2 * end[1]
            path.append((int(x), int(y)))
        
        return path
    
    @staticmethod
    async def human_like_move(page: Page, 
                            target_selector: str,
                            bezier_points: int = 20,
                            min_delay: float = 0.01,
                            max_delay: float = 0.03,
                            reaction_delay_min: float = 0.1,
                            reaction_delay_max: float = 0.3) -> None:
        """Move mouse to target element using human-like Bezier curve path"""
        try:
            # Get current mouse position (approximate)
            current_pos = (random.randint(100, 500), random.randint(100, 400))
            
            # Get target element position
            element = page.locator(target_selector)
            box = await element.bounding_box()
            if not box:
                logger.warning("Could not get bounding box for target element", selector=target_selector)
                return
                
            target_pos = (int(box['x'] + box['width']/2), int(box['y'] + box['height']/2))
            
            # Generate smooth path
            path = HumanMouseMovement.generate_bezier_path(current_pos, target_pos, bezier_points)
            
            # Move along path with realistic timing
            for point in path[::2]:  # Skip some points for speed
                await page.mouse.move(point[0], point[1])
                await asyncio.sleep(random.uniform(min_delay, max_delay))
            
            # Small pause before click (human reaction time)
            await asyncio.sleep(random.uniform(reaction_delay_min, reaction_delay_max))
            
        except Exception as e:
            logger.error("Human-like mouse movement failed", error=str(e), selector=target_selector)
    
    @staticmethod
    async def random_mouse_wiggle(page: Page, intensity: int = 3) -> None:
        """Perform small random mouse movements to simulate human behavior"""
        try:
            viewport = page.viewport_size
            if not viewport:
                return
            
            current_x, current_y = random.randint(100, viewport["width"] - 100), random.randint(100, viewport["height"] - 100)
            
            for _ in range(intensity):
                # Small random movements around current position
                offset_x = random.randint(-20, 20)
                offset_y = random.randint(-20, 20)
                new_x = max(0, min(viewport["width"], current_x + offset_x))
                new_y = max(0, min(viewport["height"], current_y + offset_y))
                
                await page.mouse.move(new_x, new_y)
                await asyncio.sleep(random.uniform(0.05, 0.15))
                
                current_x, current_y = new_x, new_y
                
        except Exception as e:
            logger.error("Random mouse wiggle failed", error=str(e))

class HumanMimicry:
    """Human-like behavior simulation"""
    
    @staticmethod
    async def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0):
        """Random delay between actions"""
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)
    
    @staticmethod
    async def gaussian_delay(mean: float = 1.0, std: float = 0.3) -> None:
        """Gaussian-distributed delay for more natural timing"""
        delay = max(0.1, random.gauss(mean, std))
        await asyncio.sleep(delay)
    
    @staticmethod
    async def element_specific_timing(page: Page, selector: str, action: str) -> None:
        """Element-specific timing based on type for more human-like behavior"""
        try:
            element_type = await page.evaluate(f"""
                () => {{
                    const el = document.querySelector('{selector}');
                    if (!el) return 'unknown';
                    
                    const tag = el.tagName.toLowerCase();
                    const role = el.getAttribute('role') || '';
                    const className = el.className || '';
                    
                    // Determine element type
                    if (tag === 'a' || role === 'link') return 'link';
                    if (tag === 'button' || role === 'button') return 'button';
                    if (tag === 'input' || tag === 'textarea' || role === 'textbox') return 'input';
                    if (tag === 'select' || role === 'combobox') return 'select';
                    if (className.includes('menu') || role === 'menu') return 'menu';
                    if (tag === 'img' || tag === 'video') return 'media';
                    
                    return tag;
                }}
            """)
            
            # Element-specific timing (in seconds)
            timing_config = {
                'link': (0.2, 0.1),      # Links click faster
                'button': (0.5, 0.2),    # Buttons take longer
                'input': (0.8, 0.3),     # Form fields take longest
                'select': (0.6, 0.2),    # Dropdowns moderate
                'menu': (0.4, 0.15),     # Menu items moderate
                'media': (0.3, 0.1),     # Media elements quick
                'unknown': (0.5, 0.2)    # Default timing
            }
            
            mean_delay, std_delay = timing_config.get(element_type, (0.5, 0.2))
            await HumanMimicry.gaussian_delay(mean_delay, std_delay)
            
            logger.debug("Element-specific timing applied", 
                        selector=selector, element_type=element_type, 
                        mean_delay=mean_delay, std_delay=std_delay)
            
        except Exception as e:
            logger.warning("Element-specific timing failed, using default", 
                          selector=selector, error=str(e))
            await HumanMimicry.gaussian_delay(0.5, 0.2)
    
    @staticmethod
    async def simulate_reading_behavior_enhanced(page: Page, content_length: Optional[int] = None) -> None:
        """Enhanced reading simulation based on content length"""
        try:
            if content_length is None:
                content = await page.inner_text('body')
                content_length = len(content.split())
            
            # Reading time: ~50 words per 2 seconds (human reading speed)
            base_reading_time = (content_length / 50) * 2
            reading_time = max(1.0, base_reading_time)
            
            # Add some randomness (20% variation)
            actual_time = random.gauss(reading_time, reading_time * 0.2)
            actual_time = max(0.5, actual_time)  # Minimum 0.5 seconds
            
            await asyncio.sleep(actual_time)
            
            logger.debug("Enhanced reading simulation", 
                        content_length=content_length, 
                        reading_time=actual_time)
            
        except Exception as e:
            logger.warning("Enhanced reading simulation failed", error=str(e))
            await HumanMimicry.gaussian_delay(1.0, 0.3)
    
    @staticmethod
    async def human_typing(page: Page, selector: str, text: str, typing_speed: float = 0.1):
        """Simulate human typing with random delays"""
        element = page.locator(selector)
        await element.click()
        await HumanMimicry.random_delay(0.1, 0.3)
        
        for char in text:
            await element.type(char)
            await asyncio.sleep(random.uniform(typing_speed * 0.5, typing_speed * 1.5))
    
    @staticmethod
    async def human_scroll(page: Page, direction: str = "down", distance: int = 300):
        """Simulate human-like scrolling"""
        if direction == "down":
            await page.mouse.wheel(0, distance)
        elif direction == "up":
            await page.mouse.wheel(0, -distance)
        
        await HumanMimicry.random_delay(0.5, 1.5)
    
    @staticmethod
    async def random_mouse_movement(page: Page):
        """Simulate random mouse movements"""
        viewport = page.viewport_size
        if not viewport:
            return
        
        # Random mouse movements
        for _ in range(random.randint(2, 5)):
            x = random.randint(0, viewport["width"])
            y = random.randint(0, viewport["height"])
            await page.mouse.move(x, y)
            await HumanMimicry.random_delay(0.1, 0.3)
    
    @staticmethod
    async def simulate_reading_behavior(page: Page, scroll_pauses: int = 3):
        """Simulate human reading behavior with scrolls and pauses"""
        # Random mouse movement
        await HumanMimicry.random_mouse_movement(page)
        
        # Scroll down with pauses
        for _ in range(scroll_pauses):
            await HumanMimicry.human_scroll(page, "down", random.randint(200, 500))
            await HumanMimicry.random_delay(1.0, 3.0)  # Reading pause
        
        # Sometimes scroll back up a bit
        if random.random() < 0.3:
            await HumanMimicry.human_scroll(page, "up", random.randint(100, 300))
            await HumanMimicry.random_delay(0.5, 1.5)

class FingerprintMasker:
    """Advanced browser fingerprint masking"""
    
    @staticmethod
    async def mask_fingerprint(page: Page, device_info: Dict[str, Any]):
        """Apply comprehensive fingerprint masking"""
        # Override navigator properties
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            
            Object.defineProperty(navigator, 'platform', {
                get: () => '""" + device_info.get("platform", "Win32") + """',
            });
            
            // Override screen properties
            Object.defineProperty(screen, 'width', {
                get: () => 1920,
            });
            
            Object.defineProperty(screen, 'height', {
                get: () => 1080,
            });
            
            Object.defineProperty(screen, 'availWidth', {
                get: () => 1920,
            });
            
            Object.defineProperty(screen, 'availHeight', {
                get: () => 1040,
            });
            
            // Override timezone
            Object.defineProperty(Intl.DateTimeFormat.prototype, 'resolvedOptions', {
                value: function() {
                    return { timeZone: 'America/New_York' };
                }
            });
            
            // Override canvas fingerprinting
            const getContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(type) {
                if (type === '2d') {
                    const context = getContext.call(this, type);
                    const originalFillText = context.fillText;
                    context.fillText = function(text, x, y, maxWidth) {
                        const noise = Math.random() * 0.1;
                        return originalFillText.call(this, text, x + noise, y + noise, maxWidth);
                    };
                    return context;
                }
                return getContext.call(this, type);
            };
        """)
    
    @staticmethod
    async def set_realistic_headers(page: Page, user_agent: str):
        """Set realistic HTTP headers"""
        await page.set_extra_http_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })

class SmartWaiter:
    """Intelligent waiting strategies for dynamic content"""
    
    @staticmethod
    async def wait_for_content_load(page: Page, timeout: int = 30000) -> bool:
        """Wait for page content to fully load with multiple strategies"""
        try:
            # Strategy 1: Wait for network idle
            await page.wait_for_load_state("networkidle", timeout=timeout)
            
            # Strategy 2: Wait for common content indicators
            content_selectors = [
                "main", "article", ".content", "#content", 
                ".post-content", "body", "[role='main']"
            ]
            
            for selector in content_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    break
                except:
                    continue
            
            # Strategy 3: Wait for images to load
            try:
                await page.wait_for_function("""
                    () => {
                        const images = document.querySelectorAll('img');
                        return Array.from(images).every(img => img.complete);
                    }
                """, timeout=10000)
            except:
                pass  # Images not critical
            
            # Strategy 4: Wait for no new network requests
            await page.wait_for_function("""
                () => {
                    return window.performance.getEntriesByType('navigation')[0].loadEventEnd > 0;
                }
            """, timeout=5000)
            
            return True
            
        except Exception as e:
            logger.warning("Content load wait failed", error=str(e))
            return False
    
    @staticmethod
    async def wait_for_dynamic_content(page: Page, selector: str, timeout: int = 15000) -> bool:
        """Wait for specific dynamic content to appear"""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            
            # Additional wait for content to be populated
            await page.wait_for_function(f"""
                () => {{
                    const element = document.querySelector('{selector}');
                    return element && element.textContent.trim().length > 10;
                }}
            """, timeout=5000)
            
            return True
        except Exception as e:
            logger.warning("Dynamic content wait failed", selector=selector, error=str(e))
            return False

class CAPTCHADetector:
    """CAPTCHA detection and handling"""
    
    CAPTCHA_INDICATORS = [
        "captcha", "recaptcha", "hcaptcha", "cloudflare",
        "challenge", "verify", "robot", "bot detection",
        "access denied", "blocked", "forbidden"
    ]
    
    @staticmethod
    async def detect_captcha(page: Page) -> Tuple[bool, str]:
        """Detect if page contains CAPTCHA or blocking"""
        try:
            # Check page title
            title = await page.title()
            title_lower = title.lower()
            
            for indicator in CAPTCHADetector.CAPTCHA_INDICATORS:
                if indicator in title_lower:
                    return True, f"CAPTCHA detected in title: {indicator}"
            
            # Check page content
            content = await page.content()
            content_lower = content.lower()
            
            for indicator in CAPTCHADetector.CAPTCHA_INDICATORS:
                if indicator in content_lower:
                    return True, f"CAPTCHA detected in content: {indicator}"
            
            # Check for common CAPTCHA elements
            captcha_selectors = [
                "[data-sitekey]", ".g-recaptcha", ".h-captcha",
                "#captcha", ".captcha", "[id*='captcha']",
                "[class*='captcha']", "[id*='recaptcha']"
            ]
            
            for selector in captcha_selectors:
                if await page.locator(selector).count() > 0:
                    return True, f"CAPTCHA element found: {selector}"
            
            return False, "No CAPTCHA detected"
            
        except Exception as e:
            logger.error("CAPTCHA detection failed", error=str(e))
            return False, f"Detection error: {str(e)}"
    
    @staticmethod
    async def handle_captcha_detection(page: Page) -> Dict[str, Any]:
        """Handle CAPTCHA detection with smart backoff"""
        is_captcha, reason = await CAPTCHADetector.detect_captcha(page)
        
        if is_captcha:
            logger.warning("CAPTCHA detected", reason=reason)
            
            # Take screenshot for analysis
            screenshot_path = f"TEST/captcha_detected_{int(time.time())}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            
            return {
                "detected": True,
                "reason": reason,
                "screenshot": screenshot_path,
                "backoff_time": random.randint(300, 600),  # 5-10 minutes
                "action": "backoff"
            }
        
        return {
            "detected": False,
            "reason": reason,
            "action": "continue"
        }

# Global instances
user_agent_pool = UserAgentPool()
proxy_rotator = None  # Will be initialized with actual proxies
adaptive_rate_limiter = AdaptiveRateLimiter()

def initialize_proxy_rotator(proxies: List[Dict[str, Any]]):
    """Initialize proxy rotator with proxy configurations"""
    global proxy_rotator
    proxy_configs = [ProxyConfig(**proxy) for proxy in proxies]
    proxy_rotator = ProxyRotator(proxy_configs)
    logger.info("Proxy rotator initialized", proxy_count=len(proxy_configs))

def get_enhanced_stealth_config() -> Dict[str, Any]:
    """Get enhanced stealth configuration"""
    user_agent, device_info = user_agent_pool.get_user_agent_with_device_info()
    
    return {
        "user_agent": user_agent,
        "device_info": device_info,
        "viewport": {
            "width": 1920,
            "height": 1080
        },
        "stealth": True,
        "java_script_enabled": True,
        "ignore_https_errors": True,
        "block_resources": [],  # Don't block resources for better stealth
        "timeout": 60000
    }

"""Enhanced stealth utilities for browser automation"""
import random
from typing import Dict, Any, List
from playwright.async_api import Page
from .anti_detection import user_agent_pool, FingerprintMasker, HumanMimicry
import structlog

logger = structlog.get_logger()

def get_random_headers(referer: str = None) -> Dict[str, str]:
    """Get random realistic headers using enhanced user agent pool"""
    user_agent, _ = user_agent_pool.get_user_agent_with_device_info()
    
    # Base headers that most browsers send
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    
    # Add referer if provided
    if referer:
        headers["Referer"] = referer
    
    # Randomly add DNT header (not all users have it enabled)
    if random.random() > 0.3:
        headers["DNT"] = "1"
    
    # Randomly add Cache-Control (humans don't always send this)
    if random.random() > 0.7:
        headers["Cache-Control"] = "max-age=0"
    
    # Randomly add additional headers for more realism
    if random.random() > 0.5:
        headers["Sec-Ch-Ua"] = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
        headers["Sec-Ch-Ua-Mobile"] = "?0"
        headers["Sec-Ch-Ua-Platform"] = '"Windows"'
    
    return headers

def get_realistic_headers(referer: str = None) -> Dict[str, str]:
    """Get more realistic headers with human-like variations"""
    user_agent, device_info = user_agent_pool.get_user_agent_with_device_info()
    
    # Base headers
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0"
    }
    
    # Add referer if provided
    if referer:
        headers["Referer"] = referer
    
    # Randomly omit some headers (humans don't always send all)
    if random.random() > 0.7:
        headers.pop("Cache-Control", None)
    
    # Add platform-specific headers
    if device_info.get("platform") == "Windows":
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "none"
        headers["Sec-Fetch-User"] = "?1"
    elif device_info.get("platform") == "macOS":
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "none"
    
    return headers

async def setup_stealth_mode(page: Page, device_info: Dict[str, Any] = None) -> None:
    """Setup enhanced stealth mode for the page with device-specific fingerprinting"""
    
    try:
        # Get device-specific configuration
        if not device_info:
            _, device_info = user_agent_pool.get_user_agent_with_device_info()
        
        # Apply comprehensive fingerprint masking
        await FingerprintMasker.mask_fingerprint(page, device_info)
        
        # Set realistic headers
        user_agent, _ = user_agent_pool.get_user_agent_with_device_info()
        await FingerprintMasker.set_realistic_headers(page, user_agent)
        
        # Additional stealth measures
        await page.add_init_script("""
            // Override webdriver detection
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // Override automation indicators
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            
            // Override Chrome runtime
            if (window.chrome && window.chrome.runtime) {
                delete window.chrome.runtime.onConnect;
                delete window.chrome.runtime.onMessage;
            }
            
            // Override permission API
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            
            // Override battery API
            Object.defineProperty(navigator, 'getBattery', {
                get: () => () => Promise.resolve({
                    charging: true,
                    chargingTime: 0,
                    dischargingTime: Infinity,
                    level: 1
                })
            });
            
            // Override connection API
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10
                })
            });
            
            // Override media devices
            Object.defineProperty(navigator, 'mediaDevices', {
                get: () => ({
                    enumerateDevices: () => Promise.resolve([]),
                    getUserMedia: () => Promise.reject(new Error('Permission denied'))
                })
            });
            
            // Override geolocation
            Object.defineProperty(navigator, 'geolocation', {
                get: () => ({
                    getCurrentPosition: () => Promise.reject(new Error('Permission denied')),
                    watchPosition: () => Promise.reject(new Error('Permission denied')),
                    clearWatch: () => {}
                })
            });
            
            // Override WebGL fingerprinting
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) {
                    return 'Intel Inc.';
                }
                if (parameter === 37446) {
                    return 'Intel(R) Iris(TM) Graphics 6100';
                }
                return getParameter(parameter);
            };
            
            // Override audio context fingerprinting
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                const originalCreateAnalyser = AudioContext.prototype.createAnalyser;
                AudioContext.prototype.createAnalyser = function() {
                    const analyser = originalCreateAnalyser.call(this);
                    const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
                    analyser.getFloatFrequencyData = function(array) {
                        originalGetFloatFrequencyData.call(this, array);
                        for (let i = 0; i < array.length; i++) {
                            array[i] += Math.random() * 0.0001;
                        }
                    };
                    return analyser;
                };
            }
        """)
        
        logger.debug("Enhanced stealth mode configured successfully")
        
    except Exception as e:
        logger.error("Failed to setup stealth mode", error=str(e))

async def simulate_human_behavior(page: Page) -> None:
    """Simulate human-like browsing behavior"""
    try:
        # Random mouse movements
        await HumanMimicry.random_mouse_movement(page)
        
        # Random delays
        await HumanMimicry.random_delay(1.0, 3.0)
        
        # Simulate reading behavior
        await HumanMimicry.simulate_reading_behavior(page, scroll_pauses=random.randint(2, 4))
        
        logger.debug("Human behavior simulation completed")
        
    except Exception as e:
        logger.error("Failed to simulate human behavior", error=str(e))

def get_random_user_agent() -> str:
    """Get random user agent from enhanced pool"""
    return user_agent_pool.get_random_user_agent()

def get_random_viewport() -> Dict[str, int]:
    """Get random viewport size"""
    viewports = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1440, "height": 900},
        {"width": 1536, "height": 864},
        {"width": 1280, "height": 720},
        {"width": 1600, "height": 900},
        {"width": 1024, "height": 768}
    ]
    
    return random.choice(viewports)

async def enhance_stealth_mode(page: Page) -> None:
    """Legacy enhanced stealth mode - now uses new system"""
    await setup_stealth_mode(page)
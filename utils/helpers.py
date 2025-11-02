"""Helper utilities for Surf Browser Service"""
import asyncio
import random
import time
import os
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()


def get_random_user_agent() -> str:
    """Get random user agent for browser diversity"""
    return random.choice(settings.user_agents)


async def random_delay(min_ms: int = 50, max_ms: int = 200) -> None:
    """Add random delay to simulate human behavior"""
    delay = random.uniform(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)


async def safe_click_with_retry(page, selector: str, max_retries: int = 3) -> bool:
    """Click element with retry logic for flaky elements"""
    
    for attempt in range(max_retries):
        try:
            element = page.locator(selector)
            await element.wait_for(state="visible", timeout=5000)
            await element.click()
            return True
            
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error("Click failed after retries", selector=selector, error=str(e))
                raise e
            
            logger.warning("Click attempt failed, retrying", attempt=attempt + 1, selector=selector)
            await asyncio.sleep(1)  # Wait before retry
    
    return False


async def wait_for_network_idle(page, timeout: int = 30000) -> None:
    """Wait for network to be idle (no requests for 500ms)"""
    
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception as e:
        logger.warning("Network idle timeout", error=str(e))


def calculate_file_size(file_path: str) -> int:
    """Calculate file size in bytes"""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format"""
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def validate_url_format(url: str) -> bool:
    """Validate URL format"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    
    return filename


def generate_safe_path(base_dir: str, filename: str) -> str:
    """Generate safe file path"""
    safe_filename = sanitize_filename(filename)
    return os.path.join(base_dir, safe_filename)


def get_timestamp() -> str:
    """Get current timestamp as string"""
    return str(int(time.time()))


def create_directory_if_not_exists(directory: str) -> None:
    """Create directory if it doesn't exist"""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create directory", directory=directory, error=str(e))
        raise


def cleanup_old_files(directory: str, max_age_hours: int = 24) -> int:
    """Clean up old files from directory"""
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0
    
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    os.remove(file_path)
                    cleaned_count += 1
        
        logger.info("File cleanup completed", directory=directory, cleaned_count=cleaned_count)
        
    except OSError as e:
        logger.error("File cleanup failed", directory=directory, error=str(e))
    
    return cleaned_count


def get_memory_usage() -> Dict[str, Any]:
    """Get current memory usage information"""
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            "rss": memory_info.rss,  # Resident Set Size
            "vms": memory_info.vms,  # Virtual Memory Size
            "percent": process.memory_percent(),
            "available": psutil.virtual_memory().available
        }
    except ImportError:
        return {"error": "psutil not available"}
    except Exception as e:
        return {"error": str(e)}


def format_bytes(bytes_value: int) -> str:
    """Format bytes in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def retry_async(max_retries: int = 3, delay: float = 1.0):
    """Decorator for retrying async functions"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            "Function failed, retrying",
                            function=func.__name__,
                            attempt=attempt + 1,
                            error=str(e)
                        )
                        await asyncio.sleep(delay * (2 ** attempt))  # Exponential backoff
                    else:
                        logger.error(
                            "Function failed after all retries",
                            function=func.__name__,
                            attempts=max_retries,
                            error=str(e)
                        )
            
            raise last_exception
        
        return wrapper
    return decorator

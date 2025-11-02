"""
Content Processing and Cleaning Utilities
Handles content extraction, cleaning, normalization, and quality assessment
"""

import re
import asyncio
import hashlib
import time
from typing import Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass
from playwright.async_api import Page
import structlog

logger = structlog.get_logger()


@dataclass
class ContentMetrics:
    """Content quality metrics"""
    word_count: int
    line_count: int
    character_count: int
    content_quality_score: float
    has_meaningful_content: bool


class ContentProcessor:
    """Advanced content processing and cleaning utilities"""
    
    @staticmethod
    async def extract_smart_content(page: Page, selector: str = 'body') -> str:
        """
        Extract content using Playwright's smart methods with fallback strategies
        
        Args:
            page: Playwright page object
            selector: CSS selector for content extraction
            
        Returns:
            Cleaned text content
        """
        try:
            # Use innerText for visible text only (excludes hidden elements)
            content = await page.inner_text(selector) or ""
            
            # If innerText is too short, fallback to textContent for more content
            if len(content.strip()) < 100:
                content = await page.text_content(selector) or ""
            
            # Clean the extracted content
            cleaned_content = await ContentProcessor.clean_content_with_js(page, content)
            
            return cleaned_content
            
        except Exception as e:
            logger.error("Content extraction failed", error=str(e))
            return ""
    
    @staticmethod
    async def clean_content_with_js(page: Page, content: str) -> str:
        """
        Clean content using JavaScript evaluation for advanced processing
        
        Args:
            page: Playwright page object
            content: Raw content to clean
            
        Returns:
            Cleaned content
        """
        if not content:
            return ""
        
        try:
            # Use Playwright to evaluate JavaScript for advanced content cleaning
            cleaned_content = await page.evaluate("""
                (content) => {
                    // Remove extra whitespace and normalize
                    let text = content;
                    
                    // Remove excessive whitespace
                    text = text.replace(/\\s+/g, ' ');
                    
                    // Remove common navigation and UI elements
                    text = text.replace(/\\b(Home|Login|Sign Up|Menu|Search|More|Categories|Topics|Latest|Hot)\\b/gi, '');
                    
                    // Remove common footer/header text
                    text = text.replace(/\\b(©|Copyright|All rights reserved|Privacy Policy|Terms of Service)\\b.*$/gmi, '');
                    
                    // Remove excessive punctuation
                    text = text.replace(/\\.{3,}/g, '...');
                    text = text.replace(/\\s+([.!?])/g, '$1');
                    
                    // Remove empty lines and normalize
                    text = text.split('\\n')
                        .map(line => line.trim())
                        .filter(line => line.length > 0)
                        .join('\\n');
                    
                    return text.trim();
                }
            """, content)
            
            return cleaned_content or content
            
        except Exception as e:
            logger.debug("JavaScript content cleaning failed, using basic cleaning", error=str(e))
            return ContentProcessor.clean_content_basic(content)
    
    @staticmethod
    def clean_content_basic(content: str) -> str:
        """
        Basic content cleaning using regex patterns
        
        Args:
            content: Raw content to clean
            
        Returns:
            Cleaned content
        """
        if not content:
            return ""
        
        # Remove excessive whitespace
        content = re.sub(r'\s+', ' ', content)
        
        # Remove common navigation elements
        nav_patterns = [
            r'\b(Home|Login|Sign Up|Menu|Search|More|Categories|Topics|Latest|Hot)\b',
            r'\b(©|Copyright|All rights reserved|Privacy Policy|Terms of Service)\b.*$',
        ]
        
        for pattern in nav_patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove excessive punctuation
        content = re.sub(r'\.{3,}', '...', content)
        content = re.sub(r'\s+([.!?])', r'\1', content)
        
        # Remove empty lines and normalize
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        content = '\n'.join(lines)
        
        return content.strip()
    
    @staticmethod
    def assess_content_quality(content: str) -> ContentMetrics:
        """
        Assess content quality and extract metrics
        
        Args:
            content: Content to assess
            
        Returns:
            ContentMetrics object with quality assessment
        """
        if not content:
            return ContentMetrics(0, 0, 0, 0.0, False)
        
        # Basic metrics
        word_count = len(content.split())
        line_count = len(content.split('\n'))
        character_count = len(content)
        
        # Quality assessment
        quality_score = 0.0
        
        # Length-based scoring
        if character_count > 500:
            quality_score += 0.3
        elif character_count > 100:
            quality_score += 0.1
        
        # Word density scoring
        if word_count > 50:
            quality_score += 0.2
        elif word_count > 10:
            quality_score += 0.1
        
        # Content diversity scoring
        unique_words = len(set(content.lower().split()))
        if unique_words > 20:
            quality_score += 0.2
        elif unique_words > 5:
            quality_score += 0.1
        
        # Meaningful content indicators
        meaningful_patterns = [
            r'\b(article|news|report|analysis|study|research|data|information)\b',
            r'\b(company|business|market|stock|investment|finance)\b',
            r'\b(price|value|growth|revenue|profit|earnings)\b',
        ]
        
        meaningful_count = sum(
            len(re.findall(pattern, content, re.IGNORECASE))
            for pattern in meaningful_patterns
        )
        
        if meaningful_count > 0:
            quality_score += 0.3
        
        # Cap quality score at 1.0
        quality_score = min(quality_score, 1.0)
        
        # Determine if content is meaningful
        has_meaningful_content = (
            character_count > 100 and 
            word_count > 10 and 
            quality_score > 0.3
        )
        
        return ContentMetrics(
            word_count=word_count,
            line_count=line_count,
            character_count=character_count,
            content_quality_score=quality_score,
            has_meaningful_content=has_meaningful_content
        )
    
    @staticmethod
    async def detect_captcha_content(page: Page, content: str) -> Tuple[bool, str]:
        """
        Detect CAPTCHA content using multiple strategies
        
        Args:
            page: Playwright page object
            content: Extracted content
            
        Returns:
            Tuple of (is_captcha, reason)
        """
        try:
            # Content-based detection (primary method)
            content_metrics = ContentProcessor.assess_content_quality(content)
            
            # Very low content length (likely CAPTCHA page or useless content)
            if content_metrics.character_count < 500:
                return True, f"Insufficient content length: {content_metrics.character_count} chars"
            
            # Check for specific CAPTCHA patterns only if content is suspiciously low
            if content_metrics.character_count < 1000:
                captcha_patterns = [
                    'recaptcha', 'hcaptcha', 'cloudflare',
                    'prove you are human', 'i am not a robot',
                    'verify you are human', 'security challenge',
                    'anti-bot', 'bot detection', 'access denied',
                    'please complete the security check'
                ]
                
                content_lower = content.lower()
                captcha_pattern_found = any(
                    pattern.lower() in content_lower 
                    for pattern in captcha_patterns
                )
                
                if captcha_pattern_found:
                    return True, f"CAPTCHA pattern found in low-content page"
            
            # Check for CAPTCHA-specific DOM elements
            captcha_elements = [
                'iframe[src*="recaptcha"]',
                'iframe[src*="hcaptcha"]', 
                'div[class*="captcha"]',
                'div[id*="captcha"]',
                'div[class*="recaptcha"]',
                'div[id*="recaptcha"]',
                'div[class*="hcaptcha"]',
                'div[id*="hcaptcha"]',
                'div[class*="cloudflare"]',
                'div[id*="cloudflare"]'
            ]
            
            for selector in captcha_elements:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        return True, f"CAPTCHA element found: {selector}"
                except:
                    continue
            
            return False, "No CAPTCHA detected"
            
        except Exception as e:
            logger.error("CAPTCHA detection failed", error=str(e))
            return False, f"Detection error: {str(e)}"
    
    @staticmethod
    def extract_structured_data(content: str, content_type: str = "general") -> Dict[str, Any]:
        """
        Extract structured data from content based on type
        
        Args:
            content: Content to process
            content_type: Type of content (general, forum, news, financial)
            
        Returns:
            Dictionary with structured data
        """
        if not content:
            return {}
        
        structured_data = {
            "raw_content": content,
            "content_type": content_type,
            "metrics": ContentProcessor.assess_content_quality(content).__dict__,
            "extracted_elements": {}
        }
        
        # Extract based on content type
        if content_type == "forum":
            structured_data["extracted_elements"] = ContentProcessor._extract_forum_elements(content)
        elif content_type == "news":
            structured_data["extracted_elements"] = ContentProcessor._extract_news_elements(content)
        elif content_type == "financial":
            structured_data["extracted_elements"] = ContentProcessor._extract_financial_elements(content)
        
        return structured_data
    
    @staticmethod
    def _extract_forum_elements(content: str) -> Dict[str, Any]:
        """Extract forum-specific elements"""
        elements = {
            "topics": [],
            "posts": [],
            "users": [],
            "categories": []
        }
        
        # Extract topic titles (simple pattern matching)
        topic_pattern = r'^([A-Z][^\\n]+)$'
        topics = re.findall(topic_pattern, content, re.MULTILINE)
        elements["topics"] = [topic.strip() for topic in topics if len(topic.strip()) > 10]
        
        # Extract user mentions
        user_pattern = r'@([a-zA-Z0-9_]+)'
        users = re.findall(user_pattern, content)
        elements["users"] = list(set(users))
        
        return elements
    
    @staticmethod
    def _extract_news_elements(content: str) -> Dict[str, Any]:
        """Extract news-specific elements"""
        elements = {
            "headlines": [],
            "dates": [],
            "authors": [],
            "keywords": []
        }
        
        # Extract potential headlines (lines that look like titles)
        lines = content.split('\n')
        headlines = [line.strip() for line in lines 
                    if len(line.strip()) > 20 and len(line.strip()) < 200 
                    and not line.strip().startswith(('http', 'www', '©', 'Copyright'))]
        elements["headlines"] = headlines[:10]  # Limit to 10
        
        # Extract dates
        date_pattern = r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\w+ \d{1,2}, \d{4}\b'
        dates = re.findall(date_pattern, content)
        elements["dates"] = list(set(dates))
        
        return elements
    
    @staticmethod
    def _extract_financial_elements(content: str) -> Dict[str, Any]:
        """Extract financial-specific elements"""
        elements = {
            "stock_symbols": [],
            "prices": [],
            "percentages": [],
            "financial_terms": []
        }
        
        # Extract stock symbols (basic pattern)
        symbol_pattern = r'\b[A-Z]{2,5}\b'
        symbols = re.findall(symbol_pattern, content)
        elements["stock_symbols"] = list(set(symbols))
        
        # Extract prices
        price_pattern = r'\$\d+\.?\d*|\d+\.?\d*\s*(?:USD|INR|Rs)'
        prices = re.findall(price_pattern, content)
        elements["prices"] = list(set(prices))
        
        # Extract percentages
        percentage_pattern = r'\d+\.?\d*%'
        percentages = re.findall(percentage_pattern, content)
        elements["percentages"] = list(set(percentages))
        
        return elements

class ContentDeduplicator:
    """Content deduplication system to avoid processing duplicate content"""
    
    def __init__(self, ttl: int = 3600):  # 1 hour TTL
        self.content_hashes: Dict[str, float] = {}
        self.ttl = ttl
    
    def generate_content_hash(self, content: str) -> str:
        """Generate a hash for content deduplication"""
        # Normalize content before hashing
        normalized = re.sub(r'\s+', ' ', content.strip().lower())
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def is_duplicate(self, content: str) -> bool:
        """Check if content is a duplicate"""
        content_hash = self.generate_content_hash(content)
        current_time = time.time()
        
        # Clean expired hashes
        self._clean_expired_hashes(current_time)
        
        if content_hash in self.content_hashes:
            return True
        
        # Add new hash
        self.content_hashes[content_hash] = current_time
        return False
    
    def _clean_expired_hashes(self, current_time: float) -> None:
        """Remove expired hashes"""
        expired_hashes = [
            hash_key for hash_key, timestamp in self.content_hashes.items()
            if current_time - timestamp > self.ttl
        ]
        for hash_key in expired_hashes:
            del self.content_hashes[hash_key]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics"""
        return {
            "total_hashes": len(self.content_hashes),
            "ttl": self.ttl
        }

class ContentTypeDetector:
    """Detect content type based on patterns and structure"""
    
    CONTENT_TYPE_PATTERNS = {
        "news": [
            r"\b(breaking|news|report|article|headline)\b",
            r"\b(published|updated|posted)\b",
            r"\b(journalist|reporter|correspondent)\b"
        ],
        "forum": [
            r"\b(post|thread|topic|discussion)\b",
            r"\b(reply|comment|user|member)\b",
            r"\b(forum|board|community)\b"
        ],
        "financial": [
            r"\b(stock|share|price|market|trading)\b",
            r"\b(earnings|revenue|profit|loss)\b",
            r"\b(investment|portfolio|dividend)\b"
        ],
        "ecommerce": [
            r"\b(price|buy|sell|product|shopping)\b",
            r"\b(cart|checkout|payment|shipping)\b",
            r"\b(review|rating|customer)\b"
        ],
        "blog": [
            r"\b(blog|post|author|published)\b",
            r"\b(opinion|thoughts|insights)\b",
            r"\b(categories|tags|archive)\b"
        ]
    }
    
    @staticmethod
    def detect_content_type(content: str) -> str:
        """Detect content type based on patterns"""
        if not content:
            return "unknown"
        
        content_lower = content.lower()
        type_scores = {}
        
        for content_type, patterns in ContentTypeDetector.CONTENT_TYPE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, content_lower))
                score += matches
            
            if score > 0:
                type_scores[content_type] = score
        
        if not type_scores:
            return "general"
        
        # Return the type with highest score
        return max(type_scores.items(), key=lambda x: x[1])[0]
    
    @staticmethod
    def get_content_confidence(content: str, detected_type: str) -> float:
        """Get confidence score for content type detection"""
        if detected_type == "unknown" or detected_type == "general":
            return 0.0
        
        patterns = ContentTypeDetector.CONTENT_TYPE_PATTERNS.get(detected_type, [])
        if not patterns:
            return 0.0
        
        content_lower = content.lower()
        total_matches = sum(len(re.findall(pattern, content_lower)) for pattern in patterns)
        
        # Normalize score based on content length
        content_length = len(content.split())
        if content_length == 0:
            return 0.0
        
        confidence = min(1.0, total_matches / (content_length / 100))
        return confidence

# Global instances
content_deduplicator = ContentDeduplicator()

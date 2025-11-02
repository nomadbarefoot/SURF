# SURF Browser Service - Advanced Web Automation Platform

A sophisticated browser automation service built with FastAPI and Playwright for the VoidOS MCP ecosystem. SURF provides enterprise-grade web scraping, content extraction, and browser automation capabilities with advanced anti-detection, intelligent content processing, and seamless MCP integration.

## 🎯 **System Overview**

SURF is a comprehensive browser automation platform that provides powerful web scraping and automation capabilities. Built on modern Python technologies and designed for the VoidOS MCP ecosystem, it provides:

- **Advanced Web Automation**: Sophisticated content extraction and interaction capabilities
- **Anti-Detection Features**: Stealth mechanisms and human behavior simulation
- **Enterprise-Grade Architecture**: Scalable, secure, and maintainable design
- **MCP Integration**: Seamless integration with the VoidOS MCP ecosystem
- **Smart Content Processing**: Rule-based content understanding and optimization

## 🏗️ **Architecture & Components**

### **Core Architecture**
```
┌─────────────────────────────────────────────────────────────────┐
│                    SURF BROWSER SERVICE                        │
├─────────────────────────────────────────────────────────────────┤
│  API Layer (FastAPI)                                          │
│  ├── Controllers: browser, session, auth, health              │
│  ├── Middleware: security, logging, rate limiting, CORS       │
│  ├── Authentication: JWT-based with scope permissions         │
│  └── Error Handling: comprehensive exception management       │
├─────────────────────────────────────────────────────────────────┤
│  Service Layer (Business Logic)                               │
│  ├── BrowserService: Core automation operations               │
│  ├── SessionService: Multi-session management                 │
│  ├── AuthService: User authentication & authorization         │
│  └── CacheService: Redis-based intelligent caching           │
├─────────────────────────────────────────────────────────────────┤
│  Intelligence Layer (Processing & Analysis)                   │
│  ├── ContentProcessor: Smart content extraction & cleaning    │
│  ├── SemanticChunker: Rule-based content chunking            │
│  ├── AntiDetection: Human behavior simulation                 │
│  └── SiteMemory: Pattern-based site optimization             │
├─────────────────────────────────────────────────────────────────┤
│  Browser Layer (Playwright Integration)                       │
│  ├── Multi-Browser Support: Chromium, Firefox, WebKit        │
│  ├── Stealth Configuration: Advanced fingerprint masking     │
│  ├── Proxy Management: Intelligent proxy rotation            │
│  └── Resource Optimization: Smart resource blocking          │
└─────────────────────────────────────────────────────────────────┘
```

### **Key Components**

#### **1. Browser Service (`services/browser_service.py`)**
- **Core Operations**: Navigation, content extraction, element interaction, screenshots
- **Smart Content Extraction**: Multi-strategy content extraction with fallbacks
- **Enhanced Processing**: Content deduplication, quality assessment, semantic chunking
- **Error Recovery**: Robust retry logic and graceful failure handling

#### **2. Anti-Detection System (`utils/anti_detection.py`)**
- **Human Behavior Simulation**: Realistic mouse movements, timing patterns, reading behavior
- **Proxy Management**: Intelligent proxy rotation with health monitoring
- **Fingerprint Masking**: Advanced browser fingerprint obfuscation
- **Adaptive Rate Limiting**: Rule-based rate limiting that adjusts based on success patterns

#### **3. Content Processing (`utils/content_processor.py`)**
- **Smart Extraction**: Playwright-powered content extraction with multiple fallback strategies
- **Content Cleaning**: Remove ads, navigation, and irrelevant content
- **Quality Assessment**: Rule-based content quality scoring and validation
- **CAPTCHA Detection**: Automatic CAPTCHA detection and handling

#### **4. Semantic Chunking (`utils/semantic_chunker.py`)**
- **Rule-Based Chunking**: Content-type aware chunking using regex patterns
- **Semantic Boundaries**: Chunk based on paragraph, sentence, and structural boundaries
- **Metadata Extraction**: Basic metadata for each content chunk
- **Confidence Scoring**: Simple confidence assessment for each chunk

#### **5. Site Memory System (`utils/site_memory.py`)**
- **Pattern Database**: DuckDB-based storage for site-specific patterns
- **Performance Tracking**: Success/failure patterns, timing optimization
- **Adaptive Strategies**: Site-specific optimization based on historical data
- **Pattern Recognition**: Identify successful extraction strategies per site

## 🚀 **Advanced Features**

### **Smart Content Processing**

#### **Content Understanding**
- **Content Type Detection**: Rule-based content type classification (news, forums, e-commerce, financial)
- **Quality Assessment**: Rule-based content quality scoring and relevance filtering
- **Structured Data Extraction**: Basic extraction of structured content patterns
- **CAPTCHA Detection**: Pattern-based CAPTCHA detection and handling strategies

#### **Adaptive Features**
- **Pattern Recognition**: Learn successful extraction patterns per site
- **Behavioral Simulation**: Human-like mouse movements and timing patterns
- **Strategy Selection**: Choose extraction strategies based on content type and site characteristics
- **Performance Tracking**: Monitor and optimize success rates through pattern analysis

### **Enterprise-Grade Security**

#### **Authentication & Authorization**
- **JWT Tokens**: Secure, stateless authentication with configurable expiration
- **Scope-Based Access**: Fine-grained permission system for different operation types
- **Request Validation**: Comprehensive input validation and sanitization
- **Security Headers**: Automatic security header injection

#### **Anti-Detection Mechanisms**
- **User Agent Rotation**: Dynamic user agent switching with realistic patterns
- **Fingerprint Masking**: Advanced browser fingerprint obfuscation
- **Human Behavior Simulation**: Realistic mouse movements, scrolling, and interaction patterns
- **Proxy Intelligence**: Smart proxy rotation with health monitoring and geographic distribution

### **Performance & Scalability**

#### **Resource Management**
- **Session Pooling**: Efficient browser session management with automatic cleanup
- **Memory Optimization**: Smart memory usage with automatic garbage collection
- **Resource Blocking**: Block unnecessary resources (images, fonts, stylesheets) for faster loading
- **Connection Pooling**: Reuse HTTP connections for improved performance

#### **Caching & Optimization**
- **Redis Integration**: Optional Redis-based caching for improved response times
- **Content Caching**: Cache extracted content and responses with TTL management
- **Session Persistence**: Optional session persistence across service restarts
- **Adaptive Caching**: Learn optimal caching strategies based on content patterns

## 📊 **API Reference**

### **Core Endpoints**

#### **Session Management**
```http
POST /sessions/create
GET /sessions/{session_id}
DELETE /sessions/{session_id}
GET /sessions
```

#### **Browser Operations**
```http
POST /browser/navigate          # Navigate to URL with intelligent waiting
POST /browser/extract           # Extract content with smart fallback strategies
POST /browser/interact          # Perform element interactions with human-like behavior
POST /browser/screenshot        # Capture screenshots with dynamic content waiting
POST /browser/batch            # Execute multiple operations in parallel or sequence
POST /browser/extract-structured # Extract structured data from page content
POST /browser/detect-captcha   # Detect CAPTCHA on current page
```

#### **Health & Monitoring**
```http
GET /health                    # Service health check
GET /health/metrics           # Detailed service metrics
GET /health/sessions          # Session statistics and performance
```

### **Request/Response Schemas**

#### **Navigation Request**
```json
{
  "session_id": "sess_1234567890",
  "url": "https://example.com",
  "wait_until": "networkidle",
  "timeout": 30000
}
```

#### **Content Extraction Request**
```json
{
  "session_id": "sess_1234567890",
  "extract_type": "text",
  "selector": "body",
  "timeout": 10000
}
```

#### **Enhanced Response Format**
```json
{
  "success": true,
  "data": {
    "raw_content": { /* extracted content */ },
  "extract_type": "text",
    "content_type": "news",
    "type_confidence": 0.85,
    "quality_metrics": {
      "word_count": 1250,
      "character_count": 7500,
      "quality_score": 0.92,
      "has_meaningful_content": true
    },
    "chunks": [
      {
        "content": "Article content...",
        "chunk_type": "paragraph",
        "confidence": 0.88,
        "metadata": { /* chunk metadata */ }
      }
    ],
    "is_duplicate": false,
    "chunk_summary": "3 paragraphs, 1 heading, 2 lists"
  }
}
```

## 🔧 **Configuration & Setup**

### **Environment Configuration**
```bash
# Server Configuration
SURF_HOST=0.0.0.0
SURF_PORT=8000
SURF_DEBUG=false
SURF_LOG_LEVEL=INFO

# Security
SURF_SECRET_KEY=your-secret-key-change-this
SURF_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Rate Limiting
SURF_RATE_LIMIT_REQUESTS=100
SURF_RATE_LIMIT_WINDOW=60

# Session Management
SURF_MAX_SESSIONS=20
SURF_SESSION_TTL=300

# Browser Configuration
SURF_HEADLESS=true
SURF_DEFAULT_TIMEOUT=30000
SURF_ENABLE_STEALTH=true

# Enhanced Features
SURF_ENABLE_ADAPTIVE_RATE_LIMITING=true
SURF_ENABLE_SITE_MEMORY=true
SURF_ENABLE_SEMANTIC_CHUNKING=true
SURF_ENABLE_CONTENT_DEDUPLICATION=true
SURF_ENABLE_ENHANCED_MOUSE_MOVEMENT=true

# Caching
SURF_ENABLE_CACHE=true
SURF_CACHE_TTL=300
SURF_REDIS_URL=redis://localhost:6379
```

### **Installation & Setup**

1. **Prerequisites**
```bash
   # Python 3.9+
   python --version
   
   # Node.js for Playwright
   node --version
   
   # Redis (optional)
   redis-server --version
   ```

2. **Installation**
```bash
   # Clone and navigate
   cd MCP/servers/surf
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Install Playwright browsers
   playwright install
   
   # Configure environment
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start Service**
   ```bash
   # Development mode
   python start_surf.py
   
   # Production mode
   python main.py
   ```

## 🧠 **Intelligence & Future Roadmap**

### **Current Smart Features**
- **Content Type Detection**: Rule-based classification of content types (news, forums, e-commerce, financial)
- **Semantic Chunking**: Pattern-based content segmentation using regex boundaries
- **Quality Assessment**: Rule-based content quality scoring and relevance filtering
- **Pattern Learning**: Site-specific pattern recognition and optimization

### **Planned Enhancements** (See `AI_ORCHESTRATOR_PLAN.md`)
- **Natural Language Interface**: Process natural language queries for web scraping tasks
- **Autonomous Operation**: Self-healing and adaptive scraping strategies
- **Advanced Learning**: Machine learning for continuous improvement
- **LLM Integration**: Full integration with VoidOS LLM manager for enhanced intelligence

### **Future Learning System Architecture**
```python
# Planned AI Agent Structure (Future Enhancement)
class SurfAIAgent:
    def __init__(self):
        self.llm_manager = ModelManager()  # VoidOS LLM integration
        self.pattern_learner = PatternLearner()
        self.strategy_selector = StrategySelector()
        self.tool_orchestrator = ToolOrchestrator()
    
    async def process_query(self, query: str) -> Dict:
        """Process natural language query and execute scraping task"""
        intent = await self._parse_query_intent(query)
        strategy = await self._select_strategy(intent)
        result = await self._execute_strategy(strategy)
        await self._learn_from_execution(intent, strategy, result)
        return result
```

## 🔄 **MCP Integration**

### **Tool Registration**
SURF automatically registers as an MCP server and exposes browser automation tools:

- **Browser Management**: Session creation, management, and cleanup
- **Navigation Tools**: URL navigation with various wait strategies
- **Content Extraction**: Text, HTML, table, link, and image extraction
- **Element Interaction**: Click, type, select, scroll, and hover operations
- **Screenshot Tools**: Full page and element screenshots
- **Batch Operations**: Execute multiple operations in parallel or sequence
- **Smart Tools**: Content analysis, structured data extraction, CAPTCHA detection

### **Cross-Service Communication**
- **Unified Configuration**: Uses MCP configuration system
- **Service Discovery**: Automatic discovery by other MCP services
- **Data Sharing**: Seamless data flow between MCP services
- **Event System**: Integration with MCP event system for real-time updates

## 📈 **Performance & Monitoring**

### **Metrics & Monitoring**
- **Response Times**: API response time monitoring with percentile analysis
- **Success Rates**: Operation success rate tracking with failure analysis
- **Resource Utilization**: Browser and system resource usage monitoring
- **Cache Performance**: Cache hit rates and performance optimization
- **Learning Metrics**: Pattern recognition accuracy and adaptive optimization effectiveness

### **Health Checks**
- **Service Health**: Overall service health and status
- **Session Health**: Active session monitoring and cleanup
- **Resource Health**: Memory, CPU, and network usage monitoring
- **Dependency Health**: Redis, Playwright, and external service health

### **Logging & Debugging**
- **Structured Logging**: JSON-formatted logs with full context
- **Request Tracing**: Complete request/response tracing with timing
- **Error Analysis**: Detailed error logging with stack traces and context
- **Performance Profiling**: Detailed performance metrics and bottleneck analysis

## 🛡️ **Security & Compliance**

### **Security Features**
- **Input Validation**: Comprehensive input validation and sanitization
- **Rate Limiting**: Per-IP rate limiting with adaptive algorithms
- **Request Size Limits**: Protection against large request attacks
- **CORS Protection**: Configurable CORS policies for cross-origin requests
- **Authentication**: JWT-based authentication with scope-based permissions

### **Privacy & Compliance**
- **Data Minimization**: Extract only necessary data
- **Anonymization**: Optional data anonymization features
- **Audit Logging**: Comprehensive audit trails for compliance
- **GDPR Compliance**: Built-in privacy controls and data handling

## 🧪 **Testing & Quality Assurance**

### **Test Coverage**
- **Unit Tests**: Individual component testing with 90%+ coverage
- **Integration Tests**: API endpoint testing with real browser scenarios
- **Browser Tests**: Playwright integration testing across multiple browsers
- **Performance Tests**: Load and stress testing with realistic scenarios
- **Pattern Tests**: Rule-based pattern recognition testing and validation

### **Quality Gates**
- **Code Quality**: Black, isort, flake8, and mypy enforcement
- **Security Scanning**: Automated security vulnerability scanning
- **Performance Benchmarks**: Automated performance regression testing
- **Documentation**: Comprehensive API documentation and examples

## 🚀 **Usage Examples**

### **Basic Web Scraping**
```python
import asyncio
import httpx

async def scrape_news_articles():
    async with httpx.AsyncClient() as client:
        # Create session
        session_response = await client.post(
            "http://localhost:8000/sessions/create",
            headers={"Authorization": "Bearer <token>"},
            json={"browser_type": "chromium", "headless": True}
        )
        session_id = session_response.json()["data"]["session_id"]
        
        # Navigate to news site
        await client.post(
            "http://localhost:8000/browser/navigate",
            headers={"Authorization": "Bearer <token>"},
            json={"session_id": session_id, "url": "https://news.example.com"}
        )
        
        # Extract articles
        articles = await client.post(
            "http://localhost:8000/browser/extract",
            headers={"Authorization": "Bearer <token>"},
            json={
                "session_id": session_id,
                "extract_type": "text",
                "selector": ".article"
            }
        )
        
        # Process with smart extraction
        structured_data = await client.post(
            "http://localhost:8000/browser/extract-structured",
            headers={"Authorization": "Bearer <token>"},
            json={
                "session_id": session_id,
                "content_type": "news",
                "selector": "body"
            }
        )
        
        return structured_data.json()["data"]

# Run the scraper
articles = asyncio.run(scrape_news_articles())
```

### **Advanced E-commerce Scraping**
```python
async def scrape_product_data():
    # Create session with enhanced stealth
    session = await create_session({
        "browser_type": "chromium",
        "headless": True,
        "stealth_mode": True,
        "proxy_rotation": True
    })
    
    # Navigate to product page
    await navigate(session.id, "https://shop.example.com/product/123")
    
    # Extract product information
    product_data = await extract_structured_data(
        session.id,
        content_type="ecommerce",
        selector=".product-details"
    )
    
    # Take screenshot for verification
    screenshot = await take_screenshot(
        session.id,
        selector=".product-image",
        path="product_123.png"
    )
    
    return product_data
```

### **Batch Operations**
```python
async def batch_scraping():
    # Define multiple operations
    operations = [
        {"type": "navigate", "url": "https://site1.com"},
        {"type": "extract", "extract_type": "text", "selector": "body"},
        {"type": "navigate", "url": "https://site2.com"},
        {"type": "extract", "extract_type": "links", "selector": "a"},
        {"type": "screenshot", "full_page": True}
    ]
    
    # Execute in parallel
    results = await batch_operations(
        operations=operations,
        session_id=session_id,
        parallel=True,
        max_concurrent=3
    )
    
    return results
```

## 🔧 **Troubleshooting & Support**

### **Common Issues**
1. **Browser Installation**: `playwright install --with-deps`
2. **Permission Issues**: Check file permissions and user access
3. **Port Conflicts**: Change port in configuration
4. **Memory Issues**: Reduce max sessions or enable resource monitoring
5. **Proxy Issues**: Verify proxy configuration and connectivity

### **Debug Mode**
```bash
# Enable detailed logging
SURF_DEBUG=true
SURF_LOG_LEVEL=DEBUG

# Check logs
tail -f logs/surf.log
tail -f logs/browser.log
```

### **Performance Tuning**
```bash
# Optimize for performance
SURF_MAX_SESSIONS=10
SURF_ENABLE_CACHE=true
SURF_BLOCK_RESOURCES=image,font,stylesheet
SURF_HEADLESS=true
```

## 📚 **Documentation & Resources**

- **API Documentation**: Available at `http://localhost:8000/docs` when running
- **Configuration Guide**: See `config/settings.py` for all available options
- **Upgrade Roadmap**: See `next_upgrades.md` for planned enhancements
- **Examples**: See `examples/` directory for usage examples

## 🤝 **Contributing**

### **Development Setup**
1. Fork the repository
2. Create a feature branch
3. Install development dependencies: `pip install -r requirements-dev.txt`
4. Run tests: `pytest`
5. Submit a pull request

### **Code Standards**
- **Formatting**: Black for code formatting
- **Imports**: isort for import organization
- **Linting**: flake8 for code quality
- **Types**: mypy for type checking
- **Testing**: pytest for comprehensive testing

## 📄 **License & Acknowledgments**

This project is licensed under the MIT License and is part of the VoidOS MCP ecosystem.

**Key Technologies:**
- **Playwright**: Browser automation framework
- **FastAPI**: Modern Python web framework
- **Pydantic**: Data validation and serialization
- **DuckDB**: High-performance analytical database
- **Redis**: In-memory data structure store
- **VoidOS MCP**: Microservice architecture platform

---

**Built with ❤️ for advanced web automation in the VoidOS ecosystem**

*SURF provides powerful web scraping capabilities with sophisticated anti-detection, smart content processing, and seamless MCP integration for maximum effectiveness and reliability.*

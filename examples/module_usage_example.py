"""
Example: How other modules would use SURF high-level tools
========================================================
This demonstrates the simple interface for module consumption
"""

import asyncio
import json
from typing import Dict, List, Any

# Example of how other modules would import and use SURF tools
class SurfModuleInterface:
    """Simple interface for other modules to use SURF tools"""
    
    def __init__(self):
        # In real implementation, this would connect to the MCP server
        self.surf_client = None  # Placeholder for MCP client
    
    async def extract_news(self, query: str, sources: List[str] = None, 
                          max_articles: int = 10, time_range: str = "1w") -> Dict:
        """Extract news articles - simple interface for modules"""
        # This would call the MCP server's extract_news tool
        params = {
            "query": query,
            "sources": sources,
            "max_articles": max_articles,
            "time_range": time_range
        }
        
        # Simulated response (in real implementation, this would be an MCP call)
        return {
            "articles": [
                {
                    "title": "AI Breakthrough in Web Scraping",
                    "content": "New AI-powered web scraping technology...",
                    "url": "https://example.com/ai-breakthrough",
                    "source": "cnn",
                    "timestamp": "2024-01-15T10:30:00Z",
                    "query_relevance": 0.95
                }
            ],
            "total_found": 1,
            "sources_used": sources or ["cnn", "bbc"],
            "query": query
        }
    
    async def extract_fundamentals(self, symbols: List[str], 
                                  data_types: List[str] = None) -> Dict:
        """Extract financial fundamental data - simple interface for modules"""
        params = {
            "symbols": symbols,
            "data_types": data_types or ["pe_ratio", "market_cap", "revenue"]
        }
        
        # Simulated response
        return {
            "fundamentals": {
                "AAPL": {
                    "pe_ratio": 25.5,
                    "market_cap": "3.0T",
                    "revenue": "394.3B",
                    "eps": "6.13"
                }
            },
            "symbols_processed": len(symbols),
            "sources_used": ["yahoo_finance", "marketwatch"]
        }
    
    async def extract_products(self, query: str, sites: List[str] = None,
                              max_products: int = 20, price_range: Dict = None) -> Dict:
        """Extract product data - simple interface for modules"""
        params = {
            "query": query,
            "sites": sites,
            "max_products": max_products,
            "price_range": price_range
        }
        
        # Simulated response
        return {
            "products": [
                {
                    "name": "MacBook Pro 16-inch",
                    "price": "$2,499.00",
                    "url": "https://amazon.com/macbook-pro",
                    "site": "amazon",
                    "image": "https://example.com/image.jpg",
                    "rating": "4.5",
                    "availability": "In Stock"
                }
            ],
            "total_found": 1,
            "sites_used": sites or ["amazon", "best_buy"],
            "query": query
        }

# Example usage in other modules
async def example_news_extraction():
    """Example: News extraction for a trading module"""
    surf = SurfModuleInterface()
    
    # Extract AI-related news
    news = await surf.extract_news(
        query="artificial intelligence stock market",
        sources=["cnn", "reuters"],
        max_articles=5,
        time_range="1w"
    )
    
    print("News Extraction Results:")
    print(f"Found {news['total_found']} articles")
    for article in news['articles']:
        print(f"- {article['title']} (Relevance: {article['query_relevance']:.2f})")
    
    return news

async def example_fundamental_analysis():
    """Example: Fundamental data extraction for analysis"""
    surf = SurfModuleInterface()
    
    # Extract fundamentals for tech stocks
    fundamentals = await surf.extract_fundamentals(
        symbols=["AAPL", "GOOGL", "MSFT"],
        data_types=["pe_ratio", "market_cap", "revenue", "eps"]
    )
    
    print("Fundamental Analysis Results:")
    for symbol, data in fundamentals['fundamentals'].items():
        print(f"{symbol}: PE={data.get('pe_ratio', 'N/A')}, "
              f"Market Cap={data.get('market_cap', 'N/A')}")
    
    return fundamentals

async def example_product_research():
    """Example: Product research for e-commerce analysis"""
    surf = SurfModuleInterface()
    
    # Extract laptop products
    products = await surf.extract_products(
        query="gaming laptop",
        sites=["amazon", "best_buy"],
        max_products=10,
        price_range={"min": 1000, "max": 3000}
    )
    
    print("Product Research Results:")
    print(f"Found {products['total_found']} products")
    for product in products['products']:
        print(f"- {product['name']} - {product['price']} ({product['site']})")
    
    return products

# Example of how the AI agent would use granular tools
class SurfAIAgent:
    """Example: AI agent using granular tools for orchestration"""
    
    def __init__(self):
        self.surf_client = None  # Placeholder for MCP client
    
    async def intelligent_scraping(self, query: str, requirements: Dict) -> Dict:
        """AI agent orchestrates multiple granular tools"""
        
        # Step 1: Analyze query and select strategy
        strategy = await self._analyze_query(query, requirements)
        
        # Step 2: Apply stealth mode based on target site
        await self._apply_stealth_mode(strategy['stealth_level'])
        
        # Step 3: Navigate to target URL
        navigation_result = await self._navigate_to_url(
            strategy['target_url'],
            wait_for=strategy['wait_selector']
        )
        
        # Step 4: Extract content using learned selectors
        content_result = await self._extract_content(
            selectors=strategy['selectors'],
            extract_type=strategy['content_type']
        )
        
        # Step 5: Interact with elements if needed
        if strategy['interactions']:
            for interaction in strategy['interactions']:
                await self._interact_with_element(
                    selector=interaction['selector'],
                    action=interaction['action'],
                    value=interaction.get('value', '')
                )
        
        # Step 6: Learn from this session
        await self._learn_patterns(
            pattern_type="behavioral",
            session_data={
                "query": query,
                "strategy": strategy,
                "success": navigation_result['success'],
                "performance": content_result['performance']
            }
        )
        
        return {
            "success": True,
            "content": content_result['content'],
            "strategy_used": strategy,
            "performance_metrics": content_result['performance']
        }
    
    async def _analyze_query(self, query: str, requirements: Dict) -> Dict:
        """Analyze query and select optimal strategy"""
        # This would use LLM to analyze the query
        # For now, return a mock strategy
        return {
            "target_url": "https://example.com/search?q=" + query,
            "stealth_level": "advanced",
            "wait_selector": ".search-results",
            "selectors": {
                "title": "h3.result-title",
                "content": ".result-snippet",
                "url": "a.result-link"
            },
            "content_type": "text",
            "interactions": []
        }
    
    async def _apply_stealth_mode(self, level: str):
        """Apply stealth mode"""
        # This would call the granular stealth tool
        pass
    
    async def _navigate_to_url(self, url: str, wait_for: str = None) -> Dict:
        """Navigate to URL"""
        # This would call the granular navigation tool
        return {"success": True, "url": url}
    
    async def _extract_content(self, selectors: Dict, extract_type: str) -> Dict:
        """Extract content using selectors"""
        # This would call the granular content extraction tool
        return {
            "content": [{"title": "Sample Title", "content": "Sample Content"}],
            "performance": {"extraction_time": 1.5, "elements_found": 1}
        }
    
    async def _interact_with_element(self, selector: str, action: str, value: str = ""):
        """Interact with page element"""
        # This would call the granular interaction tool
        pass
    
    async def _learn_patterns(self, pattern_type: str, session_data: Dict):
        """Learn patterns from session"""
        # This would call the granular learning tool
        pass

# Main example
async def main():
    """Run all examples"""
    print("=== SURF Module Usage Examples ===\n")
    
    # Example 1: News extraction
    print("1. News Extraction Example:")
    await example_news_extraction()
    print()
    
    # Example 2: Fundamental analysis
    print("2. Fundamental Analysis Example:")
    await example_fundamental_analysis()
    print()
    
    # Example 3: Product research
    print("3. Product Research Example:")
    await example_product_research()
    print()
    
    # Example 4: AI agent orchestration
    print("4. AI Agent Orchestration Example:")
    agent = SurfAIAgent()
    result = await agent.intelligent_scraping(
        query="latest AI news",
        requirements={"content_type": "news", "max_items": 10}
    )
    print(f"AI Agent Result: {result['success']}")
    print(f"Content extracted: {len(result['content'])} items")

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Start Surf Browser Service for testing
"""

import uvicorn
import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("🚀 Starting Surf Browser Service...")
    print("📍 URL: http://localhost:6660")
    print("📚 API Docs: http://localhost:6660/docs")
    print("🔍 Health Check: http://localhost:6660/health")
    print("=" * 50)
    
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=6660,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 Service stopped by user")
    except Exception as e:
        print(f"❌ Error starting service: {e}")
        sys.exit(1)

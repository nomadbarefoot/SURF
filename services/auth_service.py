"""Authentication service for Surf Browser Service"""
import hashlib
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import structlog

from config import get_settings, SecurityConfig
from core.foundation import AuthenticationError, ValidationError

logger = structlog.get_logger()
settings = get_settings()


class AuthService:
    """Authentication and authorization service"""
    
    def __init__(self):
        self.users: Dict[str, Dict[str, Any]] = {}
        self.api_keys: Dict[str, Dict[str, Any]] = {}
        self.initialized = False
    
    async def initialize(self) -> None:
        """Initialize authentication service"""
        # In a real implementation, you would load users and API keys from a database
        self.initialized = True
        logger.info("Authentication service initialized")
    
    async def cleanup(self) -> None:
        """Cleanup authentication service"""
        self.initialized = False
        logger.info("Authentication service cleaned up")
    
    async def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user with username and password"""
        
        if not self.initialized:
            raise AuthenticationError("Authentication service not initialized")
        
        # In a real implementation, you would:
        # 1. Hash the password
        # 2. Query the database for the user
        # 3. Compare password hashes
        
        # For demo purposes, accept any valid username/password
        if len(username) < 3 or len(password) < 8:
            return None
        
        # Generate user data
        user_data = {
            "username": username,
            "scopes": ["browser:read", "browser:write", "sessions:manage"],
            "created_at": datetime.utcnow(),
            "last_login": datetime.utcnow()
        }
        
        logger.info("User authenticated", username=username)
        return user_data
    
    async def create_access_token(self, user_data: Dict[str, Any]) -> str:
        """Create JWT access token for user"""
        
        token_data = {
            "sub": user_data["username"],
            "scopes": user_data.get("scopes", []),
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
        }
        
        return SecurityConfig.create_access_token(token_data)
    
    async def verify_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify JWT access token and return user data"""
        
        try:
            payload = SecurityConfig.verify_token(token)
            if payload is None:
                return None
            
            return {
                "username": payload.get("sub"),
                "scopes": payload.get("scopes", []),
                "exp": payload.get("exp")
            }
            
        except Exception as e:
            logger.error("Token verification failed", error=str(e))
            return None
    
    async def create_api_key(
        self, 
        name: str, 
        scopes: List[str], 
        user_id: str,
        expires_in_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create API key for programmatic access"""
        
        if not self.initialized:
            raise AuthenticationError("Authentication service not initialized")
        
        # Validate scopes
        if not self._validate_scopes(scopes):
            raise ValidationError("scopes", "Invalid scopes provided")
        
        # Generate API key
        api_key = SecurityConfig.generate_api_key()
        key_id = f"key_{api_key[:8]}"
        
        # Calculate expiration
        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        # Store API key data
        api_key_data = {
            "key_id": key_id,
            "hashed_key": SecurityConfig.hash_api_key(api_key),
            "name": name,
            "scopes": scopes,
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "expires_at": expires_at,
            "is_active": True
        }
        
        self.api_keys[key_id] = api_key_data
        
        logger.info("API key created", key_id=key_id, user_id=user_id, scopes=scopes)
        
        return {
            "api_key": api_key,
            "key_id": key_id,
            "scopes": scopes,
            "expires_at": expires_at
        }
    
    async def verify_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Verify API key and return associated data"""
        
        if not self.initialized:
            raise AuthenticationError("Authentication service not initialized")
        
        # Extract key ID from API key
        if not api_key.startswith("surf_"):
            return None
        
        key_id = f"key_{api_key[5:13]}"  # Extract 8 characters after "surf_"
        
        if key_id not in self.api_keys:
            return None
        
        api_key_data = self.api_keys[key_id]
        
        # Check if key is active
        if not api_key_data["is_active"]:
            return None
        
        # Check expiration
        if api_key_data["expires_at"] and datetime.utcnow() > api_key_data["expires_at"]:
            return None
        
        # Verify key hash
        if api_key_data["hashed_key"] != SecurityConfig.hash_api_key(api_key):
            return None
        
        return {
            "key_id": key_id,
            "user_id": api_key_data["user_id"],
            "scopes": api_key_data["scopes"],
            "name": api_key_data["name"]
        }
    
    async def revoke_api_key(self, key_id: str, user_id: str) -> bool:
        """Revoke API key"""
        
        if key_id not in self.api_keys:
            return False
        
        api_key_data = self.api_keys[key_id]
        
        # Check if user owns the key
        if api_key_data["user_id"] != user_id:
            return False
        
        # Deactivate key
        api_key_data["is_active"] = False
        
        logger.info("API key revoked", key_id=key_id, user_id=user_id)
        return True
    
    async def list_user_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """List API keys for a user"""
        
        user_keys = []
        for key_id, key_data in self.api_keys.items():
            if key_data["user_id"] == user_id:
                user_keys.append({
                    "key_id": key_id,
                    "name": key_data["name"],
                    "scopes": key_data["scopes"],
                    "created_at": key_data["created_at"],
                    "expires_at": key_data["expires_at"],
                    "is_active": key_data["is_active"]
                })
        
        return user_keys
    
    def _validate_scopes(self, scopes: List[str]) -> bool:
        """Validate API key scopes"""
        
        valid_scopes = [
            "browser:read",
            "browser:write",
            "sessions:read",
            "sessions:write",
            "sessions:manage",
            "admin:all"
        ]
        
        return all(scope in valid_scopes for scope in scopes)
    
    async def check_permission(self, user_data: Dict[str, Any], required_scope: str) -> bool:
        """Check if user has required permission"""
        
        user_scopes = user_data.get("scopes", [])
        
        # Check for exact scope or admin access
        return required_scope in user_scopes or "admin:all" in user_scopes
    
    async def get_user_permissions(self, user_data: Dict[str, Any]) -> List[str]:
        """Get all permissions for a user"""
        
        return user_data.get("scopes", [])
    
    async def create_user(
        self, 
        username: str, 
        password: str, 
        scopes: List[str] = None
    ) -> Dict[str, Any]:
        """Create new user (admin function)"""
        
        if not self.initialized:
            raise AuthenticationError("Authentication service not initialized")
        
        if username in self.users:
            raise ValidationError("username", "User already exists")
        
        # Validate scopes
        if scopes and not self._validate_scopes(scopes):
            raise ValidationError("scopes", "Invalid scopes provided")
        
        # Hash password
        hashed_password = SecurityConfig.hash_password(password)
        
        # Create user
        user_data = {
            "username": username,
            "hashed_password": hashed_password,
            "scopes": scopes or ["browser:read"],
            "created_at": datetime.utcnow(),
            "is_active": True
        }
        
        self.users[username] = user_data
        
        logger.info("User created", username=username, scopes=scopes)
        
        return {
            "username": username,
            "scopes": user_data["scopes"],
            "created_at": user_data["created_at"]
        }
    
    async def update_user_scopes(
        self, 
        username: str, 
        scopes: List[str]
    ) -> bool:
        """Update user scopes (admin function)"""
        
        if not self.initialized:
            raise AuthenticationError("Authentication service not initialized")
        
        if username not in self.users:
            return False
        
        if not self._validate_scopes(scopes):
            raise ValidationError("scopes", "Invalid scopes provided")
        
        self.users[username]["scopes"] = scopes
        
        logger.info("User scopes updated", username=username, scopes=scopes)
        return True

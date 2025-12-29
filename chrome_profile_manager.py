import threading
import time
import logging
from enum import Enum
from typing import Optional, Dict
from dataclasses import dataclass
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ProfileStatus(Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class ChromeProfile:
    profile_id: int
    profile_path: str
    status: ProfileStatus
    current_request_id: Optional[str] = None
    last_used: Optional[datetime] = None
    error_count: int = 0


class ChromeProfileManager:
    """
    Manages multiple Chrome profiles for concurrent image generation requests.
    Implements a round-robin allocation strategy with automatic fallback.
    """
    
    def __init__(self, profile_paths: Dict[int, str]):
        """
        Initialize the Chrome Profile Manager.
        
        Args:
            profile_paths: Dictionary mapping profile IDs to their paths
                          e.g., {1: "C:\\Users\\Administrator\\Documents\\mychat",
                                 2: "C:\\Users\\Administrator\\Documents\\mychat2"}
        """
        self.profiles: Dict[int, ChromeProfile] = {}
        self.lock = threading.Lock()
        self.current_profile_index = 0
        self.max_error_count = 3
        
        # Initialize all profiles
        for profile_id, path in profile_paths.items():
            self.profiles[profile_id] = ChromeProfile(
                profile_id=profile_id,
                profile_path=path,
                status=ProfileStatus.AVAILABLE
            )
        
        logger.info(f"✅ Initialized ChromeProfileManager with {len(self.profiles)} profiles")
        for profile_id, profile in self.profiles.items():
            logger.info(f"   Profile {profile_id}: {profile.profile_path}")
    
    def acquire_profile(self, request_id: str, timeout: int = 300) -> Optional[ChromeProfile]:
        """
        Acquire an available Chrome profile for image generation.
        Uses round-robin strategy with timeout.
        
        Args:
            request_id: Unique identifier for the request
            timeout: Maximum wait time in seconds
            
        Returns:
            ChromeProfile if available, None if timeout
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.lock:
                # Try to find an available profile starting from current index
                for _ in range(len(self.profiles)):
                    profile_id = (self.current_profile_index % len(self.profiles)) + 1
                    profile = self.profiles[profile_id]
                    
                    # Check if profile is available and not in error state
                    if (profile.status == ProfileStatus.AVAILABLE and 
                        profile.error_count < self.max_error_count):
                        
                        # Allocate the profile
                        profile.status = ProfileStatus.BUSY
                        profile.current_request_id = request_id
                        profile.last_used = datetime.now()
                        
                        # Move to next profile for next request
                        self.current_profile_index = profile_id % len(self.profiles)
                        
                        logger.info(f"🔓 Profile {profile_id} acquired by request {request_id}")
                        return profile
                    
                    self.current_profile_index = (self.current_profile_index + 1) % len(self.profiles)
            
            # No profile available, wait and retry
            logger.info(f"⏳ No profile available for request {request_id}, waiting...")
            time.sleep(2)
        
        logger.error(f"❌ Timeout: No profile available for request {request_id} after {timeout}s")
        return None
    
    def release_profile(self, profile_id: int, request_id: str, success: bool = True):
        """
        Release a Chrome profile after use.
        
        Args:
            profile_id: ID of the profile to release
            request_id: Request ID that was using the profile
            success: Whether the operation was successful
        """
        with self.lock:
            if profile_id not in self.profiles:
                logger.error(f"❌ Invalid profile ID: {profile_id}")
                return
            
            profile = self.profiles[profile_id]
            
            # Verify the request ID matches
            if profile.current_request_id != request_id:
                logger.warning(
                    f"⚠️ Request ID mismatch for profile {profile_id}. "
                    f"Expected: {profile.current_request_id}, Got: {request_id}"
                )
            
            # Update error count
            if not success:
                profile.error_count += 1
                logger.warning(f"⚠️ Profile {profile_id} error count: {profile.error_count}")
                
                if profile.error_count >= self.max_error_count:
                    profile.status = ProfileStatus.ERROR
                    logger.error(f"❌ Profile {profile_id} marked as ERROR (max errors reached)")
                else:
                    profile.status = ProfileStatus.AVAILABLE
            else:
                profile.status = ProfileStatus.AVAILABLE
                profile.error_count = 0  # Reset error count on success
            
            profile.current_request_id = None
            
            logger.info(f"🔒 Profile {profile_id} released by request {request_id}")
    
    def get_profile_status(self) -> Dict[int, dict]:
        """Get status of all profiles."""
        with self.lock:
            return {
                profile_id: {
                    "status": profile.status.value,
                    "current_request": profile.current_request_id,
                    "last_used": profile.last_used.isoformat() if profile.last_used else None,
                    "error_count": profile.error_count
                }
                for profile_id, profile in self.profiles.items()
            }
    
    def reset_profile(self, profile_id: int):
        """Manually reset a profile (useful for error recovery)."""
        with self.lock:
            if profile_id in self.profiles:
                profile = self.profiles[profile_id]
                profile.status = ProfileStatus.AVAILABLE
                profile.current_request_id = None
                profile.error_count = 0
                logger.info(f"🔄 Profile {profile_id} manually reset")
            else:
                logger.error(f"❌ Invalid profile ID: {profile_id}")
    
    def get_available_count(self) -> int:
        """Get count of available profiles."""
        with self.lock:
            return sum(1 for p in self.profiles.values() 
                      if p.status == ProfileStatus.AVAILABLE and 
                      p.error_count < self.max_error_count)
"""
Configuration package for Mingle Backend.

Provides centralized configuration management with support for:
- Local development (.env files)
- Cloud deployment (environment variables)
- Secure secret management
- Centralized settings for all modules
"""

# Import core configuration only
from .config import *

# Core configuration exports are imported from config.py via *
# Domain-specific modules import from config, not the other way around

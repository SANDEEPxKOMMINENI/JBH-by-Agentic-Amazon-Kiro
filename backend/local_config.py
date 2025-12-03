"""
Local Configuration for JobHuntr Backend
@file purpose: Local configuration values read from root .env file

🔧 SETUP INSTRUCTIONS:
1. Edit the .env file in the project root
2. Set APP_ENV to 'local' or 'production' (default: production)
3. URLs are hardcoded based on APP_ENV
4. JWT tokens are stored automatically in the app's data directory when users log in

ℹ️ ARCHITECTURE:
- Backend never talks to Supabase directly
- All database queries go through service-gateway
- Service-gateway validates JWT tokens and enforces user data isolation
- Users can only access their own data through authenticated requests
"""

import os  # noqa: E402
from pathlib import Path  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

# Load environment variables from root .env file
root_dir = Path(__file__).parent.parent
env_path = root_dir / ".env"
load_dotenv(env_path)

# Get environment setting
ENV = os.getenv("APP_ENV", "production")

# 🌐 SERVICE GATEWAY SETTINGS
# URLs are hardcoded based on APP_ENV
# Both 'local' and 'test' use localhost (test is for release builds that connect locally)
if ENV in ("local", "test"):
    SERVICE_GATEWAY_URL = "http://localhost:8001"
    BACKEND_PORT = 8001  # Service gateway port
else:
    SERVICE_GATEWAY_URL = (
        "https://democratized-service-gateway-production.up.railway.app"
    )
    BACKEND_PORT = 8001  # Service gateway port

# Development settings
DEBUG = True

# 🔑 API KEYS (Optional)
# Only needed if you want to use Google's Gemini AI model
# Get from: https://makersuite.google.com/app/apikey
GOOGLE_API_KEY = None

# ℹ️ NOTE:
# - No JWT secrets needed here - service-gateway handles validation
# - User JWT tokens are stored locally in app data directory
# - Each user can only access their own data through service-gateway

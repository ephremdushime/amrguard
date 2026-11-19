import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Ensure unit/API tests always run against an isolated synthetic test database by default
os.environ.setdefault('APP_ENV', 'test')
os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_amrguard.db')
os.environ.setdefault('INTEGRATION_API_KEY', '')

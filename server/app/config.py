import os

HOST = "127.0.0.1"
PORT = 8710
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./skilllens.db")
API_PREFIX = "/api/v1"

"""Offline test environment: dummy, schema-valid settings. No real credentials."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://testuser:testpass123@localhost:5432/testdb")
os.environ.setdefault("YOUTUBE_API_KEY", "dummy-test-key")
os.environ.setdefault("R2_ENDPOINT", "https://test.r2.example.com")
os.environ.setdefault("R2_BUCKET_NAME", "test-bucket")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test-access-id")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test-secret-key-ok")

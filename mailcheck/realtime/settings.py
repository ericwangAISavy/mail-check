"""Environment-only realtime configuration; never expose Redis credentials."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    redis_url: str = ''
    public_url: str = ''

    @property
    def enabled(self) -> bool:
        return bool(self.redis_url)

    @classmethod
    def from_env(cls) -> 'Settings':
        redis_url = os.environ.get('OFFERPATH_REDIS_URL', '').strip()
        public_url = os.environ.get('OFFERPATH_PUBLIC_URL', '').strip().rstrip('/')
        if redis_url and urlsplit(redis_url).scheme not in {'redis', 'rediss', 'unix'}:
            raise ValueError('OFFERPATH_REDIS_URL must use redis, rediss or unix')
        if public_url:
            parsed = urlsplit(public_url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or parsed.path):
                raise ValueError('OFFERPATH_PUBLIC_URL must be an HTTPS application root')
        return cls(redis_url=redis_url, public_url=public_url)

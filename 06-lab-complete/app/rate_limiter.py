"""
Rate limiting (tiêu chí 7) — sliding window 60 giây, state lưu trong Redis.

Mỗi API key có một sorted set `rate:<hash>`: member = request, score = timestamp.
Vượt RATE_LIMIT_PER_MINUTE → HTTP 429 + header Retry-After.
State nằm trong Redis nên mọi worker dùng chung và còn nguyên sau khi restart agent.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    redis_key = "rate:" + hashlib.sha256(key.encode()).hexdigest()[:16]  # không lưu key thô
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex}"
    try:
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)
        pipe.zadd(redis_key, {member: now})
        pipe.zcard(redis_key)
        pipe.zrange(redis_key, 0, 0, withscores=True)
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        _, _, count, oldest, _ = pipe.execute()
        if count > limit:
            r.zrem(redis_key, member)  # request bị từ chối không chiếm slot
            oldest_ts = oldest[0][1] if oldest else now
            retry_after = max(1, int(oldest_ts + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={"error": "Rate limit exceeded", "limit": limit, "window_seconds": WINDOW_SECONDS},
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (Redis)")

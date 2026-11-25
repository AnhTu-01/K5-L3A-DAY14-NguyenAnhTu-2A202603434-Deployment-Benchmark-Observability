"""
Cost guard (tiêu chí 8).

Cộng dồn chi phí LLM (tính theo token) vào Redis theo ngày và theo tháng.
Tổng vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
import time

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _keys() -> tuple[str, str]:
    return f"cost:day:{time.strftime('%Y-%m-%d')}", f"cost:month:{time.strftime('%Y-%m')}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → HTTP 402."""
    day_key, month_key = _keys()
    try:
        day_cost = float(r.get(day_key) or 0)
        month_cost = float(r.get(month_key) or 0)
    except Exception:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (Redis)")
    if day_cost >= settings.daily_budget_usd or month_cost >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Budget exceeded",
                "daily_used_usd": round(day_cost, 6),
                "daily_budget_usd": settings.daily_budget_usd,
                "monthly_used_usd": round(month_cost, 6),
                "monthly_budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào tổng ngày/tháng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    day_key, month_key = _keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(day_key, cost)
        pipe.expire(day_key, 3 * 24 * 3600)
        pipe.incrbyfloat(month_key, cost)
        pipe.expire(month_key, 35 * 24 * 3600)
        pipe.execute()
    except Exception:
        pass  # không làm hỏng response nếu ghi chi phí lỗi
    return cost

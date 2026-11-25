"""
Production AI Agent — Part 6 Final Project

Chạy: uvicorn app.main:app --workers 2
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng log của app là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


def log(event: str, **fields):
    logger.info(event, extra={"extra_fields": fields})


@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port)
    yield
    # Graceful shutdown: uvicorn nhận SIGTERM → ngừng nhận request mới, chờ request đang chạy xong,
    # rồi chạy phần này và thoát với exit code 0.
    log("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    log(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - start) * 1000, 1),
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy (không phụ thuộc Redis)."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 200 khi Redis kết nối được, 503 nếu không."""
    if redis_healthy():
        return {"ready": True}
    return JSONResponse(status_code=503, content={"ready": False, "reason": "redis unavailable"})


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)  # 429 khi vượt giới hạn
    check_budget()  # 402 khi hết budget
    answer = llm_ask(body.question)
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    record_cost(input_tokens, output_tokens)
    return {"question": body.question, "answer": answer}

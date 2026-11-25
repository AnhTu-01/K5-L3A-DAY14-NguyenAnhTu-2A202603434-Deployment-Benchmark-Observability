# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)
1. API key hardcode (dòng 17): push lên GitHub là lộ key ngay.
2. `DATABASE_URL` chứa user/mật khẩu hardcode (dòng 18).
3. Config cứng, không đọc từ env: `DEBUG = True`, `MAX_TOKENS = 500` (dòng 21-22).
4. Dùng `print()` thay vì logging có cấu trúc (dòng 33, 38), khó lọc và phân tích log.
5. Log ra secret: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` (dòng 34). Khi chạy thật, terminal in ra `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`.
6. Không có endpoint `/health` và `/ready` nên platform không biết khi nào agent crash để restart.
7. `host="localhost"` và `port=8000` cứng (dòng 51-52), không đọc `PORT` từ biến môi trường mà Railway/Render inject.
8. `reload=True` (dòng 53) là chế độ debug, không nên dùng khi production; ngoài ra không có graceful shutdown.

### Exercise 1.2: Kết quả chạy bản develop
`curl -X POST "http://localhost:8000/ask?question=Hello"` trả 200 OK (`POST /ask?question=Hello HTTP/1.1" 200 OK`) với câu trả lời từ mock LLM. App chạy được nhưng chưa production-ready vì các lỗi ở trên.

### Exercise 1.3: So sánh develop và production
Bản develop nhận `question` qua query string; bản production nhận JSON body (thiếu `question` thì trả 422).

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`DEBUG`, `MAX_TOKENS`, key, DB URL) | Đọc từ biến môi trường qua `config.py` (`HOST`, `PORT`, `DEBUG`, `AGENT_API_KEY`...) | Đổi cấu hình giữa dev/staging/prod mà không sửa code; secret không nằm trong git |
| Secrets | `OPENAI_API_KEY` và mật khẩu DB nằm trong code, còn bị in ra log | Chỉ lấy từ env, `.env` nằm trong `.gitignore`, log không ghi secret | Lộ key trên GitHub hoặc log là mất tiền và bị chiếm quyền |
| Health check | Không có | `/health` (liveness) và `/ready` (readiness) | Platform biết khi nào restart container và khi nào được route traffic vào |
| Logging | `print()` kèm secret | JSON có cấu trúc (`event`, độ dài câu hỏi, `client_ip`), không log secret | Dễ lọc và phân tích trong log aggregator, an toàn hơn |
| Shutdown | Tắt đột ngột | Graceful: `lifespan` đặt `is_ready=False`, chờ request đang chạy, xử lý SIGTERM | Deploy hoặc scale không cắt ngang request của người dùng |
| Host và port | `localhost:8000` cứng | `HOST=0.0.0.0`, `PORT` từ env | Trong container hoặc cloud phải nghe 0.0.0.0 và dùng cổng platform cấp |
| Reload | `reload=True` luôn bật | Chỉ reload khi `DEBUG=true` | Reload tốn tài nguyên, không an toàn khi chạy thật |


**Kết quả chạy bản production (Exercise 1.3):** `POST /ask` (JSON `{"question":"Hello"}`) → 200; `GET /health` → 200 `{"status":"ok",...}`; `GET /ready` → 200 `{"ready":true}`. Server chạy trên `0.0.0.0:8000`, log dạng JSON.

---

## Part 2: Docker Containerization

### Exercise 2.1: Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image là gì?** `python:3.11` — bản Python đầy đủ (full distribution), nặng vì chứa nhiều công cụ hệ thống không cần cho runtime.
2. **Working directory là gì?** `/app` (khai báo bằng `WORKDIR /app`); các lệnh `COPY`/`RUN` sau đó chạy trong thư mục này.
3. **Tại sao COPY `requirements.txt` trước khi COPY code?** Để tận dụng Docker layer cache. Dependencies ít thay đổi, code thay đổi liên tục. Nếu `requirements.txt` không đổi thì layer `pip install` được dùng lại từ cache, chỉ build lại layer COPY code → build nhanh hơn nhiều.
4. **CMD vs ENTRYPOINT khác nhau thế nào?** `CMD` là lệnh mặc định và có thể bị ghi đè dễ dàng khi `docker run <image> <lệnh khác>`. `ENTRYPOINT` là executable cố định của container; tham số truyền vào `docker run` được nối thêm vào sau nó (muốn ghi đè phải dùng `--entrypoint`). Dockerfile này dùng `CMD ["python", "app.py"]`.

### Exercise 2.2: Build và chạy bản develop

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name agent-dev -p 8000:8000 my-agent:develop
curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
docker images my-agent:develop
```

- Build thành công (lần đầu ~352 s vì phải pull base image `python:3.11`).
- Container chạy, `/ask` trả về 200 với `{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}`.
- Kích thước image `my-agent:develop`: **1.15 GB**.

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images | grep my-agent
```

Kết quả đo thực tế:

| Image | Size |
|---|---|
| `my-agent:develop` (single-stage, `python:3.11`) | 1.15 GB |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 163 MB |

Chênh lệch: (1150 − 163) / 1150 ≈ **86%** nhỏ hơn (tính từ 1.15 GB đã làm tròn).

- **Stage 1 (builder):** dựa trên `python:3.11-slim`, cài công cụ build (`gcc`, `libpq-dev`) và chạy `pip install --user` để cài dependencies vào `/root/.local`. Stage này chỉ để build, không dùng để deploy.
- **Stage 2 (runtime):** `python:3.11-slim` mới, tạo user non-root `appuser`, chỉ `COPY --from=builder` thư mục `/root/.local` (site-packages) và source code, có `HEALTHCHECK`, chạy `uvicorn` với 2 workers.
- **Tại sao image nhỏ hơn?** (1) Base image `slim` thay cho bản full; (2) `gcc`, `libpq-dev` và cache apt nằm lại ở stage builder và bị bỏ đi, không đi vào image cuối; (3) image cuối chỉ chứa Python, các package đã cài và code. Ngoài ra chạy bằng non-root user an toàn hơn.

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

**Các service được khởi động:** `agent` (FastAPI AI agent), `redis` (cache/session/rate limiting), `qdrant` (vector database cho RAG), `nginx` (reverse proxy + load balancer, cổng 80/443). Chúng giao tiếp qua network nội bộ `internal`.

**Sơ đồ kiến trúc:**

```
                 Client (curl / browser)
                          │  :80
                          ▼
                 ┌─────────────────┐
                 │      nginx      │  reverse proxy, rate limit 10 req/s/IP,
                 │ (nginx:alpine)  │  security headers, round-robin upstream
                 └────────┬────────┘
                          │  agent:8000  (network "internal", không expose port ra ngoài)
                          ▼
                 ┌─────────────────┐
                 │      agent      │  FastAPI + uvicorn (2 workers)
                 └───────┬─────────┘
              ┌──────────┴──────────┐
              ▼                     ▼
      ┌───────────────┐     ┌────────────────┐
      │     redis     │     │     qdrant     │
      │ cache/session │     │ vector DB (RAG)│
      └───────────────┘     └────────────────┘
```

Chỉ `nginx` publish cổng ra máy host (80, 443); `agent`, `redis`, `qdrant` chỉ truy cập được trong network nội bộ. `agent` chỉ khởi động sau khi `redis` và `qdrant` báo healthy (`depends_on` + `condition: service_healthy`).

**Kết quả chạy thực tế** (`docker compose up -d --build`, sau đó `docker compose ps`): cả 4 container đều `Up`; `agent`, `redis`, `qdrant` ở trạng thái `healthy`.

```bash
curl http://localhost/health
# {"status":"ok","uptime_seconds":19.8,"version":"2.0.0","timestamp":"2026-11-25T08:03:42.957036"}

curl http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
# {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Cả hai request đi qua Nginx (cổng 80) tới agent và đều trả về kết quả hợp lệ.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **API key được check ở đâu?** Trong hàm dependency `verify_api_key` (đọc header `X-API-Key` bằng `APIKeyHeader`), được inject vào endpoint `/ask` qua `Depends(verify_api_key)`. Key đúng được đọc từ biến môi trường `AGENT_API_KEY`.
- **Điều gì xảy ra nếu sai key?** Thiếu key → `401 Unauthorized`; có key nhưng sai → `403 Forbidden`; đúng key → `200 OK`.
- **Làm sao rotate key?** Đặt giá trị mới cho biến môi trường `AGENT_API_KEY` (không sửa code, không commit key) rồi restart/redeploy service; key cũ lập tức hết hiệu lực. Client phải cập nhật sang key mới.

Test thực tế (server chạy với `AGENT_API_KEY=secret-key-123`):

```
curl -i .../ask -X POST -d '{"question": "Hello"}'                         → HTTP/1.1 401 Unauthorized  {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
curl -i .../ask -X POST -H "X-API-Key: wrong-key" ...                      → HTTP/1.1 403 Forbidden     {"detail":"Invalid API key."}
curl -i .../ask -X POST -H "X-API-Key: secret-key-123" ...                 → HTTP/1.1 200 OK            {"question":"Hello","answer":"..."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

Luồng JWT: client gửi `POST /auth/token` với username/password → server xác thực (`authenticate_user`) và ký token HS256 bằng `JWT_SECRET`, token chứa `sub` (username), `role` và `exp` (hết hạn sau 60 phút) → client gửi token qua header `Authorization: Bearer <token>` → dependency `verify_token` giải mã và kiểm tra chữ ký/hạn dùng cho mỗi request, không cần tra DB.

Test thực tế (user `student` / `demo123`, token đã được ẩn bớt):

```
POST /auth/token                       → token bắt đầu bằng eyJhbGciOiJIUzI1NiIs...
POST /ask  (Authorization: Bearer ...) → 200 OK, "usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}
POST /ask  (không có token)            → 401 Unauthorized  {"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

Response còn có các security header: `x-content-type-options: nosniff`, `x-frame-options: DENY`, `x-xss-protection`, `referrer-policy`.

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Algorithm:** Sliding window counter — mỗi user có một `deque` các timestamp; timestamp cũ hơn cửa sổ 60 giây bị loại bỏ trước mỗi lần check.
- **Limit:** user thường 10 requests/phút (`rate_limiter_user`), admin 100 requests/phút (`rate_limiter_admin`).
- **Bypass cho admin:** không bypass hoàn toàn; endpoint chọn limiter theo `role` trong token — role `admin` (ví dụ user `teacher`) dùng limiter 100 req/phút.

Test thực tế (gọi liên tục 12 lần với token của `student`; đã có 1 request trước đó trong cùng cửa sổ):

```
1..9 -> 200
10, 11, 12 -> 429
```

Response khi bị chặn: `HTTP/1.1 429 Too Many Requests`, header `x-ratelimit-limit: 10`, `x-ratelimit-remaining: 0`, `retry-after: 44`, body `{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":44}}`.

### Exercise 4.4: Cost guard (`cost_guard.py`)

Bản trong `04-api-gateway/production/cost_guard.py` theo dõi usage theo user theo ngày: tính chi phí từ số token (input $0.00015/1K, output $0.0006/1K), kiểm tra trước khi gọi LLM, và trả `402 Payment Required` khi user vượt budget ngày ($1/ngày/user), `503` khi vượt budget toàn cục ($10/ngày); cảnh báo log khi dùng 80% budget. Bản này lưu in-memory nên mất khi restart và không chia sẻ giữa nhiều instance; trong production dùng Redis (key dạng `budget:{user_id}:{YYYY-MM}`, cộng dồn bằng `INCRBYFLOAT`, đặt `EXPIRE`) để trạng thái nhất quán khi scale. Phần này sẽ được làm thật trong `06-lab-complete/app/cost_guard.py` (Part 6).

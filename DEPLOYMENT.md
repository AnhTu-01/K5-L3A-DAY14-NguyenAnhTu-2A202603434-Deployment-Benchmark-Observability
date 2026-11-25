# Deployment Information

## Public URL
https://agent-production-23006998.up.railway.app

## Platform
Railway (agent + Redis trong cùng một project, build từ `06-lab-complete/Dockerfile`)

## Test Commands

### Health Check
```bash
curl https://agent-production-23006998.up.railway.app/health
# {"status":"ok","environment":"production"}
```

### Readiness
```bash
curl https://agent-production-23006998.up.railway.app/ready
# {"ready":true}
```

### API Test — không có key (401)
```bash
curl -i https://agent-production-23006998.up.railway.app/ask -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# HTTP/2 401
```

### API Test — có key (200)
```bash
curl -X POST https://agent-production-23006998.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."}
```

(`$AGENT_API_KEY` là key riêng đã đặt trên Railway; không commit key vào repo.)

## Environment Variables Set
- `AGENT_API_KEY` (secret, sinh ngẫu nhiên, chỉ đặt trên Railway)
- `REDIS_URL` (tham chiếu tới service Redis của project: `${{Redis.REDIS_URL}}`)
- `ENVIRONMENT=production`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `PORT` (do Railway tự cấp)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

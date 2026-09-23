import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import advisor, health, hosts, requests
from app.core.config import get_settings

# Without this, app-level loggers (e.g. app.services.ssh_audit) have no
# handler attached and their messages are silently dropped -- uvicorn only
# configures its OWN "uvicorn"/"uvicorn.access" loggers, not the root logger
# our modules propagate to. This is what made AAP Controller audit failures
# ("sunucuya erişemedi veya zaman aşımına uğradı") show up nowhere in
# `journalctl -u diskadvisor-api`.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()

app = FastAPI(title="DiskAdvisor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # UI arkasında kurumsal reverse-proxy/SSO varsayıldı (bkz. plan)
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(advisor.router, prefix=settings.api_v1_prefix)
app.include_router(requests.router, prefix=settings.api_v1_prefix)
app.include_router(hosts.router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict:
    return {"service": "diskadvisor-api", "docs": "/docs"}

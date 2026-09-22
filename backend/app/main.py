from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import advisor, health, hosts, requests
from app.core.config import get_settings

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

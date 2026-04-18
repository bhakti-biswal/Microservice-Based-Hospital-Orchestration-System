import os
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ── Config ────────────────────────────────────────────────────────────────────
AUTH_SERVICE_URL      = os.getenv("AUTH_SERVICE_URL",         "http://auth-service:8001")
PATIENT_SERVICE_URL   = os.getenv("PATIENT_SERVICE_URL",      "http://patient-service:8002")
ANALYTICS_SERVICE_URL = os.getenv("ANALYTICS_SERVICE_URL",    "http://analytics-service:8003")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8004")

app = FastAPI(
    title="API Gateway",
    version="1.0.0",
    description="Central entry point — validates JWT and routes to microservices",
)
security = HTTPBearer(auto_error=False)


# ── Auth Helper ───────────────────────────────────────────────────────────────
async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header required")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{AUTH_SERVICE_URL}/auth/validate",
                headers={"Authorization": f"Bearer {credentials.credentials}"},
            )
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Auth service unreachable")
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return resp.json()


async def proxy(method: str, url: str, request: Request, extra_headers: dict = {}) -> Response:
    """Generic reverse-proxy helper."""
    body = await request.body()
    headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        **extra_headers,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Downstream service unavailable: {e}")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


# ── Auth Routes (public — no JWT needed) ─────────────────────────────────────
@app.post("/auth/register", tags=["Auth"])
async def register(request: Request):
    return await proxy("POST", f"{AUTH_SERVICE_URL}/auth/register", request)

@app.post("/auth/login", tags=["Auth"])
async def login(request: Request):
    return await proxy("POST", f"{AUTH_SERVICE_URL}/auth/login", request)

@app.get("/auth/me", tags=["Auth"])
async def me(request: Request, user: dict = Depends(verify_token)):
    return await proxy("GET", f"{AUTH_SERVICE_URL}/auth/me", request,
                       extra_headers={"Authorization": request.headers.get("authorization", "")})


# ── Patient Routes (protected) ────────────────────────────────────────────────
@app.get("/patients", tags=["Patients"])
async def list_patients(request: Request, user: dict = Depends(verify_token)):
    return await proxy("GET", f"{PATIENT_SERVICE_URL}/patients", request,
                       extra_headers={"X-User-ID": user.get("user_id", ""), "X-Username": user.get("username", "")})

@app.post("/patients", tags=["Patients"])
async def create_patient(request: Request, user: dict = Depends(verify_token)):
    return await proxy("POST", f"{PATIENT_SERVICE_URL}/patients", request,
                       extra_headers={"X-User-ID": user.get("user_id", ""), "X-Username": user.get("username", "")})

@app.get("/patients/{patient_id}", tags=["Patients"])
async def get_patient(patient_id: str, request: Request, user: dict = Depends(verify_token)):
    return await proxy("GET", f"{PATIENT_SERVICE_URL}/patients/{patient_id}", request,
                       extra_headers={"X-User-ID": user.get("user_id", "")})

@app.put("/patients/{patient_id}", tags=["Patients"])
async def update_patient(patient_id: str, request: Request, user: dict = Depends(verify_token)):
    return await proxy("PUT", f"{PATIENT_SERVICE_URL}/patients/{patient_id}", request,
                       extra_headers={"X-User-ID": user.get("user_id", "")})

@app.delete("/patients/{patient_id}", tags=["Patients"])
async def delete_patient(patient_id: str, request: Request, user: dict = Depends(verify_token)):
    return await proxy("DELETE", f"{PATIENT_SERVICE_URL}/patients/{patient_id}", request,
                       extra_headers={"X-User-ID": user.get("user_id", "")})


# ── Analytics Routes (protected) ──────────────────────────────────────────────
@app.get("/analytics/summary", tags=["Analytics"])
async def analytics_summary(request: Request, user: dict = Depends(verify_token)):
    return await proxy("GET", f"{ANALYTICS_SERVICE_URL}/analytics/summary", request)

@app.get("/analytics/events", tags=["Analytics"])
async def analytics_events(request: Request, user: dict = Depends(verify_token)):
    return await proxy("GET", f"{ANALYTICS_SERVICE_URL}/analytics/events", request)


# ── Notification Routes (protected) ───────────────────────────────────────────
@app.get("/notifications", tags=["Notifications"])
async def list_notifications(request: Request, user: dict = Depends(verify_token)):
    return await proxy("GET", f"{NOTIFICATION_SERVICE_URL}/notifications", request)


# ── Gateway Health ────────────────────────────────────────────────────────────
@app.get("/health", tags=["Gateway"])
async def health():
    services = {}
    targets = {
        "auth-service":         f"{AUTH_SERVICE_URL}/health",
        "patient-service":      f"{PATIENT_SERVICE_URL}/health",
        "analytics-service":    f"{ANALYTICS_SERVICE_URL}/health",
        "notification-service": f"{NOTIFICATION_SERVICE_URL}/health",
    }
    async with httpx.AsyncClient(timeout=5) as client:
        for name, url in targets.items():
            try:
                r = await client.get(url)
                services[name] = "healthy" if r.status_code == 200 else "degraded"
            except Exception:
                services[name] = "unreachable"
    overall = "healthy" if all(v == "healthy" for v in services.values()) else "degraded"
    return {
        "status": overall,
        "gateway": "healthy",
        "downstream": services,
        "timestamp": datetime.utcnow().isoformat(),
    }

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import uuid
import os

# ── Config ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

app = FastAPI(title="Auth Service", version="1.0.0", description="JWT Authentication Microservice")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# ── In-Memory Store (replace with PostgreSQL in production) ─────────────────
users_db: dict[str, dict] = {}


# ── Schemas ──────────────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    full_name: str = ""

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class TokenPayload(BaseModel):
    valid: bool
    username: str
    user_id: str
    email: str


# ── Helpers ──────────────────────────────────────────────────────────────────
def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# ── Routes ───────────────────────────────────────────────────────────────────
@app.post("/auth/register", status_code=201, summary="Register a new user")
async def register(user: UserRegister):
    if user.username in users_db:
        raise HTTPException(status_code=409, detail="Username already registered")
    user_id = str(uuid.uuid4())
    users_db[user.username] = {
        "id": user_id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "hashed_password": hash_password(user.password),
        "created_at": datetime.utcnow().isoformat(),
    }
    return {"message": "User registered successfully", "user_id": user_id, "username": user.username}


@app.post("/auth/login", response_model=Token, summary="Login and get JWT token")
async def login(user: UserLogin):
    stored = users_db.get(user.username)
    if not stored or not verify_password(user.password, stored["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({
        "sub": user.username,
        "user_id": stored["id"],
        "email": stored["email"],
    })
    return {"access_token": token, "token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}


@app.get("/auth/validate", response_model=TokenPayload, summary="Validate a JWT token")
async def validate_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username or username not in users_db:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        stored = users_db[username]
        return {
            "valid": True,
            "username": username,
            "user_id": payload.get("user_id"),
            "email": stored["email"],
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/auth/me", summary="Get current user profile")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        stored = users_db.get(username)
        if not stored:
            raise HTTPException(status_code=404, detail="User not found")
        return {k: v for k, v in stored.items() if k != "hashed_password"}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "auth-service", "timestamp": datetime.utcnow().isoformat()}

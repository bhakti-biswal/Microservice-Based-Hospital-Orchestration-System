# 🏥 Patient Management System — FastAPI Microservices

> A full microservices architecture built with **FastAPI**, replacing a Spring Boot implementation.
> Mirrors the architecture from the video: API Gateway → Auth → Patient → Billing (gRPC) + Kafka → Analytics + Notifications.

---

## 🏗️ Architecture

```
Frontend (Client)
      │
      ▼
┌─────────────┐
│ API Gateway │  :8000  ← JWT validation, reverse proxy
└──────┬──────┘
       │
   ┌───┴────────────────────────┐
   │                            │
   ▼                            ▼
┌──────────────┐      ┌─────────────────────────────────────┐
│ Auth Service │      │         Patient Service              │
│   :8001      │      │            :8002                     │
│              │      │  ┌──────────────┐  ┌─────────────┐  │
│ • register   │      │  │  gRPC Client │  │   Kafka     │  │
│ • login      │      │  └──────┬───────┘  │  Producer   │  │
│ • validate   │      │         │          └──────┬──────┘  │
└──────────────┘      └─────────┼─────────────────┼─────────┘
                                │                 │
                                ▼                 ▼
                     ┌──────────────────┐   ┌─────────────────────┐
                     │  Billing Service │   │  Kafka Topic        │
                     │  gRPC :50051     │   │  "patients"         │
                     │                  │   └──────┬──────────────┘
                     │ billing.proto    │          │
                     └──────────────────┘    ┌─────┴──────┐
                                             │            │
                                             ▼            ▼
                                   ┌──────────────┐  ┌──────────────────┐
                                   │  Analytics   │  │  Notification    │
                                   │  Service     │  │  Service         │
                                   │  :8003       │  │  :8004           │
                                   │  Consumer    │  │  Consumer        │
                                   └──────────────┘  └──────────────────┘
```

---

## 🛠️ Tech Stack

| Component         | Technology                        |
|-------------------|-----------------------------------|
| REST Framework    | **FastAPI** (replaces Spring Boot) |
| Auth              | JWT via `python-jose`             |
| Inter-service RPC | **gRPC** (`grpcio`)               |
| Message Broker    | **Apache Kafka** (`aiokafka`)     |
| Containerization  | **Docker** + Docker Compose       |
| Serialization     | Protocol Buffers (`.proto`)       |

---

## 🚀 Quick Start

### Prerequisites
- Docker ≥ 24
- Docker Compose ≥ 2.20

### 1. Clone / unzip the project
```bash
cd patient-management
```

### 2. Start all services
```bash
docker compose up --build
```

> ⏳ First boot takes ~2–3 minutes for Kafka to initialize and services to connect.

### 3. Check everything is healthy
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "gateway": "healthy",
  "downstream": {
    "auth-service": "healthy",
    "patient-service": "healthy",
    "analytics-service": "healthy",
    "notification-service": "healthy"
  }
}
```

---

## 🔑 API Usage (via API Gateway on port 8000)

### Register a user
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret123", "email": "admin@hospital.com", "full_name": "Admin User"}'
```

### Login → get JWT token
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### Create a patient (triggers gRPC + Kafka)
```bash
curl -X POST http://localhost:8000/patients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "email": "john@example.com",
    "date_of_birth": "1990-05-15",
    "address": "123 Main St, Springfield",
    "phone": "+1-555-0100",
    "medical_history": "No known allergies"
  }'
```

### List all patients
```bash
curl http://localhost:8000/patients \
  -H "Authorization: Bearer $TOKEN"
```

### Update a patient
```bash
curl -X PUT http://localhost:8000/patients/<PATIENT_ID> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+1-555-9999", "address": "456 New Ave"}'
```

### Delete a patient
```bash
curl -X DELETE http://localhost:8000/patients/<PATIENT_ID> \
  -H "Authorization: Bearer $TOKEN"
```

### View analytics (Kafka consumer results)
```bash
curl http://localhost:8000/analytics/summary \
  -H "Authorization: Bearer $TOKEN"
```

### View notifications (Kafka consumer results)
```bash
curl http://localhost:8000/notifications \
  -H "Authorization: Bearer $TOKEN"
```

---

## 📋 Service Ports

| Service              | Port  | Protocol   |
|----------------------|-------|------------|
| API Gateway          | 8000  | HTTP/REST  |
| Auth Service         | 8001  | HTTP/REST  |
| Patient Service      | 8002  | HTTP/REST  |
| Analytics Service    | 8003  | HTTP/REST  |
| Notification Service | 8004  | HTTP/REST  |
| Billing Service      | 50051 | gRPC       |
| Kafka                | 9092  | TCP        |

---

## 📁 Project Structure

```
patient-management/
├── docker-compose.yml
├── README.md
│
├── api-gateway/            # JWT validation + reverse proxy
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
│
├── auth-service/           # Register, login, validate JWT
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
│
├── patient-service/        # CRUD + gRPC client + Kafka producer
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── proto/
│       └── billing_service.proto
│
├── billing-service/        # gRPC server (compiled from .proto)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── grpc_server.py
│   └── proto/
│       └── billing_service.proto
│
├── analytics-service/      # Kafka consumer → metrics
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
│
└── notification-service/   # Kafka consumer → email notifications
    ├── Dockerfile
    ├── requirements.txt
    └── main.py
```

---

## 🔄 Event Flow

When a patient is **created**:
1. `POST /patients` hits the **API Gateway**
2. Gateway validates JWT with **Auth Service**
3. Request forwarded to **Patient Service**
4. Patient Service calls **Billing Service** via **gRPC** → creates billing account
5. Patient Service publishes `PATIENT_CREATED` event to **Kafka** topic `patients`
6. **Analytics Service** consumes event → updates counters
7. **Notification Service** consumes event → generates welcome email notification

---

## 🔧 Spring Boot → FastAPI Mapping

| Spring Boot                  | FastAPI Equivalent                      |
|------------------------------|-----------------------------------------|
| `@RestController`            | `@app.get/post/put/delete`              |
| `@Service`                   | Python module / class                   |
| `@Repository` + JPA          | SQLAlchemy / in-memory dict             |
| `spring-cloud-gateway`       | FastAPI + httpx reverse proxy           |
| `spring-security` + JWT      | `python-jose` + `passlib`              |
| `spring-kafka` Producer      | `aiokafka.AIOKafkaProducer`            |
| `spring-kafka` Consumer      | `aiokafka.AIOKafkaConsumer`            |
| `@GrpcClient` / `@GrpcServer`| `grpcio` + `grpcio-tools`             |
| `application.properties`     | Environment variables / `.env`         |
| Maven / `pom.xml`            | `pip` / `requirements.txt`            |

---

## 📚 Swagger / OpenAPI Docs

Each service exposes interactive docs:

| Service              | Swagger UI                            |
|----------------------|---------------------------------------|
| API Gateway          | http://localhost:8000/docs            |
| Auth Service         | http://localhost:8001/docs            |
| Patient Service      | http://localhost:8002/docs            |
| Analytics Service    | http://localhost:8003/docs            |
| Notification Service | http://localhost:8004/docs            |

---

## 🛑 Shutdown

```bash
docker compose down          # stop containers
docker compose down -v       # stop + remove volumes
```

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import grpc
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

import billing_service_pb2
import billing_service_pb2_grpc

# ── Config ───────────────────────────────────────────────────────────────────
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL", "billing-service:50051")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = "patients"

# ── In-Memory Store ───────────────────────────────────────────────────────────
patients_db: dict[str, dict] = {}
producer: Optional[AIOKafkaProducer] = None


# ── Schemas ───────────────────────────────────────────────────────────────────
class PatientCreate(BaseModel):
    name: str
    email: str
    date_of_birth: str
    address: str
    phone: str
    medical_history: str = ""

class PatientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    medical_history: Optional[str] = None


# ── Kafka Helpers ─────────────────────────────────────────────────────────────
async def get_producer() -> AIOKafkaProducer:
    global producer
    retries = 10
    for attempt in range(retries):
        try:
            p = AIOKafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await p.start()
            print("✅ Kafka producer connected")
            return p
        except Exception as e:
            print(f"⏳ Kafka not ready (attempt {attempt+1}/{retries}): {e}")
            await asyncio.sleep(5)
    raise RuntimeError("Could not connect to Kafka after multiple retries")


async def publish_event(event_type: str, patient_data: dict):
    global producer
    if producer is None:
        print("⚠️  Kafka producer not available, skipping event")
        return
    try:
        event = {
            "event_type": event_type,
            "patient": patient_data,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "patient-service",
        }
        await producer.send_and_wait(KAFKA_TOPIC, event)
        print(f"📤 Kafka event published: {event_type} for patient {patient_data.get('id')}")
    except Exception as e:
        print(f"❌ Failed to publish Kafka event: {e}")


# ── gRPC Helpers ──────────────────────────────────────────────────────────────
def get_billing_stub():
    channel = grpc.insecure_channel(BILLING_SERVICE_URL)
    return billing_service_pb2_grpc.BillingServiceStub(channel)

def grpc_create_billing_account(patient_id: str, name: str, email: str, address: str):
    try:
        stub = get_billing_stub()
        response = stub.CreateBillingAccount(
            billing_service_pb2.BillingRequest(
                patient_id=patient_id,
                patient_name=name,
                email=email,
                address=address,
            ),
            timeout=10,
        )
        print(f"💳 Billing account created: {response.account_id}")
        return response
    except grpc.RpcError as e:
        print(f"❌ gRPC billing error: {e.code()} - {e.details()}")
        return None

def grpc_update_billing_account(patient_id: str, name: str, email: str, address: str):
    try:
        stub = get_billing_stub()
        response = stub.UpdateBillingAccount(
            billing_service_pb2.BillingUpdateRequest(
                patient_id=patient_id,
                patient_name=name,
                email=email,
                address=address,
            ),
            timeout=10,
        )
        return response
    except grpc.RpcError as e:
        print(f"❌ gRPC update error: {e.code()} - {e.details()}")
        return None


# ── App Lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = await get_producer()
    yield
    if producer:
        await producer.stop()

app = FastAPI(title="Patient Service", version="1.0.0", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/patients", summary="List all patients")
async def list_patients():
    return {"patients": list(patients_db.values()), "total": len(patients_db)}


@app.post("/patients", status_code=201, summary="Create a new patient")
async def create_patient(patient: PatientCreate):
    patient_id = str(uuid.uuid4())
    patient_data = {
        "id": patient_id,
        **patient.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": None,
        "billing_account_id": None,
    }
    patients_db[patient_id] = patient_data

    # ── gRPC: Create billing account ─────────────────────────────────────────
    billing_resp = grpc_create_billing_account(
        patient_id, patient.name, patient.email, patient.address
    )
    if billing_resp:
        patient_data["billing_account_id"] = billing_resp.account_id

    # ── Kafka: Publish PATIENT_CREATED event ──────────────────────────────────
    await publish_event("PATIENT_CREATED", patient_data)

    return patient_data


@app.get("/patients/{patient_id}", summary="Get patient by ID")
async def get_patient(patient_id: str):
    patient = patients_db.get(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return patient


@app.put("/patients/{patient_id}", summary="Update patient")
async def update_patient(patient_id: str, update: PatientUpdate):
    patient = patients_db.get(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    update_fields = update.model_dump(exclude_unset=True)
    patient.update(update_fields)
    patient["updated_at"] = datetime.utcnow().isoformat()
    patients_db[patient_id] = patient

    # ── gRPC: Update billing account ──────────────────────────────────────────
    grpc_update_billing_account(
        patient_id,
        patient.get("name", ""),
        patient.get("email", ""),
        patient.get("address", ""),
    )

    # ── Kafka: Publish PATIENT_UPDATED event ──────────────────────────────────
    await publish_event("PATIENT_UPDATED", patient)

    return patient


@app.delete("/patients/{patient_id}", status_code=204, summary="Delete patient")
async def delete_patient(patient_id: str):
    patient = patients_db.get(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    del patients_db[patient_id]

    # ── Kafka: Publish PATIENT_DELETED event ──────────────────────────────────
    await publish_event("PATIENT_DELETED", {"id": patient_id, "name": patient.get("name")})


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "patient-service", "timestamp": datetime.utcnow().isoformat()}

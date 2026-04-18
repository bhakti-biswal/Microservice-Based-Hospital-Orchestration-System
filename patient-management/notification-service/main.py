import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI

# ── Config ────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = "patients"
GROUP_ID = "notification-group"

# ── State ─────────────────────────────────────────────────────────────────────
notifications: list[dict] = []
consumer: Optional[AIOKafkaConsumer] = None


# ── Notification Builder ──────────────────────────────────────────────────────
def build_notification(event_type: str, patient: dict) -> dict:
    name = patient.get("name", "Unknown")
    email = patient.get("email", "")
    patient_id = patient.get("id", "")

    messages = {
        "PATIENT_CREATED": {
            "subject": "Welcome to Patient Management System",
            "body": f"Hello {name}, your patient profile has been successfully created. "
                    f"A billing account has also been set up for you.",
            "channel": "EMAIL",
        },
        "PATIENT_UPDATED": {
            "subject": "Your Profile Has Been Updated",
            "body": f"Hello {name}, your patient information was recently updated. "
                    f"If you did not make this change, please contact support.",
            "channel": "EMAIL",
        },
        "PATIENT_DELETED": {
            "subject": "Patient Account Removed",
            "body": f"Patient record {patient_id} has been removed from the system.",
            "channel": "INTERNAL",
        },
    }

    template = messages.get(event_type, {
        "subject": f"Notification: {event_type}",
        "body": f"An event occurred for patient {name}.",
        "channel": "INTERNAL",
    })

    return {
        "id": str(uuid.uuid4()),
        "event_type": event_type,
        "patient_id": patient_id,
        "recipient_email": email,
        "recipient_name": name,
        "subject": template["subject"],
        "body": template["body"],
        "channel": template["channel"],
        "status": "SENT",
        "sent_at": datetime.utcnow().isoformat(),
    }


# ── Consumer Loop ─────────────────────────────────────────────────────────────
async def consume():
    global consumer
    retries = 15
    for attempt in range(retries):
        try:
            consumer = AIOKafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                group_id=GROUP_ID,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="earliest",
            )
            await consumer.start()
            print(f"🔔 Notification consumer started — listening on topic '{KAFKA_TOPIC}'")
            break
        except Exception as e:
            print(f"⏳ Notification: Kafka not ready (attempt {attempt+1}/{retries}): {e}")
            await asyncio.sleep(5)
    else:
        print("❌ Notification: Could not connect to Kafka")
        return

    try:
        async for msg in consumer:
            event = msg.value
            event_type = event.get("event_type", "UNKNOWN")
            patient = event.get("patient", {})

            notification = build_notification(event_type, patient)
            notifications.insert(0, notification)

            # Keep last 200 notifications
            if len(notifications) > 200:
                notifications.pop()

            print(f"📧 [Notification] {notification['channel']} → {notification['recipient_email']}: {notification['subject']}")

    except asyncio.CancelledError:
        pass
    finally:
        await consumer.stop()


# ── App Lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(consume())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Notification Service", version="1.0.0", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/notifications", summary="List all notifications")
async def list_notifications(limit: int = 20):
    return {
        "notifications": notifications[:limit],
        "total": len(notifications),
    }

@app.get("/notifications/{notification_id}", summary="Get a notification by ID")
async def get_notification(notification_id: str):
    for n in notifications:
        if n["id"] == notification_id:
            return n
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Notification not found")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "notification-service",
        "notifications_sent": len(notifications),
        "timestamp": datetime.utcnow().isoformat(),
    }

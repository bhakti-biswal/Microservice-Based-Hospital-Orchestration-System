import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI

# ── Config ────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = "patients"
GROUP_ID = "analytics-group"

# ── State ─────────────────────────────────────────────────────────────────────
analytics: dict = {
    "total_active_patients": 0,
    "total_created": 0,
    "total_updated": 0,
    "total_deleted": 0,
    "recent_events": [],
    "started_at": datetime.utcnow().isoformat(),
}
consumer: Optional[AIOKafkaConsumer] = None


# ── Consumer Loop ─────────────────────────────────────────────────────────────
async def consume():
    global consumer, analytics
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
            print(f"📊 Analytics consumer started — listening on topic '{KAFKA_TOPIC}'")
            break
        except Exception as e:
            print(f"⏳ Analytics: Kafka not ready (attempt {attempt+1}/{retries}): {e}")
            await asyncio.sleep(5)
    else:
        print("❌ Analytics: Could not connect to Kafka")
        return

    try:
        async for msg in consumer:
            event = msg.value
            event_type = event.get("event_type", "UNKNOWN")
            patient = event.get("patient", {})
            timestamp = event.get("timestamp", datetime.utcnow().isoformat())

            print(f"📊 [Analytics] Processing event: {event_type}")

            # Update counters
            if event_type == "PATIENT_CREATED":
                analytics["total_created"] += 1
                analytics["total_active_patients"] += 1
            elif event_type == "PATIENT_UPDATED":
                analytics["total_updated"] += 1
            elif event_type == "PATIENT_DELETED":
                analytics["total_deleted"] += 1
                analytics["total_active_patients"] = max(0, analytics["total_active_patients"] - 1)

            # Keep last 50 events in memory
            analytics["recent_events"].insert(0, {
                "event_type": event_type,
                "patient_id": patient.get("id"),
                "patient_name": patient.get("name"),
                "timestamp": timestamp,
            })
            analytics["recent_events"] = analytics["recent_events"][:50]

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

app = FastAPI(title="Analytics Service", version="1.0.0", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/analytics/summary", summary="Get analytics summary")
async def get_summary():
    return {
        **analytics,
        "fetched_at": datetime.utcnow().isoformat(),
    }

@app.get("/analytics/events", summary="Get recent patient events")
async def get_events():
    return {"events": analytics["recent_events"], "count": len(analytics["recent_events"])}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "analytics-service", "timestamp": datetime.utcnow().isoformat()}

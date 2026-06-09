from contextlib import asynccontextmanager
import asyncio
import json
from datetime import datetime
import random
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dataclasses import dataclass, asdict


# --- Модели данных ---
class SensorData(BaseModel):
    temperature: str
    systemStatus: str
    sessionTime: str
    s1: str
    s2: str


@dataclass
class Event:
    type: str
    timestamp: str
    id: str
    manual: bool
    sequence: int

    def model_dump(self) -> dict:
        return asdict(self)


EVENT_TYPES = [
    'patient_lift_up',
    'patient_lift_down',
    'patient_lift_stop',
    'tube_lift_up',
    'tube_lift_down',
    'tube_lift_stop'
]


# --- Глобальный менеджер соединений ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"✅ Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"❌ Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast_sensor_data(self, sensor_data: SensorData):
        if not self.active_connections:
            print("⚠️ No active connections for sensor data")
            return

        message = json.dumps({
            "type": "sensor_data",
            "data": sensor_data.model_dump(),
            "timestamp": datetime.now().isoformat()
        })

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
                print(f"📤 Sent sensor data to client")
            except WebSocketDisconnect:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_event(self, event: Event):
        if not self.active_connections:
            print("⚠️ No active connections for event")
            return

        message = json.dumps({
            "type": "event",
            "data": event.model_dump(),
            "timestamp": datetime.now().isoformat()
        })

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
                print(f"📤 Sent event to client: {event.type}")
            except WebSocketDisconnect:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


# --- Генераторы данных ---
async def sensor_data_generator():
    sequence = 0
    while True:
        await asyncio.sleep(0.2)
        sequence += 1
        sensor_data = SensorData(
            temperature=str(random.choice(["-196.0", "-195.2", "-197.1"])),
            systemStatus=random.choice(["Простой", "Сушка", "Процедура", "Авария"]),
            sessionTime=str(120 + sequence * 0.2),
            s1=str(random.randint(36, 39)),
            s2=str(random.randint(36, 39))
        )
        yield sensor_data


async def sensor_event_generator():
    sequence = 0
    while True:
        await asyncio.sleep(2 + random.random() * 2)
        sequence += 1
        event = Event(
            type=random.choice(EVENT_TYPES),
            timestamp=datetime.now().isoformat(),
            id=f"{random.choice('abcdefg')}{''.join(random.choices('0123456789ab', k=5))}",
            manual=random.choice([True, False]),
            sequence=sequence
        )
        yield event


# --- Фоновые задачи ---
async def broadcast_sensor_data_loop():
    """Фоновая задача: рассылка данных сенсоров всем клиентам"""
    async for sensor_data in sensor_data_generator():
        await manager.broadcast_sensor_data(sensor_data)
        print(f"🔄 Sensor data generated: temp={sensor_data.temperature}")


async def broadcast_events_loop():
    """Фоновая задача: рассылка событий всем клиентам"""
    async for event in sensor_event_generator():
        await manager.broadcast_event(event)
        print(f"🔄 Event generated: {event.type} (seq: {event.sequence})")


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting server...")
    task1 = asyncio.create_task(broadcast_sensor_data_loop())
    task2 = asyncio.create_task(broadcast_events_loop())
    print("✅ Background tasks started")

    yield

    # Shutdown
    print("🛑 Shutting down...")
    task1.cancel()
    task2.cancel()
    await asyncio.gather(task1, task2, return_exceptions=True)
    print("✅ Shutdown complete")


# --- FastAPI приложение ---
app = FastAPI(title="Sensor Data Backend", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- REST endpoints ---
@app.get("/api/sensors", response_model=SensorData)
async def get_sensor_data():
    return SensorData(
        temperature="-196",
        systemStatus="Процедура",
        sessionTime="120",
        s1="37",
        s2="38"
    )


@app.get("/api/status")
async def get_status():
    return {
        "status": "running",
        "active_connections": len(manager.active_connections)
    }


# --- WebSocket endpoint (ВАЖНО: используем менеджер) ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Добавляем соединение в менеджер
    await manager.connect(websocket)

    try:
        # Отправляем приветственное сообщение
        await websocket.send_json({
            "type": "connection_established",
            "message": "Connected to sensor data stream",
            "timestamp": datetime.now().isoformat()
        })

        print(f"📡 Client connected, sending welcome message")

        # Держим соединение открытым
        while True:
            # Ждем сообщения от клиента (можно добавить команды)
            try:
                data = await websocket.receive_text()
                print(f"📨 Received from client: {data}")

                # Отправляем echo
                await websocket.send_json({
                    "type": "echo",
                    "received": data,
                    "timestamp": datetime.now().isoformat()
                })
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        print("Client disconnected")
    finally:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
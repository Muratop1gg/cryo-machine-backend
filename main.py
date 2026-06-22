from contextlib import asynccontextmanager
import asyncio
import json
from datetime import datetime
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette import status

import models


# --- Глобальный менеджер соединений ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: models.List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"✅ Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"❌ Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast_sensor_data(self, sensor_data: models.SensorData):
        if not self.active_connections:
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
            except WebSocketDisconnect:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_event(self, event: models.Event):
        if not self.active_connections:
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
        ss = models.SystemStatusModel(
            currentMode= "cooling",
            errorCode = [],
            SteamOnline = True,
            HoistOnline= True,
        )

        t = models.TelemetryModel(
            Temperature = models.TemperatureModel(SteamGenerator=0, HeaterZone=0, AirDuct=0, Humidity=0, ChamberZone=0),
            Environment = models.EnvironmentModel(AirDuctHumidity=0,ChamberHumidity = 0,ChamberOxygen = 0,NitrogenLevel = 0),
            vfdStatus = models.VFDStatusesModel(Steam= models.VFDModel(Frequency=0, ErrorCode=""), Hoist=models.VFDModel(Frequency=0, ErrorCode="")),
        )

        sensor_data = models.SensorData(
            SystemStatus=ss,
            Telemetry=t
        )
        yield sensor_data


async def sensor_event_generator():
    while True:
        await asyncio.sleep(2 + random.random() * 2)
        event = models.Event(EventType=0)
        yield event


# --- Фоновые задачи ---
async def broadcast_sensor_data_loop():
    """Фоновая задача: рассылка данных сенсоров всем клиентам"""
    async for sensor_data in sensor_data_generator():
        await manager.broadcast_sensor_data(sensor_data)

async def broadcast_events_loop():
    """Фоновая задача: рассылка событий всем клиентам"""
    async for event in sensor_event_generator():
        await manager.broadcast_event(event)



# --- Lifespan ---
@asynccontextmanager
async def lifespan(myapp: FastAPI):
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

@app.get("/api/status")
async def get_status():
    return {
        "status": "running",
        "active_connections": len(manager.active_connections)
    }


@app.post("/api/settings")
async def update_settings(settings: models.UpdateSettings):
    try:
        # Валидация значений
        # if settings.TechnologicalSettings.WorkingTime <= 0:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail="WorkingTime must be greater than 0"
        #     )
        #
        # if settings.TechnologicalSettings.S1Temperature < -50 or \
        #         settings.TechnologicalSettings.S1Temperature > 150:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail="S1Temperature out of range (-50 to 150)"
        #     )

        # Сохраняем настройки (пример)
        # save_to_database(settings)

        return {
            "status": "success",
            "message": "Settings updated successfully",
            "data": settings.model_dump()
        }

    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors()
        )

# --- WebSocket endpoint (ВАЖНО: используем менеджер) ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        # Отправляем приветственное сообщение
        await websocket.send_json({
            "type": "connection_established",
            "message": "Connected to sensor data stream",
            "timestamp": datetime.now().isoformat()
        })

        while True:
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
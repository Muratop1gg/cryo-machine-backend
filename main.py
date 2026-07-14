from contextlib import asynccontextmanager
import asyncio
import json
from datetime import datetime
import random
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette import status

import models


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


# --- Состояние процедуры ---
class ProcedureState:
    def __init__(self):
        self.is_running = False
        self.is_paused = False
        self.start_time = None
        self.elapsed_time = 0

    def start(self):
        self.is_running = True
        self.is_paused = False
        self.start_time = datetime.now()
        self.elapsed_time = 0
        print("🟢 Procedure started")

    def pause(self):
        if self.is_running and not self.is_paused:
            self.is_paused = True
            if self.start_time is not None:
                self.elapsed_time += (datetime.now() - self.start_time).total_seconds()
            print("⏸️ Procedure paused")

    def resume(self):
        if self.is_running and self.is_paused:
            self.is_paused = False
            self.start_time = datetime.now()
            print("▶️ Procedure resumed")

    def stop(self):
        if self.is_running:
            self.is_running = False
            self.is_paused = False
            self.elapsed_time = 0
            self.start_time = None
            print("⏹️ Procedure stopped")

    def get_status(self):
        if not self.is_running:
            return "stopped"
        if self.is_paused:
            return "paused"
        return "running"


procedure_state = ProcedureState()


# --- Генераторы данных ---
async def sensor_data_generator():
    sequence = 0
    # Начальная температура
    current_temp = random.uniform(-200, -100)
    
    while True:
        await asyncio.sleep(0.2)
        sequence += 1
        
        # Плавное изменение температуры (шаг ±0.5 градуса)
        # Но остаемся в диапазоне от -200 до -100
        change = random.uniform(-0.5, 0.5)
        current_temp = max(-200, min(-100, current_temp + change))
        
        ss = models.SystemStatusModel(
            currentMode="cooling",
            errorCode=[],
            SteamOnline=True,
            HoistOnline=True,
        )

        t = models.TelemetryModel(
            Temperature=models.TemperatureModel(
                SteamGenerator=0, 
                HeaterZone=0, 
                AirDuct=0, 
                Average=round(current_temp, 1),
                ChamberZone=0
            ),
            Environment=models.EnvironmentModel(
                AirDuctHumidity=0,
                ChamberHumidity=0,
                ChamberOxygen=0,
                NitrogenLevel=0
            ),
            vfdStatus=models.VFDStatusesModel(
                Steam=models.VFDModel(Frequency=0, ErrorCode=""), 
                Hoist=models.VFDModel(Frequency=0, ErrorCode="")
            ),
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
        "active_connections": len(manager.active_connections),
        "procedure_status": procedure_state.get_status()
    }


@app.post("/api/settings")
async def update_settings(settings: models.UpdateSettings):
    try:
        # Валидация значений
        if settings.TechnologicalSettings.WorkingTime <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WorkingTime must be greater than 0"
            )
        
        if settings.TechnologicalSettings.S1Temperature < -50 or \
                settings.TechnologicalSettings.S1Temperature > 150:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="S1Temperature out of range (-50 to 150)"
            )

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


# ========== ЭНДПОИНТЫ УПРАВЛЕНИЯ ПРОЦЕДУРОЙ ==========

@app.post("/api/procedure/start")
async def start_procedure(cmd: Optional[models.StartProcedure] = None):
    """Запуск процедуры"""
    try:
        if procedure_state.is_running and not procedure_state.is_paused:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procedure is already running"
            )

        # Если процедура на паузе, просто возобновляем
        if procedure_state.is_paused:
            procedure_state.resume()
            # Отправляем событие возобновления
            event = models.Event(EventType=102)  # Resume event
            await manager.broadcast_event(event)
            return {
                "status": "success",
                "message": "Procedure resumed",
                "data": {"procedure_status": procedure_state.get_status()}
            }

        # Запускаем новую процедуру
        procedure_state.start()
        
        # Отправляем событие запуска
        event = models.Event(EventType=100)  # Start event
        await manager.broadcast_event(event)
        
        return {
            "status": "success",
            "message": "Procedure started successfully",
            "data": {
                "procedure_status": procedure_state.get_status(),
                "start_time": procedure_state.start_time.isoformat() if procedure_state.start_time else None
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start procedure: {str(e)}"
        )

@app.post("/api/procedure/pause")
async def pause_procedure(cmd: Optional[models.PauseProcedure] = None):
    """Пауза процедуры"""
    try:
        if not procedure_state.is_running:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procedure is not running"
            )

        if procedure_state.is_paused:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procedure is already paused"
            )

        procedure_state.pause()
        
        # Отправляем событие паузы
        event = models.Event(EventType=101)  # Pause event
        await manager.broadcast_event(event)
        
        return {
            "status": "success",
            "message": "Procedure paused",
            "data": {
                "procedure_status": procedure_state.get_status(),
                "elapsed_time": procedure_state.elapsed_time
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause procedure: {str(e)}"
        )


@app.post("/api/procedure/resume")
async def resume_procedure(cmd: Optional[models.ResumeProcedure] = None):
    """Возобновление процедуры после паузы"""
    try:
        if not procedure_state.is_running:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procedure is not running"
            )

        if not procedure_state.is_paused:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procedure is not paused"
            )

        procedure_state.resume()
        
        # Отправляем событие возобновления
        event = models.Event(EventType=102)  # Resume event
        await manager.broadcast_event(event)
        
        return {
            "status": "success",
            "message": "Procedure resumed",
            "data": {
                "procedure_status": procedure_state.get_status(),
                "elapsed_time": procedure_state.elapsed_time
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume procedure: {str(e)}"
        )


@app.post("/api/procedure/stop")
async def stop_procedure(cmd: Optional[models.StopProcedure] = None):
    """Остановка процедуры"""
    try:
        if not procedure_state.is_running:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procedure is not running"
            )

        procedure_state.stop()
        
        # Отправляем событие остановки
        event = models.Event(EventType=103)  # Stop event
        await manager.broadcast_event(event)
        
        return {
            "status": "success",
            "message": "Procedure stopped",
            "data": {
                "procedure_status": procedure_state.get_status(),
                "total_elapsed_time": procedure_state.elapsed_time
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop procedure: {str(e)}"
        )


# --- WebSocket endpoint ---
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

        # Отправляем текущий статус процедуры
        await websocket.send_json({
            "type": "procedure_status",
            "data": {
                "status": procedure_state.get_status(),
                "is_running": procedure_state.is_running,
                "is_paused": procedure_state.is_paused,
                "elapsed_time": procedure_state.elapsed_time
            },
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


# ========== ДОПОЛНИТЕЛЬНЫЙ ЭНДПОИНТ ДЛЯ СТАТУСА ПРОЦЕДУРЫ ==========

@app.get("/api/procedure/status")
async def get_procedure_status():
    """Получение текущего статуса процедуры"""
    return {
        "status": procedure_state.get_status(),
        "is_running": procedure_state.is_running,
        "is_paused": procedure_state.is_paused,
        "start_time": procedure_state.start_time.isoformat() if procedure_state.start_time else None,
        "elapsed_time": procedure_state.elapsed_time
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
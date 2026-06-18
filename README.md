ИВЕНТ ПО ЗАПРОСУ С ФРОНТА (ОБЫЧНЫЕ)

```json
{
  "timestamp": "2026-06-17T17:12:45Z", // ISO 8601
  "system_status": {
    "current_mode": "autotest", // stdby autotest drying cooling working
    "error_code": null || [], // 0 ошибок нет, null -ошибки нет массив - список ошибок
    "vfd1_steam_online": true, // парогенератор для сервисного режима
    "vfd2_hoist_online": true // лебёдка
  },
  "telemetry": {
    "temperatures": {
      "t0_steam_generator": 45.2,
      "t1_heater_zone": 28.0,
      "t2_air_duct": 24.5,
      "t3_humidity_sensor": 23.8,
      "t4_chamber_zone": -12.4
    },
    "environment": {
      "h0_air_duct_humidity": 85.0,
      "h1_chamber_humidity": 40.5,
      "o0_chamber_oxygen": 20.9,
      "nitrogen_left": 10 // остаток азота тоже сюда надо
    },
    "vfd_status": {
      "vfd1": {
        "freq_hz": 30.0,
        "err_code": "" // null или str
      },
      "vfd2-status": { // hoist
        "freq_hz": 50.0,
        "direction": true, // true - подъемник вверх, false - вниз
        "err_code": "" // null или str
      }
    }
  }
}
```

ИВЕНТЫ С БЭКА ПО ЗАПРОСУ (БЫСТРЫЕ)

```json
"digital_inputs": {
    "pipe_hoist": {
      "lsw_top_emergency": false,
      "lsw_top_working": false,
      "lsw_bottom_working": true,
      "lsw_bottom_emergency": false
    },
    "patient_hoist": {
      "lsw_top_emergency": false,
      "lsw_top_working": false,
      "lsw_bottom_working": true,
      "lsw_bottom_emergency": false,
      "patient_present": true
    },
    "safety": {
      "estop_pressed": false,
      "cabinet_door_open": true
    }
  }
```

ИВЕНТ С БЭКА

"event_id": 20, // циферка ивенета

REST API POST с фронта

```json
{
  "mode_selection": {
    "mode": "cooling"
  },
  "technological_settings": {
    "time_s1_sec": 30, // работа 
    "time_s2_sec": 10, // ожидание
    "time_s3_sec": 5, // общая длительность процедуры
    "temperature_sp1": 75.0, // уставка s1
    "temperature_sp2": 30.0 // уставка s2
  },
  
  
}
```

Ивенты подъема спуска с фронта: 

```json
  "motion_commands": {
    "patient_hoist": true, // true - вверх, false - вниз, null - стоп
    "pipe_hoist": false // true - вверх, false - вниз, null - стоп
  },
```

Ивенты кнопок:

```json
"ui_buttons": {
    "btn_ok": false, // дублирование кнопок контроллера
    "btn_esc": false,
    "btn_reset_fault": false,
    "btn_bypass_confirm": false
},
```

Ивент на разблокировку без инета:
```json
"security": {
    "system_code_long": "sdfbjkhds1212367t21asd" // для разблокировки кода
}
```


СЕРВИСНОЕ МЕНЮ

перечисление концевиков
ошибки
ну и вывести всё остальное

управление:

разблок без инета
кнопки контроллера
кнопка запуска автокалибровки ()
уставки:

```json
{
  "mode_selection": {
    "mode": "cooling"
  },
  "technological_settings": {
    "time_s1_sec": 30, // работа 
    "time_s2_sec": 10, // ожидание
    "time_s3_sec": 5, // общая длительность процедуры
    "temperature_sp1": 75.0, // уставка s1
    "temperature_sp2": 30.0 // уставка s2
  }
}

Уведы:

Требование ручного нажатия кнопки estop, требование убедиться в надписи stdby на ПЧ (пробел - естоп)
Требование поместить вес на платформу подъемника пациента ()
Требование нажать на пульте все клавиши подряд (порядок высвечивается на дисплее, учитываются только правильные нажатия)



управление Исполнительными устройствами:

Двигатель нагнетателя - (ОИН-1, ТТР, aout1) - вкл/выкл, частота от 0 до 50
Двигатель парогенератора VFD1.1 (GD27,075, com1.1) - вкл/выкл, частота от 0 до 50, направление (туда - сюда)
Двигатель лебедки подъёмника пациента VFD1.2 (GD27,075, com1.2) - выкл/вверх вниз
Двигатель трубоподъемника (VDC24, opto1 - dir, opto2 - start) - выкл/вверх вниз
ТЭН 0.5кВт (ТТР, aout2) - вкл/выкл
Вентилятор вытяжки 0.05кВт (triac1) - вкл/выкл
Заслонка вытяжки (triac2) - открыть/закрыть
Светодиодная лента - выбор цвета, вкл/выкл

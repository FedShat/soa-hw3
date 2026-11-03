# Контракты

REST доступен на `http://localhost:8000`, Swagger — `/docs`, OpenAPI — `/openapi.json`. gRPC — `localhost:50051`, пакет `flight.v1`, исходный контракт — `proto/flight.proto`. Все пять RPC требуют metadata `x-api-key`, значение задаётся `GRPC_API_KEY`.

Все ID рейсов, бронирований и резерваций — UUID. `user_id` — непустая строка до 128 символов. Время передаётся как protobuf Timestamp и RFC 3339 в REST; дата поиска соответствует UTC. Цена — десятичная строка с двумя знаками после точки, арифметика выполняется через Decimal, хранение — PostgreSQL NUMERIC. Статусы в protobuf определены enum.

| REST | Назначение | Успех |
| --- | --- | --- |
| `GET /flights?origin=SVO&destination=LED&date=2026-11-11` | Поиск SCHEDULED-рейсов; дата необязательна | 200, массив |
| `GET /flights/{id}` | Получение рейса | 200 |
| `POST /bookings` | GetFlight → ReserveSeats → сохранение CONFIRMED | 201 |
| `GET /bookings/{id}` | Получение бронирования | 200 |
| `POST /bookings/{id}/cancel` | ReleaseReservation → сохранение CANCELLED | 200 |
| `GET /bookings?user_id=X` | Бронирования покупателя, новые первыми | 200, массив |
| `GET /health` | Проверка БД Booking Service и состояние circuit breaker | 200 |

Тело создания бронирования:

```json
{
  "user_id": "user-1",
  "flight_id": "00000000-0000-0000-0000-000000000001",
  "passenger_name": "Ivan Petrov",
  "passenger_email": "ivan@example.com",
  "seat_count": 2
}
```

| RPC | Ошибки предметной области |
| --- | --- |
| SearchFlights | INVALID_ARGUMENT при некорректном IATA, одинаковых аэропортах или Timestamp даты не на 00:00:00 UTC |
| GetFlight | INVALID_ARGUMENT для некорректного UUID; NOT_FOUND для отсутствующего рейса |
| ReserveSeats | INVALID_ARGUMENT для UUID или seat_count вне 1..1000000; NOT_FOUND; RESOURCE_EXHAUSTED при нехватке мест; FAILED_PRECONDITION для не-SCHEDULED рейса или отменённого booking_id; ALREADY_EXISTS при повторном booking_id с другими параметрами |
| ReleaseReservation | INVALID_ARGUMENT для некорректного UUID; повторный вызов и отсутствие резервации возвращают RELEASED |
| UpdateFlight | INVALID_ARGUMENT для некорректных значений или пустого обновления; NOT_FOUND; FAILED_PRECONDITION, если новая вместимость меньше числа занятых мест |

UpdateFlight позволяет изменить price, total_seats, status. Остальные поля рейса неизменяемы через этот контракт. EXPIRED предусмотрен контрактом и БД, автоматическое истечение подтверждённых резерваций не выполняется.

Все методы возвращают UNAUTHENTICATED при отсутствии или неверном ключе и UNAVAILABLE при недоступности БД. ReleaseReservation идемпотентен и сохраняет запрет будущего ReserveSeats с этим booking_id даже при отсутствии резервации. Это защищает компенсацию от позднего выполнения запроса.

| gRPC / источник | HTTP |
| --- | --- |
| INVALID_ARGUMENT / REST-валидация | 422 |
| NOT_FOUND | 404 |
| RESOURCE_EXHAUSTED, ALREADY_EXISTS, FAILED_PRECONDITION | 409 |
| UNAVAILABLE | 503 |
| DEADLINE_EXCEEDED | 504 |
| UNAUTHENTICATED, PERMISSION_DENIED между сервисами | 502 |
| Прочая ошибка gRPC | 502 |
| Открытый circuit breaker | 503, code CIRCUIT_OPEN |
| Недоступность БД Booking Service | 503 |

Повторная отмена уже CANCELLED-бронирования возвращает 409. Параллельные отмены не возвращают места дважды. Ошибка gRPC представлена JSON с `detail` и `code`; ошибки REST-валидации имеют стандартный формат FastAPI.

ReserveSeats идемпотентен по booking_id. POST /bookings создаёт новое бронирование для каждого нового HTTP-запроса; HTTP idempotency key в контракт не входит. Цена фиксируется из GetFlight до ReserveSeats, как требует сценарий задания.

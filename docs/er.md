# Схема данных

```mermaid
erDiagram
    AIRLINES ||--o{ FLIGHTS : operates
    FLIGHTS ||--o{ SEAT_RESERVATIONS : contains
    FLIGHTS ||..o{ BOOKINGS : referenced_by_id
    BOOKINGS ||..|| SEAT_RESERVATIONS : logical_booking_id
    BOOKINGS |o..o{ BOOKING_OPERATIONS : recovery

    AIRLINES {
        varchar code PK
        varchar name
    }

    FLIGHTS {
        uuid id PK
        varchar flight_number "UNIQUE with UTC departure date"
        varchar airline_code FK
        varchar origin "IATA"
        varchar destination "IATA"
        timestamptz departure_time
        timestamptz arrival_time
        integer total_seats "greater than zero"
        integer available_seats "between zero and total_seats"
        numeric price "positive, scale 2"
        varchar currency
        varchar status "SCHEDULED, DEPARTED, CANCELLED, COMPLETED"
    }

    SEAT_RESERVATIONS {
        uuid id PK
        uuid flight_id FK
        uuid booking_id UK "logical Booking reference"
        integer seat_count "greater than zero"
        varchar status "ACTIVE, RELEASED, EXPIRED"
        timestamptz created_at
    }

    BOOKINGS {
        uuid id PK
        varchar user_id "external user identifier"
        uuid flight_id "logical Flight reference"
        varchar passenger_name
        varchar passenger_email
        integer seat_count "greater than zero"
        numeric total_price "positive price snapshot"
        varchar currency
        varchar status "CONFIRMED, CANCELLED"
        timestamptz created_at
    }

    BOOKING_OPERATIONS {
        uuid id PK
        uuid booking_id "may precede Booking creation"
        varchar kind "CREATE, CANCEL"
        varchar state "PENDING, DONE"
        timestamptz created_at
    }

    RESERVATION_CANCELLATIONS {
        uuid booking_id PK
        timestamptz created_at
    }

    CACHE_REVISION {
        integer id PK "always 1"
        bigint revision
    }
```

`airlines`, `flights`, `seat_reservations`, `reservation_cancellations` и `cache_revision` находятся в PostgreSQL Flight Service. `bookings` и `booking_operations` находятся в отдельной PostgreSQL Booking Service. Сплошные линии обозначают локальные внешние ключи, пунктирные — логические связи через идентификаторы. Между базами нет внешних ключей и прямых запросов сервисов к чужим таблицам.

В устойчивом состоянии каждому созданному бронированию соответствует одна резервация; при компенсации неуспешной операции может остаться RELEASED-резервация без бронирования. Незавершённая операция CREATE существует до записи бронирования, поэтому `booking_operations.booking_id` намеренно не имеет FK.

Поля атомарны, неключевые атрибуты зависят от ключа своей сущности. Название авиакомпании вынесено в `airlines`: оно определяется кодом авиакомпании. Информация о маршруте не дублируется в бронировании. Данные пассажира описывают пассажира конкретной покупки; `user_id` идентифицирует покупателя и не определяет пассажира. Стоимость бронирования — самостоятельный исторический факт, она не зависит от текущей цены рейса. Отдельное поле departure_date не хранится: уникальность номера и UTC-даты задаёт функциональный индекс. Эти свойства обеспечивают 3NF.

CHECK-ограничения проверяют положительные цены и количество мест, диапазон доступных мест, допустимые статусы, форматы аэропортов и валют, разные аэропорты и порядок времён. `UNIQUE(booking_id)` запрещает две резервации одного бронирования. Счётчик доступных мест и резервация изменяются в одной транзакции с блокировкой рейса `SELECT FOR UPDATE`.

`reservation_cancellations` хранит запрет повторного резервирования для уже отменённого booking_id. Он нужен и при отсутствии резервации: отложенный ReserveSeats после таймаута не сможет заново занять места после компенсации. `cache_revision` изменяется транзакционно вместе с данными рейсов и защищает чтение кеша после сбоя Redis.

-- Slot inventory: the Booking Service's own copy of every published slot, built from
-- SlotPublished events. It is the only place that decides whether a slot is free.
CREATE TABLE slot_inventory (
    slot_id       uuid PRIMARY KEY,
    merchant_id   uuid         NOT NULL,
    resource_id   uuid         NOT NULL,
    resource_name varchar(200) NOT NULL,
    resource_type varchar(50)  NOT NULL,
    start_time    timestamptz  NOT NULL,
    end_time      timestamptz  NOT NULL,
    local_date    date         NOT NULL,
    status        varchar(16)  NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'BOOKED')),
    version       integer      NOT NULL DEFAULT 0,
    updated_at    timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE bookings (
    booking_id        uuid PRIMARY KEY,
    reference         varchar(16)  NOT NULL UNIQUE,
    slot_id           uuid         NOT NULL REFERENCES slot_inventory (slot_id),
    merchant_id       uuid         NOT NULL,
    customer_id       varchar(128) NOT NULL,
    customer_username varchar(128) NOT NULL,
    status            varchar(16)  NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    idempotency_key   varchar(128) NOT NULL,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    cancelled_at      timestamptz,
    -- A retried request with the same key returns the original booking instead of a new one.
    CONSTRAINT bookings_idempotency UNIQUE (customer_id, idempotency_key)
);

-- Last line of defence: at most one active booking per slot, whatever the application does.
CREATE UNIQUE INDEX bookings_one_active_per_slot ON bookings (slot_id) WHERE status = 'CONFIRMED';
CREATE INDEX bookings_customer_idx ON bookings (customer_id, created_at DESC);
CREATE INDEX bookings_merchant_idx ON bookings (merchant_id, created_at DESC);

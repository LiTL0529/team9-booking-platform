CREATE TABLE notifications (
    notification_id uuid PRIMARY KEY,
    customer_id     varchar(128) NOT NULL,
    kind            varchar(40)  NOT NULL,
    title           varchar(200) NOT NULL,
    body            text         NOT NULL,
    booking_id      uuid,
    source_event_id uuid         NOT NULL UNIQUE,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    read_at         timestamptz
);
CREATE INDEX notifications_customer_idx ON notifications (customer_id, created_at DESC);

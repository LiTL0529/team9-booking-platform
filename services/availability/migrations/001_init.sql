-- Read model (the query side of CQRS), built only from events. It may lag a few seconds
-- behind the Booking Service, which remains the authority on whether a slot is free.
CREATE TABLE merchants_view (
    merchant_id uuid PRIMARY KEY,
    name        varchar(200) NOT NULL,
    slug        varchar(80)  NOT NULL,
    updated_at  timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE slots_view (
    slot_id       uuid PRIMARY KEY,
    merchant_id   uuid         NOT NULL,
    resource_id   uuid         NOT NULL,
    resource_name varchar(200) NOT NULL,
    resource_type varchar(50)  NOT NULL,
    start_time    timestamptz  NOT NULL,
    end_time      timestamptz  NOT NULL,
    local_date    date         NOT NULL,
    status        varchar(16)  NOT NULL DEFAULT 'AVAILABLE',
    -- Slot version from the Booking Service; older events never overwrite newer state.
    version       integer      NOT NULL DEFAULT 0,
    updated_at    timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX slots_view_search_idx ON slots_view (local_date, resource_type, merchant_id, start_time);

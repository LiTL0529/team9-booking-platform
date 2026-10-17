CREATE TABLE resources (
    resource_id   uuid PRIMARY KEY,
    merchant_id   uuid         NOT NULL,
    name          varchar(200) NOT NULL,
    resource_type varchar(50)  NOT NULL,
    description   text         NOT NULL DEFAULT '',
    timezone      varchar(64)  NOT NULL DEFAULT 'Asia/Singapore',
    created_by    varchar(128) NOT NULL,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (merchant_id, name)
);
CREATE INDEX resources_merchant_idx ON resources (merchant_id);

-- The database itself guarantees that slots of one resource never overlap: every slot
-- starts on a whole hour and lasts exactly one hour, so two slots overlap only if they
-- share a start time, which the unique constraint forbids. (Variable-length slots, out of
-- scope, would switch this to an EXCLUDE USING gist constraint with btree_gist.)
CREATE TABLE time_slots (
    slot_id     uuid PRIMARY KEY,
    resource_id uuid        NOT NULL REFERENCES resources (resource_id),
    merchant_id uuid        NOT NULL,
    start_time  timestamptz NOT NULL,
    end_time    timestamptz NOT NULL,
    local_date  date        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT time_slots_whole_hour CHECK (date_trunc('hour', start_time) = start_time),
    CONSTRAINT time_slots_one_hour CHECK (end_time = start_time + interval '1 hour'),
    CONSTRAINT time_slots_no_overlap UNIQUE (resource_id, start_time)
);

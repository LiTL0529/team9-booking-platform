CREATE TABLE merchants (
    merchant_id   uuid PRIMARY KEY,
    name          varchar(200) NOT NULL,
    slug          varchar(80)  NOT NULL UNIQUE,
    contact_email varchar(254) NOT NULL,
    status        varchar(20)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    created_at    timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    membership_id uuid PRIMARY KEY,
    merchant_id   uuid         NOT NULL REFERENCES merchants (merchant_id),
    username      varchar(128) NOT NULL,
    role          varchar(32)  NOT NULL CHECK (role IN ('merchant_admin', 'merchant_staff')),
    sync_status   varchar(20)  NOT NULL DEFAULT 'PENDING' CHECK (sync_status IN ('PENDING', 'SYNCED')),
    created_at    timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (merchant_id, username)
);

-- A user belongs to at most one merchant, because the merchant travels as a single token claim.
CREATE UNIQUE INDEX memberships_one_merchant_per_user ON memberships (username);

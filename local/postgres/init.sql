-- One database and one login per service, as on the shared RDS instance in AWS.
-- Local development passwords only; AWS passwords live in Secrets Manager.
CREATE ROLE merchant_svc WITH LOGIN PASSWORD 'merchant_local';
CREATE ROLE catalogue_svc WITH LOGIN PASSWORD 'catalogue_local';
CREATE ROLE availability_svc WITH LOGIN PASSWORD 'availability_local';
CREATE ROLE booking_svc WITH LOGIN PASSWORD 'booking_local';
CREATE ROLE notification_svc WITH LOGIN PASSWORD 'notification_local';

CREATE DATABASE merchant OWNER merchant_svc;
CREATE DATABASE catalogue OWNER catalogue_svc;
CREATE DATABASE availability OWNER availability_svc;
CREATE DATABASE booking OWNER booking_svc;
CREATE DATABASE notification OWNER notification_svc;

REVOKE ALL ON DATABASE merchant FROM PUBLIC;
REVOKE ALL ON DATABASE catalogue FROM PUBLIC;
REVOKE ALL ON DATABASE availability FROM PUBLIC;
REVOKE ALL ON DATABASE booking FROM PUBLIC;
REVOKE ALL ON DATABASE notification FROM PUBLIC;

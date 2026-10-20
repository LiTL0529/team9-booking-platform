# Public API documentation

Open `/api-docs.html` on the deployed web origin to browse operations and download the OpenAPI JSON for each service. The page reads the existing web client configuration and makes a request through the same gateway as the booking application.

The versioned specification endpoints are:

| Service | Specification |
| --- | --- |
| Merchant | `/v1/docs/merchant/openapi.json` |
| Catalogue | `/v1/docs/catalogue/openapi.json` |
| Availability | `/v1/docs/availability/openapi.json` |
| Booking | `/v1/docs/booking/openapi.json` |
| Notification | `/v1/docs/notification/openapi.json` |

Partners supply their existing `x-api-key` header to fetch a specification. These read-only documentation endpoints do not require a user token. Authentication, ownership checks and API-key requirements on business routes are unchanged.

On 20 October 2026, all five deployed specifications returned HTTP 200 and matched the repository contracts after excluding the build version. Requests without an API key returned HTTP 403. Evidence: `.local/acceptance/api-documentation.json`.

# Booking Service

Owns slot inventory, bookings and the transactional outbox. It is the only place that decides
whether a slot can be booked.

- Create: one local transaction claims the slot (`AVAILABLE` -> `BOOKED`), inserts the booking and
  its `BookingConfirmed` event into the outbox, then commits. A taken slot returns 409.
- Retries: the same `Idempotency-Key` returns the original booking.
- Events: consumes `SlotPublished`; publishes `BookingConfirmed` and `BookingCancelled`.

Run the tests: `python -m pytest services/booking/tests`

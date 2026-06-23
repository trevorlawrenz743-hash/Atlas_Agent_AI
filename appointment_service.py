from dataclasses import dataclass

from repositories import AppointmentRequestRepository


@dataclass(frozen=True)
class AppointmentRequestResult:
    status: str
    message: str
    appointment_request_id: int | None = None


class AppointmentService:
    def __init__(self, session):
        self.session = session
        self.appointment_requests = AppointmentRequestRepository(session)

    def request_appointment(self, business_id, customer_id, service_request_id, preferred_time, notes=""):
        if not preferred_time:
            return AppointmentRequestResult(
                status="not_requested",
                message="No preferred time was provided during the call.",
            )

        appointment = self.appointment_requests.create_requested_time(
            business_id=business_id,
            customer_id=customer_id,
            service_request_id=service_request_id,
            requested_time_text=preferred_time,
            notes=notes,
        )
        return AppointmentRequestResult(
            status="requested",
            message=(
                "Preferred time saved. Calendar availability has not been checked yet, "
                "so this is not a confirmed appointment."
            ),
            appointment_request_id=appointment.id,
        )

    def check_availability(self, *_args, **_kwargs):
        return AppointmentRequestResult(
            status="not_connected",
            message="Calendar availability is not connected yet.",
        )

    def create_calendar_event(self, *_args, **_kwargs):
        return AppointmentRequestResult(
            status="not_connected",
            message="Calendar event creation is not connected yet.",
        )

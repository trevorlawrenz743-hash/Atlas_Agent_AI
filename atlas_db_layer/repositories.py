import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    AppointmentRequest,
    Business,
    BusinessPhoneNumber,
    Call,
    Customer,
    ServiceRequest,
)


def normalize_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


class BusinessRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_twilio_number(self, twilio_number):
        normalized = normalize_phone(twilio_number)
        statement = (
            select(Business)
            .join(BusinessPhoneNumber)
            .where(BusinessPhoneNumber.twilio_number == normalized)
            .where(BusinessPhoneNumber.active.is_(True))
            .where(Business.active.is_(True))
        )
        return self.session.execute(statement).scalar_one_or_none()

    def create_business(
        self,
        name,
        twilio_number,
        assistant_name="Atlas",
        timezone="America/Chicago",
        industry="hvac",
        service_areas="",
        notification_email="",
        greeting_script="",
        closing_script="",
    ):
        business = Business(
            name=name,
            greeting_name=name,
            assistant_name=assistant_name,
            timezone=timezone,
            industry=industry,
            service_areas=service_areas,
            notification_email=notification_email,
            greeting_script=greeting_script,
            closing_script=closing_script,
        )
        self.session.add(business)
        self.session.flush()
        self.session.add(
            BusinessPhoneNumber(
                business_id=business.id,
                twilio_number=normalize_phone(twilio_number),
            )
        )
        self.session.flush()
        return business


class CustomerRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_phone(self, business_id, phone):
        statement = select(Customer).where(
            Customer.business_id == business_id,
            Customer.phone == normalize_phone(phone),
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_or_create_from_lead(self, business_id, lead, from_phone):
        phone = normalize_phone(lead.get("phone") or from_phone)
        customer = self.get_by_phone(business_id, phone)
        if not customer:
            customer = Customer(business_id=business_id, phone=phone)
            self.session.add(customer)
            self.session.flush()

        name_parts = (lead.get("name") or "").split()
        if name_parts:
            customer.first_name = name_parts[0]
            customer.last_name = " ".join(name_parts[1:])
        if lead.get("email") and lead["email"] not in {"Skipped", "Can add by SMS", "Review by SMS"}:
            customer.email = lead["email"]
        if lead.get("address"):
            customer.last_service_address = lead["address"]
        if lead.get("zip_code"):
            customer.last_service_zip = lead["zip_code"]

        self.session.flush()
        return customer

    def update_customer_details(self, customer_id, name="", email="", service_address="", service_zip=""):
        customer = self.session.get(Customer, customer_id)
        if not customer:
            return None

        name_parts = (name or "").split()
        if name_parts:
            customer.first_name = name_parts[0]
            customer.last_name = " ".join(name_parts[1:])
        if email:
            customer.email = email
        if service_address:
            customer.last_service_address = service_address
        if service_zip:
            customer.last_service_zip = service_zip

        self.session.flush()
        return customer


class CallRepository:
    def __init__(self, session: Session):
        self.session = session

    def save_completed_call(self, business_id, customer_id, call_sid, from_phone, to_phone, transcript):
        call = Call(
            business_id=business_id,
            customer_id=customer_id,
            twilio_call_sid=call_sid,
            from_phone=normalize_phone(from_phone),
            to_phone=normalize_phone(to_phone),
            transcript_json=json.dumps(transcript or []),
            status="completed",
        )
        self.session.add(call)
        self.session.flush()
        return call

    def get_by_call_sid(self, call_sid):
        statement = select(Call).where(Call.twilio_call_sid == call_sid)
        return self.session.execute(statement).scalar_one_or_none()


class ServiceRequestRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_from_lead(self, business_id, customer_id, call_id, lead):
        request = ServiceRequest(
            business_id=business_id,
            customer_id=customer_id,
            call_id=call_id,
            category=lead.get("category", ""),
            priority=lead.get("priority", "Normal"),
            issue_summary=lead.get("issue_summary") or lead.get("issue") or "",
            service_address=lead.get("address", ""),
            service_zip=lead.get("zip_code", ""),
            preferred_time=lead.get("preferred_time", ""),
            system_status=lead.get("system_status", ""),
            sms_review_required=bool(lead.get("sms_review_required")),
        )
        self.session.add(request)
        self.session.flush()
        return request

    def get_by_call_id(self, call_id):
        statement = (
            select(ServiceRequest)
            .where(ServiceRequest.call_id == call_id)
            .order_by(ServiceRequest.id.desc())
        )
        return self.session.execute(statement).scalars().first()

    def update_review_details(
        self,
        service_request_id,
        service_address="",
        service_zip="",
        issue_summary="",
        preferred_time="",
    ):
        request = self.session.get(ServiceRequest, service_request_id)
        if not request:
            return None

        if service_address:
            request.service_address = service_address
        if service_zip:
            request.service_zip = service_zip
        if issue_summary:
            request.issue_summary = issue_summary
        if preferred_time:
            request.preferred_time = preferred_time
        request.sms_review_required = False
        request.status = "reviewed"

        self.session.flush()
        return request


class AppointmentRequestRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_requested_time(self, business_id, customer_id, service_request_id, requested_time_text, notes=""):
        appointment = AppointmentRequest(
            business_id=business_id,
            customer_id=customer_id,
            service_request_id=service_request_id,
            requested_time_text=requested_time_text or "",
            status="requested",
            notes=notes,
        )
        self.session.add(appointment)
        self.session.flush()
        return appointment

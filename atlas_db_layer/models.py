from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    assistant_name: Mapped[str] = mapped_column(String(80), default="Atlas", nullable=False)
    greeting_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(80), default="hvac", nullable=False)
    notification_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="America/Chicago", nullable=False)
    service_areas: Mapped[str] = mapped_column(Text, default="", nullable=False)
    greeting_script: Mapped[str] = mapped_column(Text, default="", nullable=False)
    closing_script: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    phone_numbers: Mapped[list["BusinessPhoneNumber"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


class BusinessPhoneNumber(Base):
    __tablename__ = "business_phone_numbers"
    __table_args__ = (UniqueConstraint("twilio_number", name="uq_business_phone_twilio_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    twilio_number: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    business: Mapped[Business] = relationship(back_populates="phone_numbers")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("business_id", "phone", name="uq_customer_business_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    first_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    last_service_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_service_zip: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (UniqueConstraint("twilio_call_sid", name="uq_call_twilio_call_sid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    twilio_call_sid: Mapped[str] = mapped_column(String(128), nullable=False)
    from_phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    to_phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    transcript_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey("calls.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(40), default="Normal", nullable=False)
    issue_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    service_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    service_zip: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    preferred_time: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    system_status: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="new", nullable=False)
    sms_review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AppointmentRequest(Base):
    __tablename__ = "appointment_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    service_request_id: Mapped[int | None] = mapped_column(ForeignKey("service_requests.id"), nullable=True)
    requested_time_text: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    calendar_provider: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    calendar_event_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="requested", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

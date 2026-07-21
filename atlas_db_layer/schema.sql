CREATE TABLE businesses (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    assistant_name VARCHAR(80) NOT NULL DEFAULT 'Atlas',
    greeting_name VARCHAR(255) NOT NULL,
    industry VARCHAR(80) NOT NULL DEFAULT 'hvac',
    notification_email VARCHAR(255) NOT NULL DEFAULT '',
    timezone VARCHAR(80) NOT NULL DEFAULT 'America/Chicago',
    service_areas TEXT NOT NULL DEFAULT '',
    greeting_script TEXT NOT NULL DEFAULT '',
    closing_script TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE business_phone_numbers (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    twilio_number VARCHAR(32) NOT NULL UNIQUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    phone VARCHAR(32) NOT NULL,
    first_name VARCHAR(120) NOT NULL DEFAULT '',
    last_name VARCHAR(120) NOT NULL DEFAULT '',
    email VARCHAR(255) NOT NULL DEFAULT '',
    last_service_address TEXT NOT NULL DEFAULT '',
    last_service_zip VARCHAR(20) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE (business_id, phone)
);

CREATE TABLE calls (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_id INTEGER REFERENCES customers(id),
    twilio_call_sid VARCHAR(128) NOT NULL UNIQUE,
    from_phone VARCHAR(32) NOT NULL DEFAULT '',
    to_phone VARCHAR(32) NOT NULL DEFAULT '',
    transcript_json TEXT NOT NULL DEFAULT '[]',
    status VARCHAR(40) NOT NULL DEFAULT 'completed',
    started_at TIMESTAMP,
    completed_at TIMESTAMP NOT NULL
);

CREATE TABLE service_requests (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_id INTEGER REFERENCES customers(id),
    call_id INTEGER REFERENCES calls(id),
    category VARCHAR(80) NOT NULL DEFAULT '',
    priority VARCHAR(40) NOT NULL DEFAULT 'Normal',
    issue_summary TEXT NOT NULL DEFAULT '',
    service_address TEXT NOT NULL DEFAULT '',
    service_zip VARCHAR(20) NOT NULL DEFAULT '',
    preferred_time VARCHAR(255) NOT NULL DEFAULT '',
    system_status TEXT NOT NULL DEFAULT '',
    status VARCHAR(40) NOT NULL DEFAULT 'new',
    sms_review_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE appointment_requests (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_id INTEGER REFERENCES customers(id),
    service_request_id INTEGER REFERENCES service_requests(id),
    requested_time_text VARCHAR(255) NOT NULL DEFAULT '',
    calendar_provider VARCHAR(80) NOT NULL DEFAULT '',
    calendar_event_id VARCHAR(255) NOT NULL DEFAULT '',
    status VARCHAR(40) NOT NULL DEFAULT 'requested',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

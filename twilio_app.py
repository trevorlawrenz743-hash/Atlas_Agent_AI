import json
import os
import smtplib
import sys
import threading
from urllib import request as url_request
from urllib.error import HTTPError, URLError
from email.message import EmailMessage
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, request
from twilio.rest import Client
from twilio.twiml.voice_response import Gather, VoiceResponse

from ai_receptionist import AIReceptionist
import ai_receptionist


load_dotenv()

TWILIO_APP_VERSION = "atlas-first-question-faq-2026-07-20"

print("LOADED AI FILE:", ai_receptionist.__file__)
print("AI DIALOGUE VERSION:", AIReceptionist.DIALOGUE_VERSION)
print("=" * 72)
print("RUNNING TWILIO APP FROM:", __file__)
print("RUNNING TWILIO APP VERSION:", TWILIO_APP_VERSION)
print("RUNNING AI MODULE FROM:", ai_receptionist.__file__)
print("RUNNING AI DIALOGUE VERSION:", AIReceptionist.DIALOGUE_VERSION)
print("=" * 72)
print("TWILIO ACCOUNT SID FOUND:", bool(os.getenv("TWILIO_ACCOUNT_SID")))
print("TWILIO AUTH TOKEN FOUND:", bool(os.getenv("TWILIO_AUTH_TOKEN")))
print("TWILIO PHONE NUMBER FOUND:", bool(os.getenv("TWILIO_PHONE_NUMBER")))

app = Flask(__name__)

sessions = {}
completed_call_sids = set()


TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TWILIO_TTS_VOICE = os.getenv("TWILIO_TTS_VOICE", "Polly.Brian-Generative")
TWILIO_TTS_LANGUAGE = os.getenv("TWILIO_TTS_LANGUAGE", "en-GB")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
REVIEW_BASE_URL = os.getenv("REVIEW_BASE_URL", PUBLIC_BASE_URL).rstrip("/")
SMS_FOLLOWUP_ENABLED = os.getenv("SMS_FOLLOWUP_ENABLED", "0") == "1"
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").lower()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)
BUSINESS_NOTIFICATION_EMAIL = os.getenv("BUSINESS_NOTIFICATION_EMAIL", "")
print(
    "[EMAIL CONFIG]",
    {
        "provider": EMAIL_PROVIDER,
        "resend_api_key_found": bool(RESEND_API_KEY),
        "smtp_host_found": bool(SMTP_HOST),
        "from_email_found": bool(SMTP_FROM_EMAIL),
        "fallback_business_email_found": bool(BUSINESS_NOTIFICATION_EMAIL),
    },
)
OUTPUT_DIR = Path(__file__).resolve().parent
DB_LAYER_DIR = OUTPUT_DIR / "atlas_db_layer"
if DB_LAYER_DIR.exists():
    sys.path.insert(0, str(DB_LAYER_DIR))

try:
    from appointment_service import AppointmentService
    from business_config import (
        DEFAULT_BUSINESS_CONFIG,
        apply_business_config_to_bot,
        get_business_config_for_call,
    )
    from database import init_db, session_scope
    from models import Customer
    from repositories import (
        AppointmentRequestRepository,
        CallRepository,
        CustomerRepository,
        ServiceRequestRepository,
    )

    DB_AVAILABLE = True
    DB_IMPORT_ERROR = ""
except Exception as exc:
    AppointmentService = None
    DEFAULT_BUSINESS_CONFIG = None
    apply_business_config_to_bot = None
    get_business_config_for_call = None
    init_db = None
    session_scope = None
    Customer = None
    AppointmentRequestRepository = None
    CallRepository = None
    CustomerRepository = None
    ServiceRequestRepository = None
    DB_AVAILABLE = False
    DB_IMPORT_ERROR = repr(exc)

LEADS_PATH = OUTPUT_DIR / "twilio_leads.jsonl"
TRANSCRIPTS_PATH = OUTPUT_DIR / "twilio_call_transcripts.jsonl"
TRANSCRIPTS_MD_PATH = OUTPUT_DIR / "twilio_call_transcripts.md"
BOT_DIALOGUE_PATH = OUTPUT_DIR / "twilio_bot_dialogue.md"
print("BOT DIALOGUE LOG:", BOT_DIALOGUE_PATH)
print("DATABASE LAYER AVAILABLE:", DB_AVAILABLE)
if DB_IMPORT_ERROR:
    print("DATABASE LAYER IMPORT ERROR:", DB_IMPORT_ERROR)

if DB_AVAILABLE and os.getenv("DB_AUTO_INIT", "1") == "1":
    try:
        init_db()
        print("DATABASE TABLE CHECK: ok")
    except Exception as exc:
        print("DATABASE TABLE CHECK ERROR:", repr(exc))


@app.before_request
def log_request():
    print(f"[REQUEST] {request.method} {request.path}")
    if request.form:
        print("[FORM]", dict(request.form))


def twilio_client():
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return None
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def xml_response(twiml):
    return Response(str(twiml), mimetype="text/xml")


def say(target, text):
    target.say(text, voice=TWILIO_TTS_VOICE, language=TWILIO_TTS_LANGUAGE)


def get_call_sid():
    return request.form.get("CallSid", "local-dev")


def get_or_create_bot(call_sid):
    if call_sid not in sessions:
        sessions[call_sid] = {
            "bot": AIReceptionist(),
            "transcript": [],
            "last_prompt": "",
            "business_config": None,
            "returning_customer": None,
        }
    return sessions[call_sid]["bot"]


def get_transcript(call_sid):
    if call_sid not in sessions:
        sessions[call_sid] = {
            "bot": AIReceptionist(),
            "transcript": [],
            "last_prompt": "",
            "business_config": None,
            "returning_customer": None,
        }
    return sessions[call_sid]["transcript"]


def split_customer_name(customer):
    name = " ".join(
        part for part in [getattr(customer, "first_name", ""), getattr(customer, "last_name", "")] if part
    )
    return name.strip()


def apply_returning_customer_to_bot(bot, customer):
    if not customer:
        return

    name = split_customer_name(customer)
    if name:
        bot.lead["name"] = name
    if getattr(customer, "phone", ""):
        bot.lead["phone"] = customer.phone
        bot.lead["phone_confirmed"] = True
        bot.lead["verification_status"] = "Caller ID Matched"
    if getattr(customer, "email", ""):
        bot.lead["email"] = customer.email
    if getattr(customer, "last_service_address", ""):
        bot.lead["address"] = customer.last_service_address


def setup_call_context(call_sid, bot):
    session_state = sessions.get(call_sid, {})
    if session_state.get("business_config") is not None:
        return session_state

    form_payload = dict(request.form)
    fallback_config = DEFAULT_BUSINESS_CONFIG if DB_AVAILABLE else None
    session_state["business_config"] = fallback_config
    session_state["returning_customer"] = None

    if not DB_AVAILABLE:
        return session_state

    try:
        with session_scope() as db_session:
            business_config = get_business_config_for_call(db_session, form_payload.get("To", ""))
            apply_business_config_to_bot(bot, business_config)
            session_state["business_config"] = business_config

            if business_config.business_id:
                customer = CustomerRepository(db_session).get_by_phone(
                    business_config.business_id,
                    form_payload.get("From", ""),
                )
                if customer:
                    session_state["returning_customer"] = {
                        "id": customer.id,
                        "first_name": customer.first_name,
                        "last_name": customer.last_name,
                        "phone": customer.phone,
                        "email": customer.email,
                        "last_service_address": customer.last_service_address,
                    }
                    apply_returning_customer_to_bot(bot, customer)
    except Exception as exc:
        print("[DB CONTEXT ERROR]", repr(exc))

    return session_state


def returning_customer_greeting(bot, customer_snapshot):
    if not customer_snapshot:
        return None

    first_name = customer_snapshot.get("first_name") or bot.lead.get("name", "").split()[0]
    if not first_name:
        return None

    return (
        f"Thank you for calling {bot.company_info['name']}. "
        f"I am {bot.company_info.get('assistant_name', 'Atlas')}, your virtual assistant. "
        f"Welcome back, {first_name}. How can I help you today?"
    )


def add_transcript_turn(call_sid, customer=None, receptionist=None, metadata=None):
    transcript = get_transcript(call_sid)
    transcript.append(
        {
            "customer": customer,
            "receptionist": receptionist,
            "metadata": metadata or {},
        }
    )


def remember_prompt(call_sid, prompt):
    if call_sid in sessions:
        sessions[call_sid]["last_prompt"] = prompt


def lead_has_minimum_for_business_email(bot):
    return bool(
        bot.lead.get("phone_confirmed")
        and bot.lead.get("phone")
        and (bot.lead.get("issue_summary") or bot.lead.get("issue"))
    )


def force_complete_with_current_lead(bot):
    if bot.current_step == "complete":
        return bot.submit_request()

    bot.lead["possible_transcription_error"] = True
    bot.lead["sms_review_required"] = True
    if not bot.lead.get("preferred_time"):
        bot.lead["preferred_time"] = "Not collected by phone"
    if not bot.lead.get("address"):
        bot.lead["address"] = "Needs team review"
    if not bot.lead.get("system_status") and bot.lead.get("category") == "Support":
        bot.lead["system_status"] = "Needs team review"
    return bot.submit_request()


def log_bot_dialogue(call_sid, prompt, step, source):
    with BOT_DIALOGUE_PATH.open("a", encoding="utf-8") as file:
        file.write(f"\n## {call_sid}\n\n")
        file.write(f"Source: {source}\n\n")
        file.write(f"Step: {step}\n\n")
        file.write(f"Receptionist: {prompt}\n")


def apply_voice_channel_shortcuts(bot, prompt):
    if bot.current_step != "email":
        return prompt

    bot.lead["email"] = "Not collected by phone"
    next_prompt = bot.next_question()
    return next_prompt


def normalize_inbound_for_step(bot):
    digits = request.form.get("Digits", "").strip()
    speech = request.form.get("SpeechResult", "").strip()

    if digits:
        if bot.current_step == "phone":
            return digits
        if bot.current_step == "phone_confirmation":
            return {"1": "yes", "2": "no"}.get(digits, digits)
        if bot.awaiting_anything_else:
            return {"1": "no"}.get(digits, digits)
        if bot.current_step in {"confirmation", "preferred_time"}:
            return {"1": "yes", "2": "no"}.get(digits, digits)

    return speech or digits


def say_in_chunks(response, text):
    parts = []
    current = ""
    for sentence in text.split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        if not sentence.endswith("."):
            sentence += "."
        if len(current) + len(sentence) > 320:
            if current:
                parts.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current.strip())

    for part in parts or [text]:
        say(response, part)
        response.pause(length=1)


def build_twiml(prompt, bot, call_sid):
    response = VoiceResponse()

    if bot.current_step == "complete":
        say_in_chunks(response, prompt)
        response.hangup()
        return response

    if bot.current_step == "phone":
        gather = Gather(
            input="dtmf",
            action="/gather",
            method="POST",
            num_digits=10,
            timeout=10,
            action_on_empty_result=False,
        )
        say(gather, "Please enter the best callback phone number, including area code.")
        response.append(gather)
        say(response, "I missed the phone number. Let me ask that again.")
        response.redirect(f"/repeat/{call_sid}", method="POST")
        return response

    if bot.current_step == "phone_confirmation":
        gather = Gather(
            input="dtmf speech",
            action="/gather",
            method="POST",
            num_digits=1,
            timeout=6,
            speech_timeout="auto",
            action_on_empty_result=False,
        )
        say(gather, prompt + " Press 1 for yes, or 2 to enter it again.")
        response.append(gather)
        response.redirect(f"/repeat/{call_sid}", method="POST")
        return response

    if bot.current_step == "confirmation":
        gather = Gather(
            input="speech",
            action="/gather",
            method="POST",
            timeout=8,
            speech_timeout="auto",
            action_on_empty_result=False,
        )
        say(gather, prompt)
        response.append(gather)
        response.redirect(f"/repeat/{call_sid}", method="POST")
        return response

    if bot.awaiting_anything_else:
        gather = Gather(
            input="dtmf speech",
            action="/gather",
            method="POST",
            num_digits=1,
            timeout=8,
            speech_timeout="auto",
            action_on_empty_result=False,
        )
        say(gather, prompt + " Press 1 for no, or say what you want to add.")
        response.append(gather)
        response.redirect(f"/repeat/{call_sid}", method="POST")
        return response

    gather = Gather(
        input="speech",
        action="/gather",
        method="POST",
        timeout=8,
        speech_timeout="auto",
        action_on_empty_result=False,
    )
    say(gather, prompt)
    response.append(gather)
    say(response, "I missed that. Let me ask that again.")
    response.redirect(f"/repeat/{call_sid}", method="POST")
    return response


def build_review_url(call_sid):
    if not REVIEW_BASE_URL:
        return ""
    return f"{REVIEW_BASE_URL}/review/{call_sid}"


def send_review_sms(bot, call_sid):
    if not SMS_FOLLOWUP_ENABLED:
        print("[SMS DISABLED] SMS follow-up is disabled for this deployment.")
        bot.lead["sms_sent"] = False
        return False

    if not bot.lead.get("phone_confirmed") or not bot.lead.get("phone"):
        print("[SMS SKIPPED] Phone number is not confirmed.")
        bot.lead["sms_sent"] = False
        return False

    if not TWILIO_PHONE_NUMBER:
        print("[SMS SKIPPED] TWILIO_PHONE_NUMBER is missing.")
        bot.lead["sms_sent"] = False
        return False

    client = twilio_client()
    if not client:
        print("[SMS SKIPPED] Twilio credentials are missing.")
        bot.lead["sms_sent"] = False
        return False

    review_url = build_review_url(call_sid)
    company_name = bot.lead.get("company_name") or "Atlas"
    if review_url:
        body = f"{company_name}: Review or update your request here: {review_url}"
    else:
        body = f"{company_name}: We received your request. Reply with any corrections or updates."

    client.messages.create(
        body=body,
        from_=TWILIO_PHONE_NUMBER,
        to="+1" + bot.lead["phone"],
    )
    bot.lead["sms_sent"] = True
    return True


def get_company_name_for_form_payload(form_payload):
    if not DB_AVAILABLE:
        return "Atlas"

    try:
        with session_scope() as db_session:
            business_config = get_business_config_for_call(db_session, form_payload.get("To", ""))
            return business_config.company_name or "Atlas"
    except Exception as exc:
        print("[DB COMPANY LOOKUP ERROR]", repr(exc))
        return "Atlas"


def get_business_config_for_form_payload(form_payload):
    if not DB_AVAILABLE:
        return None

    try:
        with session_scope() as db_session:
            return get_business_config_for_call(db_session, form_payload.get("To", ""))
    except Exception as exc:
        print("[DB BUSINESS LOOKUP ERROR]", repr(exc))
        return None


def get_notification_email_for_form_payload(form_payload):
    business_config = get_business_config_for_form_payload(form_payload)
    business_notification_email = getattr(business_config, "notification_email", "")
    if business_notification_email:
        return business_notification_email
    return BUSINESS_NOTIFICATION_EMAIL


def build_notification_email_body(call_sid, lead, transcript, form_payload):
    lines = [
        f"Atlas captured a completed call for {lead.get('company_name', 'the business')}.",
        "",
        f"Call SID: {call_sid}",
        f"From: {form_payload.get('From', '')}",
        f"To: {form_payload.get('To', '')}",
        "",
        "Lead details:",
        f"Name: {lead.get('name', '')}",
        f"Phone: {lead.get('phone', '')}",
        f"Email: {lead.get('email', '')}",
        f"Service address: {lead.get('address', '')}",
        f"Category: {lead.get('category', '')}",
        f"Priority: {lead.get('priority', '')}",
        f"Reason: {lead.get('issue_summary') or lead.get('issue') or ''}",
        f"System/status detail: {lead.get('system_status', '')}",
        f"Preferred time: {lead.get('preferred_time', '')}",
        f"Needs team review: {lead.get('sms_review_required') or lead.get('possible_transcription_error')}",
        "",
        "Transcript:",
    ]
    for turn in transcript or []:
        if turn.get("customer") is not None:
            lines.append(f"Customer: {turn['customer']}")
        if turn.get("receptionist") is not None:
            lines.append(f"Atlas: {turn['receptionist']}")
    return "\n".join(lines)


def send_business_notification_email_via_resend(to_email, subject, body):
    if not RESEND_API_KEY:
        print("[EMAIL SKIPPED] RESEND_API_KEY is missing.")
        return False
    if not SMTP_FROM_EMAIL:
        print("[EMAIL SKIPPED] SMTP_FROM_EMAIL is required as the sender address.")
        return False

    payload = json.dumps(
        {
            "from": SMTP_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "text": body,
        }
    ).encode("utf-8")
    request = url_request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Atlas-Agent-AI/1.0",
        },
        method="POST",
    )

    try:
        with url_request.urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")
        print("[EMAIL SENT]", {"provider": "resend", "to": to_email, "response": response_body})
        return True
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print("[EMAIL ERROR]", {"provider": "resend", "status": exc.code, "body": error_body})
        return False
    except URLError as exc:
        print("[EMAIL ERROR]", {"provider": "resend", "error": repr(exc)})
        return False
    except Exception as exc:
        print("[EMAIL ERROR]", {"provider": "resend", "error": repr(exc)})
        return False


def send_business_notification_email_via_smtp(to_email, subject, body):
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        print("[EMAIL SKIPPED] SMTP_HOST and SMTP_FROM_EMAIL/SMTP_USERNAME are required.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
        print("[EMAIL SENT]", {"provider": "smtp", "to": to_email})
        return True
    except Exception as exc:
        print("[EMAIL ERROR]", {"provider": "smtp", "error": repr(exc)})
        return False


def send_business_notification_email(call_sid, lead, transcript, form_payload):
    to_email = get_notification_email_for_form_payload(form_payload)
    if not to_email:
        print("[EMAIL SKIPPED] BUSINESS_NOTIFICATION_EMAIL or business notification email is missing.")
        return False

    subject = f"New Atlas call: {lead.get('name') or form_payload.get('From', 'unknown caller')}"
    body = build_notification_email_body(call_sid, lead, transcript, form_payload)
    print("[EMAIL ATTEMPT]", {"provider": EMAIL_PROVIDER, "to": to_email, "call_sid": call_sid})

    if EMAIL_PROVIDER == "resend":
        return send_business_notification_email_via_resend(to_email, subject, body)

    return send_business_notification_email_via_smtp(to_email, subject, body)


def save_completed_call_to_database(call_sid, lead, transcript, form_payload):
    if not DB_AVAILABLE:
        return False

    try:
        with session_scope() as db_session:
            business_config = get_business_config_for_call(db_session, form_payload.get("To", ""))
            if not business_config.business_id:
                print("[DB SKIPPED] No active business matched this Twilio number.")
                return False
            lead["company_name"] = business_config.company_name

            customer = CustomerRepository(db_session).get_or_create_from_lead(
                business_config.business_id,
                lead,
                form_payload.get("From", ""),
            )
            call = CallRepository(db_session).save_completed_call(
                business_id=business_config.business_id,
                customer_id=customer.id,
                call_sid=call_sid,
                from_phone=form_payload.get("From", ""),
                to_phone=form_payload.get("To", ""),
                transcript=transcript,
            )
            service_request = ServiceRequestRepository(db_session).create_from_lead(
                business_id=business_config.business_id,
                customer_id=customer.id,
                call_id=call.id,
                lead=lead,
            )
            appointment_result = AppointmentService(db_session).request_appointment(
                business_id=business_config.business_id,
                customer_id=customer.id,
                service_request_id=service_request.id,
                preferred_time=lead.get("preferred_time", ""),
                notes="Captured by Atlas during phone call.",
            )
            print(
                "[DB SAVED]",
                {
                    "business_id": business_config.business_id,
                    "customer_id": customer.id,
                    "call_id": call.id,
                    "service_request_id": service_request.id,
                    "appointment_status": appointment_result.status,
                },
            )
            return True
    except Exception as exc:
        print("[DB SAVE ERROR]", repr(exc))
        return False


def save_lead(call_sid, bot):
    transcript = sessions.get(call_sid, {}).get("transcript", [])
    save_lead_snapshot(call_sid, bot.lead, transcript, dict(request.form))


def save_lead_snapshot(call_sid, lead, transcript, form_payload):
    payload = {
        "call_sid": call_sid,
        "from": form_payload.get("From", ""),
        "to": form_payload.get("To", ""),
        "lead": lead,
        "transcript": transcript,
    }
    with LEADS_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")


def save_transcript(call_sid, bot):
    transcript = sessions.get(call_sid, {}).get("transcript", [])
    save_transcript_snapshot(call_sid, bot.lead, transcript, dict(request.form))


def save_transcript_snapshot(call_sid, lead, transcript, form_payload):
    payload = {
        "call_sid": call_sid,
        "from": form_payload.get("From", ""),
        "to": form_payload.get("To", ""),
        "lead": lead,
        "transcript": transcript,
    }

    with TRANSCRIPTS_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")

    with TRANSCRIPTS_MD_PATH.open("a", encoding="utf-8") as file:
        file.write(f"\n## Call {call_sid}\n\n")
        file.write(f"From: {form_payload.get('From', '')}\n\n")
        file.write(f"To: {form_payload.get('To', '')}\n\n")
        for turn in transcript:
            if turn.get("customer") is not None:
                file.write(f"Customer: {turn['customer']}\n\n")
            if turn.get("receptionist") is not None:
                file.write(f"Receptionist: {turn['receptionist']}\n\n")
        file.write("Final lead:\n\n```json\n")
        file.write(json.dumps(lead, indent=2))
        file.write("\n```\n")


def complete_call_after_response(call_sid, lead, transcript, form_payload):
    print(
        "[CALL COMPLETION START]",
        {
            "call_sid": call_sid,
            "email_provider": EMAIL_PROVIDER,
            "lead_name": lead.get("name"),
            "reason": lead.get("issue_summary") or lead.get("issue"),
        },
    )

    class LeadSnapshot:
        pass

    bot_snapshot = LeadSnapshot()
    lead["company_name"] = lead.get("company_name") or get_company_name_for_form_payload(form_payload)
    bot_snapshot.lead = lead
    try:
        send_review_sms(bot_snapshot, call_sid)
        lead["sms_sent"] = bot_snapshot.lead.get("sms_sent", lead.get("sms_sent"))
    except Exception as exc:
        print("[SMS ERROR]", repr(exc))
        lead["sms_sent"] = False

    try:
        save_lead_snapshot(call_sid, lead, transcript, form_payload)
        save_transcript_snapshot(call_sid, lead, transcript, form_payload)
    except Exception as exc:
        print("[LOCAL SNAPSHOT ERROR]", repr(exc))

    db_saved = save_completed_call_to_database(call_sid, lead, transcript, form_payload)
    email_sent = send_business_notification_email(call_sid, lead, transcript, form_payload)
    print("[CALL COMPLETION RESULT]", {"call_sid": call_sid, "db_saved": db_saved, "email_sent": email_sent})


@app.route("/health", methods=["GET"])
def health():
    return {
        "ok": True,
        "sessions": len(sessions),
        "twilio_account_sid_found": bool(TWILIO_ACCOUNT_SID),
        "twilio_auth_token_found": bool(TWILIO_AUTH_TOKEN),
        "twilio_phone_number_found": bool(TWILIO_PHONE_NUMBER),
        "lead_file": str(LEADS_PATH),
        "transcript_file": str(TRANSCRIPTS_MD_PATH),
        "bot_dialogue_file": str(BOT_DIALOGUE_PATH),
        "ai_file": ai_receptionist.__file__,
        "dialogue_version": AIReceptionist.DIALOGUE_VERSION,
        "twilio_app_version": TWILIO_APP_VERSION,
        "tts_voice": TWILIO_TTS_VOICE,
        "tts_language": TWILIO_TTS_LANGUAGE,
        "database_layer_available": DB_AVAILABLE,
        "database_import_error": DB_IMPORT_ERROR,
        "email_provider": EMAIL_PROVIDER,
        "resend_api_key_found": bool(RESEND_API_KEY),
        "smtp_host_found": bool(SMTP_HOST),
        "from_email_found": bool(SMTP_FROM_EMAIL),
        "fallback_business_email_found": bool(BUSINESS_NOTIFICATION_EMAIL),
    }


@app.route("/version", methods=["GET"])
def version():
    return {
        "twilio_app_file": __file__,
        "twilio_app_version": TWILIO_APP_VERSION,
        "ai_file": ai_receptionist.__file__,
        "dialogue_version": AIReceptionist.DIALOGUE_VERSION,
        "tts_voice": TWILIO_TTS_VOICE,
        "tts_language": TWILIO_TTS_LANGUAGE,
        "database_layer_available": DB_AVAILABLE,
        "database_import_error": DB_IMPORT_ERROR,
        "email_provider": EMAIL_PROVIDER,
        "resend_api_key_found": bool(RESEND_API_KEY),
        "smtp_host_found": bool(SMTP_HOST),
        "from_email_found": bool(SMTP_FROM_EMAIL),
        "fallback_business_email_found": bool(BUSINESS_NOTIFICATION_EMAIL),
    }


@app.route("/voice-test", methods=["GET", "POST"])
def voice_test():
    response = VoiceResponse()
    say(
        response,
        "Hello. Your Twilio call reached the AI receptionist test app. "
        "If you can hear this message, the webhook is working."
    )
    response.hangup()
    return xml_response(response)


@app.route("/voice", methods=["POST"])
def voice():
    call_sid = get_call_sid()
    bot = get_or_create_bot(call_sid)
    session_state = setup_call_context(call_sid, bot)
    prompt = returning_customer_greeting(bot, session_state.get("returning_customer"))
    if not prompt:
        prompt = bot.process_conversation("Hi")
    prompt = apply_voice_channel_shortcuts(bot, prompt)
    remember_prompt(call_sid, prompt)
    log_bot_dialogue(call_sid, prompt, bot.current_step, "voice")
    add_transcript_turn(
        call_sid,
        customer="[call started]",
        receptionist=prompt,
        metadata={"step": bot.current_step},
    )
    return xml_response(build_twiml(prompt, bot, call_sid))


@app.route("/repeat/<call_sid>", methods=["POST"])
def repeat(call_sid):
    bot = get_or_create_bot(call_sid)
    prompt = sessions.get(call_sid, {}).get("last_prompt") or "I missed that. Could you say that again?"
    log_bot_dialogue(call_sid, prompt, bot.current_step, "repeat")
    return xml_response(build_twiml(prompt, bot, call_sid))


@app.route("/gather", methods=["POST"])
def gather():
    call_sid = get_call_sid()
    if call_sid in completed_call_sids:
        response = VoiceResponse()
        say(response, "Your request has already been submitted. Goodbye.")
        response.hangup()
        return xml_response(response)

    bot = get_or_create_bot(call_sid)
    setup_call_context(call_sid, bot)
    inbound = normalize_inbound_for_step(bot)

    if not inbound:
        if lead_has_minimum_for_business_email(bot):
            prompt = force_complete_with_current_lead(bot)
            prompt = apply_voice_channel_shortcuts(bot, prompt)
            remember_prompt(call_sid, prompt)
            log_bot_dialogue(call_sid, prompt, bot.current_step, "empty-gather-auto-complete")
            add_transcript_turn(
                call_sid,
                customer="[no response captured]",
                receptionist=prompt,
                metadata={"step": bot.current_step, "auto_completed": True},
            )
            lead_snapshot = dict(bot.lead)
            transcript_snapshot = list(sessions.get(call_sid, {}).get("transcript", []))
            form_payload = dict(request.form)
            print(
                "[CALL AUTO COMPLETE TRIGGER]",
                {
                    "call_sid": call_sid,
                    "email_provider": EMAIL_PROVIDER,
                    "resend_api_key_found": bool(RESEND_API_KEY),
                    "fallback_business_email_found": bool(BUSINESS_NOTIFICATION_EMAIL),
                },
            )
            threading.Thread(
                target=complete_call_after_response,
                args=(call_sid, lead_snapshot, transcript_snapshot, form_payload),
                daemon=False,
            ).start()
            completed_call_sids.add(call_sid)
            sessions.pop(call_sid, None)
            return xml_response(build_twiml(prompt, bot, call_sid))

        prompt = sessions.get(call_sid, {}).get("last_prompt") or "I missed that. Could you say that again?"
        log_bot_dialogue(call_sid, prompt, bot.current_step, "empty-gather-repeat")
        return xml_response(build_twiml(prompt, bot, call_sid))

    before_step = bot.current_step
    prompt = bot.process_conversation(inbound)
    prompt = apply_voice_channel_shortcuts(bot, prompt)
    remember_prompt(call_sid, prompt)
    log_bot_dialogue(call_sid, prompt, bot.current_step, "gather")
    print(
        "[TURN]",
        {
            "call_sid": call_sid,
            "from_step": before_step,
            "to_step": bot.current_step,
            "inbound": inbound,
            "lead": {
                "name": bool(bot.lead.get("name")),
                "phone": bool(bot.lead.get("phone")),
                "phone_confirmed": bot.lead.get("phone_confirmed"),
                "address": bool(bot.lead.get("address")),
                "system_status": bool(bot.lead.get("system_status")),
                "preferred_time": bool(bot.lead.get("preferred_time")),
                "category": bot.lead.get("category"),
            },
            "prompt": prompt,
        },
    )
    add_transcript_turn(
        call_sid,
        customer=inbound,
        receptionist=prompt,
        metadata={
            "step": bot.current_step,
            "speech_result": request.form.get("SpeechResult", ""),
            "speech_confidence": request.form.get("Confidence", ""),
            "digits": request.form.get("Digits", ""),
        },
    )

    if bot.current_step == "complete":
        lead_snapshot = dict(bot.lead)
        transcript_snapshot = list(sessions.get(call_sid, {}).get("transcript", []))
        form_payload = dict(request.form)
        print(
            "[CALL COMPLETE TRIGGER]",
            {
                "call_sid": call_sid,
                "email_provider": EMAIL_PROVIDER,
                "resend_api_key_found": bool(RESEND_API_KEY),
                "fallback_business_email_found": bool(BUSINESS_NOTIFICATION_EMAIL),
            },
        )
        threading.Thread(
            target=complete_call_after_response,
            args=(call_sid, lead_snapshot, transcript_snapshot, form_payload),
            daemon=False,
        ).start()
        completed_call_sids.add(call_sid)
        sessions.pop(call_sid, None)

    return xml_response(build_twiml(prompt, bot, call_sid))


@app.route("/review/<call_sid>", methods=["GET"])
def review(call_sid):
    if not DB_AVAILABLE:
        return Response(
            "<h1>Review unavailable</h1><p>The database is not connected right now.</p>",
            mimetype="text/html",
            status=503,
        )

    try:
        with session_scope() as db_session:
            call = CallRepository(db_session).get_by_call_sid(call_sid)
            if not call:
                return Response(
                    "<h1>Review not ready</h1><p>Please try this link again in a moment.</p>",
                    mimetype="text/html",
                    status=404,
                )
            customer = db_session.get(Customer, call.customer_id)
            service_request = ServiceRequestRepository(db_session).get_by_call_id(call.id)
            if not customer:
                return Response(
                    "<h1>Review not found</h1><p>We could not find the customer for this request.</p>",
                    mimetype="text/html",
                    status=404,
                )
            full_name = " ".join(
                part for part in [customer.first_name, customer.last_name] if part
            ).strip()
            html = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Review Your Request</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 24px; background: #f6f7f9; color: #17202a; }}
    main {{ max-width: 640px; margin: 0 auto; background: white; padding: 24px; border: 1px solid #d9dee7; }}
    label {{ display: block; font-weight: 700; margin-top: 16px; }}
    input, textarea {{ width: 100%; box-sizing: border-box; padding: 12px; margin-top: 6px; border: 1px solid #b8c0cc; font-size: 16px; }}
    textarea {{ min-height: 96px; }}
    button {{ margin-top: 20px; padding: 12px 16px; font-size: 16px; border: 0; background: #174ea6; color: white; cursor: pointer; }}
  </style>
</head>
<body>
  <main>
    <h1>Review Your Request</h1>
    <form method="post">
      <label for="name">Name</label>
      <input id="name" name="name" value="{escape(full_name)}">

      <label for="service_address">Service address</label>
      <input id="service_address" name="service_address" value="{escape(service_request.service_address if service_request else '')}">

      <label for="email">Email</label>
      <input id="email" name="email" value="{escape(customer.email)}">

      <label for="issue_summary">Service notes</label>
      <textarea id="issue_summary" name="issue_summary">{escape(service_request.issue_summary if service_request else '')}</textarea>

      <label for="preferred_time">Preferred follow-up time</label>
      <input id="preferred_time" name="preferred_time" value="{escape(service_request.preferred_time if service_request else '')}">

      <button type="submit">Save Updates</button>
    </form>
  </main>
</body>
</html>
"""
            return Response(html, mimetype="text/html")
    except Exception as exc:
        print("[REVIEW ERROR]", repr(exc))
        return Response(
            "<h1>Review unavailable</h1><p>We could not load this request.</p>",
            mimetype="text/html",
            status=500,
        )


@app.route("/review/<call_sid>", methods=["POST"])
def review_update(call_sid):
    if not DB_AVAILABLE:
        return Response(
            "<h1>Review unavailable</h1><p>The database is not connected right now.</p>",
            mimetype="text/html",
            status=503,
        )

    try:
        with session_scope() as db_session:
            call = CallRepository(db_session).get_by_call_sid(call_sid)
            if not call:
                return Response(
                    "<h1>Review not found</h1><p>We could not find this request.</p>",
                    mimetype="text/html",
                    status=404,
                )

            service_request = ServiceRequestRepository(db_session).get_by_call_id(call.id)
            CustomerRepository(db_session).update_customer_details(
                call.customer_id,
                name=request.form.get("name", "").strip(),
                email=request.form.get("email", "").strip(),
                service_address=request.form.get("service_address", "").strip(),
            )
            if service_request:
                ServiceRequestRepository(db_session).update_review_details(
                    service_request.id,
                    service_address=request.form.get("service_address", "").strip(),
                    issue_summary=request.form.get("issue_summary", "").strip(),
                    preferred_time=request.form.get("preferred_time", "").strip(),
                )
            print("[REVIEW UPDATED]", {"call_sid": call_sid, "call_id": call.id})
            return Response(
                "<h1>Updates saved</h1><p>Thank you. We updated your request for the team.</p>",
                mimetype="text/html",
            )
    except Exception as exc:
        print("[REVIEW UPDATE ERROR]", repr(exc))
        return Response(
            "<h1>Update failed</h1><p>We could not save your changes. Please call the team directly.</p>",
            mimetype="text/html",
            status=500,
        )


@app.route("/transcripts", methods=["GET"])
def transcripts():
    if not TRANSCRIPTS_MD_PATH.exists():
        return {
            "message": "No completed call transcripts have been saved yet.",
            "path": str(TRANSCRIPTS_MD_PATH),
        }
    return Response(TRANSCRIPTS_MD_PATH.read_text(encoding="utf-8"), mimetype="text/plain")


@app.route("/bot-dialogue", methods=["GET"])
def bot_dialogue():
    if not BOT_DIALOGUE_PATH.exists():
        return {
            "message": "No receptionist-only dialogue has been saved yet.",
            "path": str(BOT_DIALOGUE_PATH),
        }
    return Response(BOT_DIALOGUE_PATH.read_text(encoding="utf-8"), mimetype="text/plain")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5002"))
    app.run(host="0.0.0.0", port=port, debug=True)

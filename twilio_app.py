import json
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, request
from twilio.rest import Client
from twilio.twiml.voice_response import Gather, VoiceResponse

from ai_receptionist import AIReceptionist
import ai_receptionist


load_dotenv()

TWILIO_APP_VERSION = "atlas-github-render-ready-2026-06-23"

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


TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TWILIO_TTS_VOICE = os.getenv("TWILIO_TTS_VOICE", "Polly.Brian-Generative")
TWILIO_TTS_LANGUAGE = os.getenv("TWILIO_TTS_LANGUAGE", "en-GB")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
REVIEW_BASE_URL = os.getenv("REVIEW_BASE_URL", PUBLIC_BASE_URL).rstrip("/")
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


def log_bot_dialogue(call_sid, prompt, step, source):
    with BOT_DIALOGUE_PATH.open("a", encoding="utf-8") as file:
        file.write(f"\n## {call_sid}\n\n")
        file.write(f"Source: {source}\n\n")
        file.write(f"Step: {step}\n\n")
        file.write(f"Receptionist: {prompt}\n")


def apply_voice_channel_shortcuts(bot, prompt):
    if bot.current_step != "email":
        return prompt

    bot.lead["email"] = "Can add by SMS"
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
        say(gather, "Please enter the best phone number for text confirmation, including area code.")
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
            input="dtmf speech",
            action="/gather",
            method="POST",
            num_digits=1,
            timeout=8,
            speech_timeout="auto",
            action_on_empty_result=False,
        )
        say(gather, prompt + " Press 1 for yes, or 2 if something sounds wrong.")
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
    if review_url:
        body = f"ABC Heating & Air: Review or update your request here: {review_url}"
    else:
        body = "ABC Heating & Air: We received your request. Reply with any corrections or updates."

    client.messages.create(
        body=body,
        from_=TWILIO_PHONE_NUMBER,
        to="+1" + bot.lead["phone"],
    )
    bot.lead["sms_sent"] = True
    return True


def save_completed_call_to_database(call_sid, lead, transcript, form_payload):
    if not DB_AVAILABLE:
        return False

    try:
        with session_scope() as db_session:
            business_config = get_business_config_for_call(db_session, form_payload.get("To", ""))
            if not business_config.business_id:
                print("[DB SKIPPED] No active business matched this Twilio number.")
                return False

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
    class LeadSnapshot:
        pass

    bot_snapshot = LeadSnapshot()
    bot_snapshot.lead = lead
    try:
        send_review_sms(bot_snapshot, call_sid)
        lead["sms_sent"] = bot_snapshot.lead.get("sms_sent", lead.get("sms_sent"))
    except Exception as exc:
        print("[SMS ERROR]", repr(exc))
        lead["sms_sent"] = False

    save_lead_snapshot(call_sid, lead, transcript, form_payload)
    save_transcript_snapshot(call_sid, lead, transcript, form_payload)
    save_completed_call_to_database(call_sid, lead, transcript, form_payload)


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
    bot = get_or_create_bot(call_sid)
    inbound = normalize_inbound_for_step(bot)

    if not inbound:
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
        threading.Thread(
            target=complete_call_after_response,
            args=(call_sid, lead_snapshot, transcript_snapshot, form_payload),
            daemon=True,
        ).start()
        sessions.pop(call_sid, None)

    return xml_response(build_twiml(prompt, bot, call_sid))


@app.route("/review/<call_sid>", methods=["GET"])
def review(call_sid):
    return {
        "message": "This is a placeholder review endpoint.",
        "call_sid": call_sid,
        "next_step": "Replace this with a customer-facing form to edit lead details.",
    }


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

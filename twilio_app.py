import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, request
from twilio.rest import Client
from twilio.twiml.voice_response import Gather, VoiceResponse

from ai_receptionist_groomed import AIReceptionist
import ai_receptionist_groomed


load_dotenv("/Users/trevorlawrenz/Documents/.env")

print("LOADED AI FILE:", ai_receptionist_groomed.__file__)
print("TWILIO ACCOUNT SID FOUND:", bool(os.getenv("TWILIO_ACCOUNT_SID")))
print("TWILIO AUTH TOKEN FOUND:", bool(os.getenv("TWILIO_AUTH_TOKEN")))
print("TWILIO PHONE NUMBER FOUND:", bool(os.getenv("TWILIO_PHONE_NUMBER")))

app = Flask(__name__)

sessions = {}


TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
REVIEW_BASE_URL = os.getenv("REVIEW_BASE_URL", PUBLIC_BASE_URL).rstrip("/")
OUTPUT_DIR = Path(__file__).resolve().parent
LEADS_PATH = OUTPUT_DIR / "twilio_leads.jsonl"


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


def get_call_sid():
    return request.form.get("CallSid", "local-dev")


def get_or_create_bot(call_sid):
    if call_sid not in sessions:
        sessions[call_sid] = AIReceptionist()
    return sessions[call_sid]


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


def build_twiml(prompt, bot):
    response = VoiceResponse()

    if bot.current_step == "complete":
        response.say(prompt)
        response.hangup()
        return response

    if bot.current_step == "phone":
        gather = Gather(
            input="dtmf",
            action="/gather",
            method="POST",
            num_digits=10,
            timeout=10,
            action_on_empty_result=True,
        )
        gather.say("Please enter the best phone number for text confirmation, including area code.")
        response.append(gather)
        response.say("I did not receive a phone number. Please call again or wait for our team to follow up.")
        return response

    if bot.current_step == "phone_confirmation":
        gather = Gather(
            input="dtmf speech",
            action="/gather",
            method="POST",
            num_digits=1,
            timeout=6,
            speech_timeout="auto",
            action_on_empty_result=True,
        )
        gather.say(prompt + " Press 1 for yes, or 2 to enter it again.")
        response.append(gather)
        response.redirect("/gather", method="POST")
        return response

    if bot.current_step == "confirmation":
        gather = Gather(
            input="dtmf speech",
            action="/gather",
            method="POST",
            num_digits=1,
            timeout=8,
            speech_timeout="auto",
            action_on_empty_result=True,
        )
        gather.say(prompt + " Press 1 for yes, or 2 if something sounds wrong.")
        response.append(gather)
        response.redirect("/gather", method="POST")
        return response

    if bot.awaiting_anything_else:
        gather = Gather(
            input="dtmf speech",
            action="/gather",
            method="POST",
            num_digits=1,
            timeout=8,
            speech_timeout="auto",
            action_on_empty_result=True,
        )
        gather.say(prompt + " Press 1 for no, or say what you want to add.")
        response.append(gather)
        response.redirect("/gather", method="POST")
        return response

    gather = Gather(
        input="speech",
        action="/gather",
        method="POST",
        timeout=8,
        speech_timeout="auto",
        action_on_empty_result=True,
    )
    gather.say(prompt)
    response.append(gather)
    response.say("I did not catch that. Please call again or wait for our team to follow up.")
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


def save_lead(call_sid, bot):
    payload = {
        "call_sid": call_sid,
        "from": request.form.get("From", ""),
        "to": request.form.get("To", ""),
        "lead": bot.lead,
    }
    with LEADS_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")


@app.route("/health", methods=["GET"])
def health():
    return {
        "ok": True,
        "sessions": len(sessions),
        "twilio_account_sid_found": bool(TWILIO_ACCOUNT_SID),
        "twilio_auth_token_found": bool(TWILIO_AUTH_TOKEN),
        "twilio_phone_number_found": bool(TWILIO_PHONE_NUMBER),
    }


@app.route("/voice-test", methods=["GET", "POST"])
def voice_test():
    response = VoiceResponse()
    response.say(
        "Hello. Your Twilio call reached the AI receptionist test app. "
        "If you can hear this message, the webhook is working."
    )
    response.hangup()
    return xml_response(response)


@app.route("/voice", methods=["POST"])
def voice():
    call_sid = get_call_sid()
    bot = get_or_create_bot(call_sid)
    prompt = bot.process_conversation("Hi")
    return xml_response(build_twiml(prompt, bot))


@app.route("/gather", methods=["POST"])
def gather():
    call_sid = get_call_sid()
    bot = get_or_create_bot(call_sid)
    inbound = normalize_inbound_for_step(bot)

    if not inbound:
        inbound = "I did not answer"

    prompt = bot.process_conversation(inbound)

    if bot.current_step == "complete":
        send_review_sms(bot, call_sid)
        save_lead(call_sid, bot)
        sessions.pop(call_sid, None)

    return xml_response(build_twiml(prompt, bot))


@app.route("/review/<call_sid>", methods=["GET"])
def review(call_sid):
    return {
        "message": "This is a placeholder review endpoint.",
        "call_sid": call_sid,
        "next_step": "Replace this with a customer-facing form to edit lead details.",
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5002"))
    app.run(host="0.0.0.0", port=port, debug=True)

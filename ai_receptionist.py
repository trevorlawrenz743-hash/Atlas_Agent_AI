import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("/Users/trevorlawrenz/Documents/.env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class AIReceptionist:

    def __init__(self):
        self.reset()

    def reset(self):
        self.current_step = "greeting"

        self.company_info = {
            "name": "ABC Heating & Air",
            "hours": "Monday through Friday from 8 AM to 6 PM",
            "service_areas": "Austin, Round Rock, Cedar Park, Pflugerville, Georgetown, downtown Austin, and nearby areas",
            "emergency_service": True
        }

        self.lead = {
            "name": "",
            "phone": "",
            "email": "",
            "address": "",
            "issue": "",
            "category": "",
            "priority": "",
            "reason": "",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "verified": False,
            "sms_sent": False,
            "human_requested": False,
            "existing_appointment": False,
            "different_address_requested": False,
            "extra_update_count": 0,
            "soft_close_started": False
        }

    # =========================
    # NORMALIZATION
    # =========================
    def normalize(self, text):
        text = text.lower()
        text = re.sub(r"[^a-z0-9@\.\s\-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def is_greeting_only(self, msg):
        return self.normalize(msg) in [
            "hello", "hi", "hey",
            "good morning", "good afternoon", "good evening"
        ]

    # =========================
    # FIELD EXTRACTION
    # =========================
    def extract_email(self, msg):
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", msg)
        return match.group(0).strip() if match else None

    def extract_phone(self, msg):
        digits = re.sub(r"\D", "", msg)

        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]

        if len(digits) == 10:
            return digits

        return None

    def is_valid_name(self, name):
        if not name:
            return False

        bad_words = [
            "phone", "email", "quote", "service", "appointment", "reschedule",
            "downtown", "austin", "financing", "carrier", "repair", "ac",
            "heat", "working", "stopped", "broken", "leaking", "hours",
            "open", "close", "cost", "price", "tomorrow", "today"
        ]

        normalized = self.normalize(name)
        parts = name.split()

        if any(word in normalized.split() for word in bad_words):
            return False

        if len(parts) < 2:
            return False

        if len(parts) > 4:
            return False

        return True

    def extract_name(self, msg):
        text = msg.strip()

        patterns = [
            r"my name is ([a-zA-Z\s]+?)(?:,| and | also | do you | can you | what | when | where | how |$)",
            r"this is ([a-zA-Z\s]+?)(?:,| and | also | do you | can you | what | when | where | how |$)",
            r"i am ([a-zA-Z\s]+?)(?:,| and | also | do you | can you | what | when | where | how |$)",
            r"i'm ([a-zA-Z\s]+?)(?:,| and | also | do you | can you | what | when | where | how |$)",
            r"name is ([a-zA-Z\s]+?)(?:,| and | also | do you | can you | what | when | where | how |$)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = re.sub(r"\s+", " ", match.group(1).strip())
                if self.is_valid_name(name):
                    return name.title()

        if self.current_step == "name":
            cleaned = re.sub(r"[^a-zA-Z\s]", "", text).strip()
            cleaned = re.sub(r"\s+", " ", cleaned)

            if self.is_valid_name(cleaned):
                return cleaned.title()

        return None

    def customer_mentions_different_address(self, msg):
        text = self.normalize(msg)

        triggers = [
            "different address",
            "new address",
            "another address",
            "different location",
            "new location",
            "another location",
            "service address is",
            "system is located at",
            "come to"
        ]

        return any(x in text for x in triggers)

    def extract_address(self, msg):
        if not self.customer_mentions_different_address(msg):
            return None

        text = msg.strip()

        if len(text) < 6:
            return None

        if self.extract_email(text) or self.extract_phone(text):
            return None

        return text

    def extract_all_fields(self, msg):
        name = self.extract_name(msg)
        phone = self.extract_phone(msg)
        email = self.extract_email(msg)
        address = self.extract_address(msg)

        if name and not self.lead["name"]:
            self.lead["name"] = name

        if phone and not self.lead["phone"]:
            self.lead["phone"] = phone

        if email and not self.lead["email"]:
            self.lead["email"] = email

        if address:
            self.lead["address"] = address
            self.lead["different_address_requested"] = True

    # =========================
    # QUESTION HANDLING
    # =========================
    def answer_special_question(self, msg):
        text = self.normalize(msg)
        responses = []

        if any(x in text for x in [
            "hours", "open", "close", "what time", "when are you"
        ]):
            responses.append(
                f"Our regular office hours are {self.company_info['hours']}."
            )

        if any(x in text for x in [
            "service area", "do you service", "do you work in",
            "downtown austin", "austin", "round rock", "cedar park",
            "georgetown", "pflugerville"
        ]):
            responses.append(
                f"We service {self.company_info['service_areas']}."
            )

        if any(x in text for x in [
            "financing", "finance", "payment plan", "monthly payments"
        ]):
            responses.append(
                "Many customers ask about financing. Our team can review available options with you."
            )

        if any(x in text for x in [
            "how soon", "come out today", "available today", "earliest appointment"
        ]):
            responses.append(
                "Availability depends on the schedule and urgency, but I can note that you'd like the soonest available follow-up."
            )

        if any(x in text for x in [
            "carrier", "trane", "lennox", "goodman", "rheem", "mini split"
        ]):
            responses.append(
                "We service many common HVAC systems and brands. Our team can confirm the details for your specific unit."
            )

        if any(x in text for x in [
            "speak to a person", "speak with a person", "real person",
            "representative", "human", "manager", "live agent",
            "talk to someone", "talk to a person"
        ]):
            self.lead["category"] = "Human Request"
            self.lead["priority"] = "Normal"
            self.lead["human_requested"] = True

            responses.append(
                "Absolutely. I can document your request and have someone from our team follow up."
            )

        return " ".join(responses) if responses else None

    # =========================
    # CONTEXT FLAGS
    # =========================
    def update_context_flags(self, msg):
        text = self.normalize(msg)

        if any(x in text for x in [
            "already have an appointment",
            "appointment tomorrow",
            "appointment today",
            "reschedule",
            "cancel appointment"
        ]):
            self.lead["existing_appointment"] = True

    # =========================
    # EMERGENCY OVERRIDE
    # =========================
    def emergency_override(self, msg):
        text = self.normalize(msg)

        keywords = [
            "no air", "no ac", "no heat",
            "not working", "broken", "stopped working",
            "leak", "flood", "water",
            "over 100", "100 degrees", "very hot",
            "freezing", "urgent", "emergency", "asap"
        ]

        for keyword in keywords:
            if keyword in text:
                return {
                    "category": "Support",
                    "priority": "High",
                    "reason": f"Matched emergency keyword: {keyword}"
                }

        return None

    # =========================
    # LLM CLASSIFICATION
    # =========================
    def classify_with_llm(self, msg):
        system_prompt = """
You are an HVAC dispatch classifier.

Return ONLY JSON:
{
  "category": "...",
  "priority": "...",
  "summary": "...",
  "reason": "..."
}

Categories:
Support, Sales, Billing, Complaint, General Inquiry

Support = repair, AC/heat not working, leak, airflow, cooling, heating problem, existing appointment with active system problem
Sales = quote, pricing, estimate, new install, replacement, upgrade
Billing = invoice, payment, refund, charge, receipt
Complaint = bad service, technician issue, missed appointment, upset customer
General Inquiry = service area, hours, general questions

Priority:
High = no AC/heat, extreme temperature, leak, flood, emergency, urgent, missed technician for active service issue
Normal = everything else

If a message contains multiple intents, choose the most business-actionable intent.
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": msg}
            ],
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content)

    def classify_issue(self, msg):
        override = self.emergency_override(msg)

        if override:
            self.lead.update(override)
            return

        try:
            result = self.classify_with_llm(msg)

            self.lead["category"] = result.get("category", "General Inquiry")
            self.lead["priority"] = result.get("priority", "Normal")
            self.lead["reason"] = result.get("reason", "")

        except Exception as e:
            print("[ERROR] LLM classification failed:", e)

            self.lead["category"] = "General Inquiry"
            self.lead["priority"] = "Normal"
            self.lead["reason"] = "LLM classification failed"

    # =========================
    # NEXT STEP LOGIC
    # =========================
    def next_missing_question(self):
        if not self.lead["name"]:
            self.current_step = "name"
            return "May I have your name?"

        if not self.lead["phone"]:
            self.current_step = "phone"
            first_name = self.lead["name"].split()[0]
            return f"Thanks {first_name}. What's the best phone number to reach you?"

        if self.lead["category"] in ["Sales", "Billing"] and not self.lead["email"]:
            self.current_step = "email"
            return "What email address should we use for follow-up? You can also say skip."

        self.current_step = "confirmation"
        return self.build_confirmation()

    def intro_for_category(self):
        category = self.lead["category"]

        if category == "Support":
            return "I'm sorry you're dealing with that. I'll make sure this is noted for the team."

        if category == "Sales":
            return "I'd be happy to help with that."

        if category == "Billing":
            return "I can help get that routed to the right person."

        if category == "Complaint":
            return "I'm sorry to hear that. I'd like to make sure your concern is documented properly."

        if category == "Human Request":
            return "I can document your request and have someone follow up."

        return "I can help with that."

    # =========================
    # CONFIRMATION / SOFT CLOSE
    # =========================
    def handle_confirmation_message(self, msg):
        text = self.normalize(msg)

        done_phrases = [
            "yes", "correct", "looks good", "that's right", "that is right",
            "no", "nope", "nothing else", "that's all", "that is all",
            "submit", "send it", "all good"
        ]

        if any(x in text for x in done_phrases):
            return self.submit_request()

        meaningful_update = any(x in text for x in [
            "appointment", "reschedule", "cancel",
            "stopped working", "not working", "no ac", "no air",
            "no heat", "leak", "water", "broken",
            "carrier", "trane", "lennox", "financing",
            "different address", "new address", "another address",
            "different location", "new location", "another location"
        ])

        if meaningful_update:
            special_answer = self.answer_special_question(msg)
            self.update_context_flags(msg)

            self.lead["issue"] = msg
            self.classify_issue(msg)

            self.lead["extra_update_count"] += 1
            self.lead["soft_close_started"] = True

            response_parts = []

            if special_answer:
                response_parts.append(special_answer)

            if self.lead["existing_appointment"]:
                response_parts.append(
                    "I noted that you already have an appointment and may need scheduling help."
                )

            if self.lead["priority"].lower() == "high":
                response_parts.append(
                    "Since your system stopped working, I’ll mark this as a high-priority service issue."
                )

            if self.lead["different_address_requested"]:
                response_parts.append(
                    "I also noted the updated service location."
                )

            if self.lead["extra_update_count"] >= 2:
                self.current_step = "complete"
                self.lead["verified"] = True

                if not self.lead["sms_sent"]:
                    self.lead["sms_sent"] = True
                    print("[SMS READY] Send SMS confirmation here.")

                response_parts.append(
                    "I’ve added that to the request. I’ll submit this now so the team can follow up."
                )

                return " ".join(response_parts)

            response_parts.append(
                "I’ve added that to the request. Is there anything else you’d like me to include?"
            )

            return " ".join(response_parts)

        if self.lead["soft_close_started"]:
            return self.submit_request()

        return (
            "No problem. I can update the request. "
            "What would you like me to change or add?"
        )

    def submit_request(self):
        self.lead["verified"] = True
        self.current_step = "complete"

        if not self.lead["sms_sent"]:
            self.lead["sms_sent"] = True
            print("[SMS READY] Send SMS confirmation here.")

        return (
            "Thank you. I’ve submitted your request, and the team will follow up soon. "
            "We’ll also send a text message where you can review or update your information if needed."
        )

    # =========================
    # MAIN CONVERSATION ENGINE
    # =========================
    def process_conversation(self, msg):
        print("\nSTEP:", self.current_step)
        print("INPUT:", msg)

        msg = msg.strip()

        self.extract_all_fields(msg)
        self.update_context_flags(msg)

        if self.current_step == "greeting" and self.is_greeting_only(msg):
            return "Thank you for calling. How can I help you today?"

        if self.current_step == "confirmation":
            return self.handle_confirmation_message(msg)

        if self.current_step == "complete":
            return (
                "Your request has already been submitted. "
                "A member of our team will follow up soon."
            )

        if self.current_step == "email" and self.normalize(msg) in ["skip", "no", "none"]:
            self.current_step = "confirmation"
            return self.build_confirmation()

        special_answer = self.answer_special_question(msg)

        if not self.lead["issue"] and not self.is_greeting_only(msg):
            self.lead["issue"] = msg
            self.classify_issue(msg)

        if any(x in self.normalize(msg) for x in [
            "stopped working", "no ac", "no air", "no heat", "leak",
            "quote", "estimate", "billing", "charged", "complaint",
            "appointment", "reschedule"
        ]):
            self.lead["issue"] = msg
            self.classify_issue(msg)

        if not self.lead["category"]:
            self.current_step = "clarify_intent"
            prefix = special_answer + " " if special_answer else ""
            return prefix + "Are you calling about a repair, a new installation or quote, billing, or something else?"

        prefix_parts = []

        if special_answer:
            prefix_parts.append(special_answer)

        if self.current_step in ["greeting", "clarify_intent"]:
            prefix_parts.append(self.intro_for_category())

        next_question = self.next_missing_question()

        if self.current_step == "confirmation":
            if prefix_parts:
                return " ".join(prefix_parts) + "\n\n" + next_question
            return next_question

        if prefix_parts:
            return " ".join(prefix_parts) + " " + next_question

        return next_question

    # =========================
    # FINAL CONFIRMATION
    # =========================
    def build_confirmation(self):
        summary = f"""
Thank you — here is what I have:

Name: {self.lead['name']}
Phone: {self.lead['phone']}
"""

        if self.lead["address"]:
            summary += f"Address: {self.lead['address']}\n"

        if self.lead["email"]:
            summary += f"Email: {self.lead['email']}\n"

        if self.lead["issue"]:
            summary += f"Issue: {self.lead['issue']}\n"

        if self.lead["existing_appointment"]:
            summary += "Existing Appointment: Yes\n"

        summary += f"Category: {self.lead['category']}\n"
        summary += f"Priority: {self.lead['priority']}\n"

        summary += """
Is this information correct?
"""

        return summary

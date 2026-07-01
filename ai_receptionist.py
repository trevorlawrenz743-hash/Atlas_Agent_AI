import re
from datetime import datetime

from industry_profiles import get_industry_profile


class AIReceptionist:
    DIALOGUE_VERSION = "atlas-reason-confirmation-2026-07-01"

    def __init__(self, use_llm_classifier=False):
        self.use_llm_classifier = use_llm_classifier
        self.reset()

    def reset(self):
        self.current_step = "greeting"
        self.awaiting_confirmation = False
        self.awaiting_anything_else = False
        self.awaiting_phone_confirmation = False
        self.address_prompt_count = 0
        self.address_candidate = ""

        self.company_info = {
            "name": "ABC Heating & Air",
            "hours": "Monday through Friday from 8 AM to 6 PM",
            "service_areas": (
                "Austin, Round Rock, Cedar Park, Pflugerville, Georgetown, "
                "downtown Austin, and nearby areas"
            ),
            "industry": "hvac",
            "assistant_name": "Atlas",
        }

        self.lead = {
            "name": "",
            "phone": "",
            "email": "",
            "address": "",
            "unit": "",
            "customer_type": "",
            "issue": "",
            "issue_summary": "",
            "category": "",
            "priority": "Normal",
            "reason": "",
            "danger_flag": False,
            "safety_note_given": False,
            "preferred_time": "",
            "system_status": "",
            "appointment_action": "",
            "human_requested": False,
            "existing_appointment": False,
            "verified": False,
            "sms_sent": False,
            "phone_confirmed": False,
            "verification_status": "Unverified",
            "possible_transcription_error": False,
            "sms_review_required": False,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # -------------------------
    # Normalization
    # -------------------------
    def normalize(self, text):
        text = text.lower()
        text = re.sub(r"[^a-z0-9@\.\s#,\-]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def contains_any(self, text, phrases):
        normalized = self.normalize(text)
        return any(phrase in normalized for phrase in phrases)

    def is_greeting_only(self, msg):
        return self.normalize(msg) in {
            "hello",
            "hi",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
        }

    # -------------------------
    # Field extraction
    # -------------------------
    def extract_email(self, msg):
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", msg)
        return match.group(0).strip() if match else None

    def extract_phone(self, msg):
        digits = re.sub(r"\D", "", msg)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits if len(digits) == 10 else None

    def format_phone_for_voice(self, phone):
        if len(phone) != 10:
            return phone
        return f"{phone[:3]}-{phone[3:6]}-{phone[6:]}"

    def is_valid_name(self, name):
        bad_words = {
            "yes",
            "yeah",
            "yep",
            "sure",
            "okay",
            "ok",
            "um",
            "uh",
            "phone",
            "email",
            "quote",
            "service",
            "appointment",
            "repair",
            "billing",
            "financing",
            "interested",
            "new",
            "returning",
            "customer",
            "available",
            "tomorrow",
            "today",
            "too",
            "austin",
            "street",
            "road",
            "drive",
            "avenue",
            "lane",
            "blvd",
            "ac",
            "heat",
        }
        parts = self.normalize(name).split()
        return 2 <= len(parts) <= 4 and not any(word in bad_words for word in parts)

    def clean_name_candidate(self, name):
        candidate = re.sub(r"[^a-zA-Z\s]", " ", name).strip()
        candidate = re.sub(r"\s+", " ", candidate)
        filler_prefixes = [
            "yes",
            "yeah",
            "yep",
            "sure",
            "okay",
            "ok",
            "absolutely",
            "um",
            "uh",
            "so",
            "hello",
            "hi",
            "my name is",
            "name is",
            "this is",
            "i am",
            "im",
            "i m",
        ]
        changed = True
        while changed:
            changed = False
            lower = candidate.lower()
            for prefix in filler_prefixes:
                if lower == prefix:
                    return ""
                if lower.startswith(prefix + " "):
                    candidate = candidate[len(prefix) :].strip()
                    changed = True
                    break
        return candidate

    def extract_name(self, msg):
        patterns = [
            r"my name is ([a-zA-Z\s]+?)(?:,| and |$)",
            r"this is ([a-zA-Z\s]+?)(?:,| and |$)",
            r"i am ([a-zA-Z\s]+?)(?:,| and |$)",
            r"i'm ([a-zA-Z\s]+?)(?:,| and |$)",
            r"name is ([a-zA-Z\s]+?)(?:,| and |$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, msg, re.IGNORECASE)
            if match:
                candidate = self.clean_name_candidate(match.group(1))
                if self.is_valid_name(candidate):
                    return candidate.title()

        if self.current_step == "name":
            candidate = self.clean_name_candidate(msg)
            if self.is_valid_name(candidate):
                return candidate.title()

        return None

    def looks_like_address(self, msg):
        if self.extract_email(msg) or self.extract_phone(msg):
            return False

        text = self.normalize(msg)
        street_words = [
            "st",
            "street",
            "rd",
            "road",
            "dr",
            "drive",
            "ave",
            "avenue",
            "ln",
            "lane",
            "blvd",
            "court",
            "ct",
            "way",
            "trail",
        ]
        return bool(re.search(r"\d{2,6}\s+\w+", text)) and any(
            word in text.split() for word in street_words
        )

    def looks_like_service_location(self, msg):
        text = self.normalize(msg)
        service_cities = [
            "austin",
            "round rock",
            "cedar park",
            "pflugerville",
            "georgetown",
        ]
        return self.looks_like_address(msg) or any(city in text for city in service_cities)

    def is_vague_issue(self, msg):
        text = self.normalize(msg)
        vague_phrases = {
            "i need help",
            "need help",
            "i need service",
            "need service",
            "i need someone",
            "send someone",
            "come out",
            "someone to come out",
            "service call",
            "appointment",
            "question",
        }
        if not text:
            return True
        if text in vague_phrases or any(phrase in text for phrase in vague_phrases):
            return True
        return len(text.split()) <= 3 and not self.contains_any(
            text,
            [
                "ac",
                "air",
                "heat",
                "heater",
                "furnace",
                "cooling",
                "leak",
                "broken",
                "repair",
                "quote",
                "estimate",
                "install",
                "noise",
                "warm",
                "hot",
                "cold",
            ],
        )

    def extract_unit(self, msg):
        match = re.search(
            r"\b(?:apt|apartment|unit|suite|ste|#)\s*([A-Za-z0-9\-]+)",
            msg,
            re.IGNORECASE,
        )
        if not match:
            return None

        unit_value = match.group(1).strip()
        blocked_values = {"is", "was", "has", "leaking", "making", "not"}
        if unit_value.lower() in blocked_values:
            return None
        if not any(char.isdigit() for char in unit_value) and len(unit_value) > 3:
            return None
        return match.group(0).strip()

    def extract_fields(self, msg):
        name = self.extract_name(msg)
        phone = self.extract_phone(msg)
        email = self.extract_email(msg)
        unit = self.extract_unit(msg)

        if name and not self.lead["name"]:
            self.lead["name"] = name
        if phone and not self.lead["phone"]:
            self.lead["phone"] = phone
        if email and not self.lead["email"]:
            self.lead["email"] = email
        if unit:
            self.lead["unit"] = unit
        if self.current_step == "address" and self.looks_like_address(msg):
            self.lead["address"] = msg.strip()

    # -------------------------
    # Classification
    # -------------------------
    def classify_issue(self, msg):
        text = self.normalize(msg)
        profile = get_industry_profile(self.company_info.get("industry"))

        if self.is_dangerous_issue(text):
            self.lead["danger_flag"] = True
            return self.apply_classification("Support", "High", "Potential safety concern.")

        if self.contains_any(text, ["human", "real person", "representative", "manager", "live agent"]):
            return self.apply_classification("Human Request", "Normal", "Customer asked for a person.")

        if self.contains_any(text, ["reschedule", "move my appointment", "cancel appointment", "cancel my appointment"]):
            return self.apply_classification("Scheduling", "Normal", "Appointment scheduling request.")

        if self.contains_any(text, ["invoice", "charged", "charge", "payment", "refund", "receipt", "bill"]):
            return self.apply_classification("Billing", "Normal", "Billing/payment language.")

        if self.contains_any(text, ["complaint", "upset", "bad service", "never showed", "missed appointment"]):
            priority = "High" if self.contains_any(text, profile["high_priority_keywords"]) else "Normal"
            return self.apply_classification("Complaint", priority, "Complaint or missed appointment language.")

        if self.contains_any(text, profile["sales_keywords"]):
            return self.apply_classification("Sales", "Normal", "Quote, replacement, or installation language.")

        if self.contains_any(text, profile["support_keywords"]):
            priority = "High" if self.is_likely_emergency(text) else "Normal"
            return self.apply_classification("Support", priority, "Repair or active system problem.")

        if self.contains_any(text, ["hours", "open", "close", "service area", "do you service"]):
            return self.apply_classification("General Inquiry", "Normal", "General company question.")

        return self.apply_classification("General Inquiry", "Normal", "Could not confidently classify.")

    def is_likely_emergency(self, text):
        profile = get_industry_profile(self.company_info.get("industry"))
        return any(phrase in text for phrase in profile["high_priority_keywords"])

    def is_dangerous_issue(self, text):
        profile = get_industry_profile(self.company_info.get("industry"))
        return any(phrase in text for phrase in profile["danger_keywords"])

    def apply_classification(self, category, priority, reason):
        self.lead["category"] = category
        self.lead["priority"] = priority
        self.lead["reason"] = reason
        if category == "Human Request":
            self.lead["human_requested"] = True

    def clean_customer_reason(self, msg):
        text = msg.strip()
        lower = text.lower()
        text = re.sub(r"\b(?:send|sent)\s+(?:this|it|that)?\s*(?:over|through)\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" .,-")
        lower = text.lower()
        issue_starts = [
            "my ac",
            "my air",
            "my heat",
            "my heater",
            "my furnace",
            "the ac",
            "the air",
            "the heat",
            "the heater",
            "the furnace",
            "there is",
            "i need repair",
        ]
        positions = [lower.find(phrase) for phrase in issue_starts if lower.find(phrase) >= 0]
        if positions:
            return text[min(positions):].strip()
        return text

    # -------------------------
    # Context and FAQ handling
    # -------------------------
    def update_context(self, msg):
        text = self.normalize(msg)

        if self.contains_any(text, ["new customer", "first time", "never used you", "never called before"]):
            self.lead["customer_type"] = "New"

        if self.contains_any(text, ["returning customer", "used you before", "existing customer", "you installed", "you serviced"]):
            self.lead["customer_type"] = "Returning"

        if self.is_dangerous_issue(text):
            self.lead["danger_flag"] = True

        if self.contains_any(text, ["already have an appointment", "appointment today", "appointment tomorrow"]):
            self.lead["existing_appointment"] = True

        if self.contains_any(text, ["reschedule", "move my appointment"]):
            self.lead["existing_appointment"] = True
            self.lead["appointment_action"] = "Reschedule"

        if self.contains_any(text, ["cancel appointment", "cancel my appointment"]):
            self.lead["existing_appointment"] = True
            self.lead["appointment_action"] = "Cancel"

    def answer_special_question(self, msg):
        text = self.normalize(msg)
        answers = []

        if self.contains_any(text, ["hours", "open", "close", "what time"]):
            answers.append(f"Our regular office hours are {self.company_info['hours']}.")

        if self.contains_any(text, ["service area", "do you service", "do you work in", "round rock", "cedar park", "pflugerville", "georgetown"]):
            city_answer = self.answer_service_area_question(text)
            answers.append(city_answer)

        if self.contains_any(text, ["financing", "finance", "payment plan", "monthly payments"]):
            answers.append("Our team can review available financing options with you.")

        if self.contains_any(text, ["how soon", "come out today", "available today", "earliest appointment", "when can you come"]):
            answers.append("Availability depends on the schedule and urgency, but I can note that you would like the soonest available follow-up.")

        return " ".join(answers)

    def answer_service_area_question(self, text):
        city_names = {
            "round rock": "Round Rock",
            "cedar park": "Cedar Park",
            "pflugerville": "Pflugerville",
            "georgetown": "Georgetown",
            "downtown austin": "downtown Austin",
            "austin": "Austin",
        }
        for key, label in city_names.items():
            if key in text:
                return f"Yes, we do service {label}."
        return f"We service {self.company_info['service_areas']}."

    def is_question_only(self, msg):
        text = self.normalize(msg)
        question_mark = "?" in msg
        question_phrases = [
            "do you service",
            "do you work in",
            "what are your hours",
            "are you open",
            "how soon",
            "when can you come",
            "available today",
            "earliest appointment",
        ]
        action_phrases = [
            "no ac",
            "no air",
            "no heat",
            "not cooling",
            "not heating",
            "completely out",
            "stopped working",
            "leaking",
            "repair",
            "quote",
            "estimate",
            "install",
            "replace",
            "billing",
            "invoice",
            "reschedule",
            "cancel",
            "talk to",
            "person",
        ]
        return (question_mark or any(x in text for x in question_phrases)) and not any(
            x in text for x in action_phrases
        )

    # -------------------------
    # Flow control
    # -------------------------
    def process_conversation(self, msg):
        msg = msg.strip()
        if not msg:
            return "I can help with that. What would you like our team to know?"

        self.extract_fields(msg)
        self.update_context(msg)

        if self.current_step == "complete":
            return "Your request has already been submitted. A member of our team will follow up soon."

        if self.current_step == "greeting" and self.is_greeting_only(msg):
            return (
                f"Thank you for calling {self.company_info['name']}. "
                "I am Atlas, your virtual assistant. How can I help you today?"
            )

        if self.awaiting_anything_else:
            return self.handle_anything_else(msg)

        if self.current_step == "phone_confirmation":
            return self.handle_phone_confirmation(msg)

        if self.current_step == "confirmation":
            return self.handle_confirmation(msg)

        if self.current_step == "clarify_intent":
            if self.looks_like_address(msg):
                return "I caught the location. Before that, what problem should the team help with?"
            self.lead["issue"] = msg
            self.lead["issue_summary"] = msg
            self.classify_issue(msg)
            if self.lead["category"] == "General Inquiry" and self.is_vague_issue(msg):
                return "I want the service note to be clear. What problem should the team help with?"
            return self.next_question()

        if self.current_step in {"name", "phone", "email", "address", "preferred_time", "system_status"}:
            return self.advance_after_field(msg)

        faq_answer = self.answer_special_question(msg)

        if faq_answer and not self.lead["issue"] and self.is_question_only(msg):
            self.current_step = "clarify_intent"
            return faq_answer + " What is going on with your system today?"

        if not self.lead["issue"] and not self.is_greeting_only(msg):
            clean_reason = self.clean_customer_reason(msg)
            self.lead["issue"] = clean_reason
            self.lead["issue_summary"] = clean_reason
            self.classify_issue(msg)

        if faq_answer and self.lead["category"] == "General Inquiry":
            self.lead["issue"] = ""
            self.lead["issue_summary"] = ""
            self.current_step = "clarify_intent"
            return faq_answer + " What is going on with your system today?"

        question = self.next_question()
        if faq_answer:
            return f"{faq_answer} {question}"
        return question

    def advance_after_field(self, msg):
        text = self.normalize(msg)

        if self.current_step == "email" and text in {"skip", "no", "none", "no email"}:
            self.lead["email"] = "Skipped"

        if self.current_step == "phone" and self.lead["phone"] and not self.lead["phone_confirmed"]:
            self.current_step = "phone_confirmation"
            self.awaiting_phone_confirmation = True
            return self.prompt_for_phone_confirmation()

        if self.current_step == "address" and not self.lead["address"]:
            if self.looks_like_address(msg):
                self.lead["address"] = msg.strip()
            elif self.lead["category"] == "Sales" and self.looks_like_service_location(msg):
                self.lead["address"] = msg.strip()
            elif self.address_prompt_count >= 2:
                self.lead["address"] = self.address_candidate or msg.strip() or "Needs team review"
                self.lead["possible_transcription_error"] = True
                self.lead["sms_review_required"] = True
                return (
                    "No problem, I will flag the service location for the team to confirm "
                    "when they follow up. "
                    + self.next_question()
                )
            else:
                if msg.strip() and not self.address_candidate:
                    self.address_candidate = msg.strip()
                self.address_prompt_count += 1
                if self.lead["category"] == "Sales":
                    return "I may have missed the location. What city or service address is this for?"
                return "I may have missed the address. What is the service address? A street address is best."

        if self.current_step == "preferred_time":
            self.lead["preferred_time"] = msg.strip()

        if self.current_step == "system_status":
            self.lead["system_status"] = msg.strip()
            if self.is_likely_emergency(text):
                self.lead["priority"] = "High"

        return self.next_question()

    def next_question(self):
        category = self.lead["category"]

        if (
            self.lead["phone_confirmed"]
            and category in {"", "General Inquiry"}
            and self.is_vague_issue(self.lead["issue_summary"] or self.lead["issue"])
        ):
            self.current_step = "clarify_intent"
            return (
                "I want the service note to be clear. What problem should the team help with?"
            )

        if not self.lead["name"]:
            self.current_step = "name"
            return self.prompt_for_name()

        if not self.lead["phone"]:
            self.current_step = "phone"
            return self.prompt_for_phone()

        if not self.lead["phone_confirmed"]:
            self.current_step = "phone_confirmation"
            self.awaiting_phone_confirmation = True
            return self.prompt_for_phone_confirmation()

        if category in {"Support", "Sales"} and not self.lead["address"]:
            self.current_step = "address"
            return self.prompt_for_address()

        if category == "Support" and not self.lead["system_status"]:
            self.current_step = "system_status"
            return self.prompt_for_system_status()

        if category in {"Sales", "Billing"} and not self.lead["email"]:
            self.current_step = "email"
            return self.prompt_for_email()

        if not self.lead["preferred_time"] and category in {"Support", "Sales", "Billing", "Complaint", "Human Request", "Scheduling"}:
            self.current_step = "preferred_time"
            return self.prompt_for_preferred_time()

        if not self.awaiting_confirmation:
            self.current_step = "confirmation"
            self.awaiting_confirmation = True
            return self.build_confirmation()

        return self.submit_request()

    def prompt_for_name(self):
        category = self.lead["category"]
        if category == "Support" and self.lead["priority"] == "High":
            safety_note = ""
            if self.lead["danger_flag"] and not self.lead["safety_note_given"]:
                self.lead["safety_note_given"] = True
                safety_note = get_industry_profile(self.company_info.get("industry"))["safety_note"]
            return (
                "Oh no, that sounds miserable. I am glad you called. "
                "Let me get the essentials so the right person can help."
                + safety_note
                + " Can I get your first and last name?"
            )
        if category == "Support":
            return (
                "Got it. I will keep this simple and make sure the note is clear. "
                "Can I get your first and last name?"
            )
        if category == "Sales":
            return (
                "Sure, I can help get that started. "
                "Can I get your first and last name?"
            )
        if category == "Billing":
            return (
                "Of course. I will get the billing question tied to the right contact so the team can follow up cleanly. "
                "Can I get your first and last name?"
            )
        if category == "Complaint":
            return (
                "I am sorry that happened. I want this to land with the team clearly, not as a vague note. "
                "Can I get your first and last name?"
            )
        if category == "Human Request":
            return (
                "Of course. I will make sure a person from the team knows you asked to speak with someone. "
                "Can I get your first and last name?"
            )
        return "I can help with that. Can I get your first and last name?"

    def prompt_for_phone(self):
        first_name = self.lead["name"].split()[0]
        return (
            f"Thank you, {first_name}. What is the best phone number for the team to reach you?"
        )

    def prompt_for_phone_confirmation(self):
        return (
            f"I heard {self.format_phone_for_voice(self.lead['phone'])}. "
            "Is that the best number?"
        )

    def prompt_for_address(self):
        self.address_prompt_count += 1
        if self.lead["category"] == "Sales":
            return (
                "Perfect. The location helps the team confirm the service area and prepare the right options before they call. "
                "What city or service address is this for?"
            )
        return (
            "Thank you. What is the service address?"
        )

    def prompt_for_system_status(self):
        profile = get_industry_profile(self.company_info.get("industry"))
        if self.lead["priority"] == "High":
            return (
                "That helps. One quick detail will help the team understand how urgent this is before they call: "
                + profile["status_question_high"]
            )
        return (
            "That helps. One quick detail gives the technician a better starting point: "
            + profile["status_question_normal"]
        )

    def prompt_for_email(self):
        return (
            "If you have an email handy, we can add it for follow-up. "
            "You can also say skip."
        )

    def prompt_for_preferred_time(self):
        category = self.lead["category"]
        if category == "Support" and self.lead["priority"] == "High":
            return (
                "Okay, I have the main picture. "
                "What is the best time for them to reach you?"
            )
        if category == "Sales":
            return (
                "Great, that gives the team enough context to start the conversation in the right place. "
                "What is a good time for someone to follow up?"
            )
        if category == "Complaint":
            return (
                "Thank you for explaining that. I want the follow-up to happen at a time that works for you. "
                "When is the best time to reach you?"
            )
        if category == "Human Request":
            return (
                "I will note that you would like a person to follow up. "
                "What is the best time to reach you?"
            )
        return "Thanks. What is the best time for our team to follow up?"

    def intro_for_category(self):
        category = self.lead["category"]
        if category == "Support":
            safety_note = ""
            if self.lead["danger_flag"] and not self.lead["safety_note_given"]:
                self.lead["safety_note_given"] = True
                safety_note = get_industry_profile(self.company_info.get("industry"))["safety_note"]
            if self.lead["priority"] == "High":
                return "I am sorry you are dealing with that. I will mark this as a high-priority service issue." + safety_note
            return "I am sorry you are dealing with that. I will get this noted for the service team." + safety_note
        if category == "Sales":
            return "I would be happy to help get your quote request to the right person."
        if category == "Billing":
            return "I can help route that to the billing team."
        if category == "Complaint":
            return "I am sorry to hear that. I will make sure your concern is documented clearly."
        if category == "Human Request":
            return "Of course. I can document your request and have someone from the team follow up."
        if category == "Scheduling":
            return "I can help document that for the scheduling team."
        return "I can help with that."

    # -------------------------
    # Confirmation and close
    # -------------------------
    def handle_confirmation(self, msg):
        text = self.normalize(msg)

        affirmative = {"yes", "correct", "looks good", "that is right", "that's right", "submit", "send it", "all good"}
        negative = {"no", "not correct", "incorrect", "change that", "update that", "wait"}

        if any(phrase == text or phrase in text for phrase in affirmative):
            self.awaiting_confirmation = False
            return self.submit_request()

        if any(phrase == text or phrase in text for phrase in negative):
            self.awaiting_confirmation = False
            self.lead["possible_transcription_error"] = True
            self.lead["sms_review_required"] = True
            self.lead["verification_status"] = "Needs Team Review"
            return self.submit_request()

        self.apply_update(msg)
        self.awaiting_confirmation = False
        return "I added that. " + self.next_question()

    def handle_phone_confirmation(self, msg):
        text = self.normalize(msg)
        phone = self.extract_phone(msg)
        affirmative = {"yes", "correct", "that is right", "that's right", "yep", "yeah"}
        negative = {"no", "wrong", "incorrect", "not right", "change it"}

        if phone:
            self.lead["phone"] = phone
            return "Got it. " + self.prompt_for_phone_confirmation()

        if any(phrase == text or phrase in text for phrase in affirmative):
            self.lead["phone_confirmed"] = True
            self.awaiting_phone_confirmation = False
            return self.next_question()

        if any(phrase == text or phrase in text for phrase in negative):
            return "No problem, I want to get that right. Please say or enter the best phone number again, including the area code."

        return (
            "I want to make sure I heard the number correctly. "
            f"Was the number {self.format_phone_for_voice(self.lead['phone'])}?"
        )

    def ask_anything_else(self):
        self.awaiting_confirmation = False
        self.awaiting_anything_else = True
        return (
            "Great. I have enough to get this moving. "
            "Is there anything else you would like me to include before I submit it?"
        )

    def handle_anything_else(self, msg):
        text = self.normalize(msg)
        nothing_else = {"no", "nope", "nothing else", "that is all", "that's all", "all good"}

        if any(phrase == text or phrase in text for phrase in nothing_else):
            return self.submit_request()

        self.apply_update(msg)
        return "I added that to the request. " + self.submit_request()

    def apply_update(self, msg):
        self.update_context(msg)

        name = self.extract_name(msg)
        phone = self.extract_phone(msg)
        email = self.extract_email(msg)

        if name:
            self.lead["name"] = name
        if phone:
            self.lead["phone"] = phone
        if email:
            self.lead["email"] = email

        if self.looks_like_address(msg):
            self.lead["address"] = msg.strip()
            unit = self.extract_unit(msg)
            if unit:
                self.lead["unit"] = unit
        elif phone and self.contains_any(msg, ["phone", "number", "reach me"]):
            return
        elif email and self.contains_any(msg, ["email", "e mail"]):
            return
        else:
            self.lead["issue_summary"] = self.combine_summary(self.lead["issue_summary"], msg)
            self.classify_issue(self.lead["issue_summary"])

    def combine_summary(self, old, new):
        if not old:
            return new.strip()
        if new.strip().lower() in old.lower():
            return old
        return f"{old}; {new.strip()}"

    def submit_request(self):
        self.current_step = "complete"
        reason = self.lead["issue_summary"] or self.lead["issue"] or "your request"
        appreciation = (
            "Thank you so much for calling us today. We appreciate your business and value your time."
        )
        if self.lead["sms_review_required"]:
            self.lead["verified"] = False
            self.lead["verification_status"] = "Needs Team Review"
            closing_message = (
                f"I have your reason for calling noted as: {reason}. "
                "I have submitted the request so the team has it, and I flagged anything that may need confirmation. "
                + appreciation
            )
        else:
            self.lead["verified"] = True
            self.lead["verification_status"] = "Voice Confirmed"
            closing_message = (
                f"I have your reason for calling noted as: {reason}. "
                "I have submitted your request, and the team will follow up soon. "
                + appreciation
            )

        if not self.lead["sms_sent"]:
            self.lead["sms_sent"] = False

        return closing_message

    def build_confirmation(self):
        lines = [
            "Beautiful. Let me read back the important parts so we know the team has the right starting point:",
            "",
            f"Name: {self.lead['name']}",
            f"Phone: {self.lead['phone']}",
        ]

        optional_fields = [
            ("Address", self.lead["address"]),
            ("Unit", self.lead["unit"]),
            ("Reason for Call", self.lead["issue_summary"] or self.lead["issue"]),
            ("System Status", self.lead["system_status"]),
            ("Existing Appointment", "Yes" if self.lead["existing_appointment"] else ""),
            ("Appointment Request", self.lead["appointment_action"]),
            ("Best Time to Reach You", self.lead["preferred_time"]),
        ]

        for label, value in optional_fields:
            if value:
                lines.append(f"{label}: {value}")

        lines.extend(["", "Does that sound generally right?"])
        return "\n".join(lines)

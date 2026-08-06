import re
from datetime import datetime

from industry_profiles import get_industry_profile, get_industry_services


class AIReceptionist:
    DIALOGUE_VERSION = "atlas-always-probe-2026-08-06"

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
            "name": "Cheap Cold Air, Austin's HVAC Experts",
            "hours": "Monday through Friday from 9 AM to 5 PM, emergency services are available after hours",
            "service_areas": (
                "Austin, Round Rock, Cedar Park, Lakeway, Georgetown, "
                "downtown Austin, and nearby areas"
            ),
            "industry": "hvac",
            "services": get_industry_services("hvac"),
            "assistant_name": "Atlas",
            "greeting_script": "",
            "closing_script": "",
        }

        self.lead = {
            "name": "",
            "phone": "",
            "email": "",
            "address": "",
            "zip_code": "",
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

    def is_vertex_profile(self):
        return self.company_info.get("industry") in {
            "vertex",
            "mission_critical",
            "mission-critical",
            "enterprise_hvac",
        }

    def render_business_script(self, script, **values):
        if not script:
            return ""
        defaults = {
            "business_name": self.company_info.get("name", ""),
            "assistant_name": self.company_info.get("assistant_name", "Atlas"),
            "first_name": self.lead.get("name", "").split()[0] if self.lead.get("name") else "",
            "reason": self.lead.get("issue_summary") or self.lead.get("issue") or "",
        }
        defaults.update(values)
        try:
            return script.format(**defaults).strip()
        except (KeyError, ValueError):
            return script.strip()

    def build_greeting(self):
        custom_greeting = self.render_business_script(self.company_info.get("greeting_script", ""))
        if custom_greeting:
            return custom_greeting
        return (
            f"Thank you for calling {self.company_info['name']}. "
            f"I am {self.company_info.get('assistant_name', 'Atlas')}, your virtual assistant. "
            "How can I help you today?"
        )

    def build_closing_appreciation(self, reason):
        custom_closing = self.render_business_script(
            self.company_info.get("closing_script", ""),
            reason=reason,
        )
        if custom_closing:
            return custom_closing
        return "Thank you so much for calling us today. We appreciate your business and value your time. Goodbye."

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

    def extract_zip_code(self, msg):
        match = re.search(r"\b\d{5}(?:-\d{4})?\b", msg)
        return match.group(0) if match else None

    def format_phone_for_voice(self, phone):
        if len(phone) != 10:
            return phone
        return f"{phone[:3]}-{phone[3:6]}-{phone[6:]}"

    def is_valid_name(self, name):
        bad_words = {
            "yes",
            "and",
            "yeah",
            "yep",
            "sure",
            "okay",
            "ok",
            "um",
            "uh",
            "phone",
            "email",
            "it",
            "is",
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
            "and",
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
            "it is",
            "it's",
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
            "blvd",
            "boulevard",
            "ln",
            "lane",
            "court",
            "ct",
            "circle",
            "cir",
            "place",
            "pl",
            "parkway",
            "pkwy",
            "highway",
            "hwy",
            "terrace",
            "ter",
            "loop",
            "way",
            "trail",
        ]
        city_words = [
            "austin",
            "round rock",
            "cedar park",
            "pflugerville",
            "georgetown",
        ]
        number_words = {
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
            "hundred",
            "thousand",
        }
        words = [word.strip(".,") for word in text.split()]
        has_digit_number = bool(re.search(r"\b\d{1,6}\b", text))
        has_spoken_number = any(word in number_words for word in words[:6])
        has_street_word = any(word in street_words for word in words)
        has_city = any(city in text for city in city_words)

        if has_digit_number and has_street_word:
            return True
        if has_spoken_number and has_street_word:
            return True
        return self.current_step == "address" and has_digit_number and has_city

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
            "call me",
            "call back",
            "callback",
            "someone call",
            "someone call me",
            "can someone call me",
            "have someone call",
            "have someone call me",
            "follow up",
            "someone follow up",
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
        zip_code = self.extract_zip_code(msg)

        if name and not self.lead["name"]:
            self.lead["name"] = name
        if phone and not self.lead["phone"]:
            self.lead["phone"] = phone
        if email and not self.lead["email"]:
            self.lead["email"] = email
        if unit:
            self.lead["unit"] = unit
        if zip_code and not self.lead["zip_code"] and self.current_step in {"address", "zip_code"}:
            self.lead["zip_code"] = zip_code
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

        if self.is_duct_cleaning_request(text):
            self.lead["system_status"] = "Duct or vent cleaning request; no active system issue stated."
            return self.apply_classification("Support", "Normal", "Duct or vent cleaning service request.")

        if self.contains_any(text, profile["sales_keywords"]):
            return self.apply_classification("Sales", "Normal", "Quote, replacement, or installation language.")

        if self.contains_any(text, profile["support_keywords"]):
            priority = "High" if self.is_likely_emergency(text) else "Normal"
            return self.apply_classification("Support", priority, "Repair or active system problem.")

        if self.contains_any(text, ["hours", "open", "close", "service area", "do you service"]):
            return self.apply_classification("General Inquiry", "Normal", "General company question.")

        return self.apply_classification("General Inquiry", "Normal", "Could not confidently classify.")

    def is_duct_cleaning_request(self, text):
        duct_words = ["duct", "ducts", "duck", "ducks", "vent", "vents", "air vent", "air vents"]
        cleaning_words = ["clean", "cleaning", "cleaned", "clean out", "come by"]
        return any(word in text for word in duct_words) and any(
            word in text for word in cleaning_words
        )

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
        text = re.sub(r"\bduck(s)?\b", r"duct\1", text, flags=re.IGNORECASE)
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

        if self.is_service_area_question(text):
            city_answer = self.answer_service_area_question(text)
            answers.append(city_answer)

        if self.is_services_question(text):
            answers.append(self.answer_services_question(text))

        if self.contains_any(text, ["financing", "finance", "payment plan", "monthly payments"]):
            answers.append("Our team can review available financing options with you.")

        if self.contains_any(text, ["how soon", "come out today", "available today", "earliest appointment", "when can you come"]):
            answers.append("Availability depends on the schedule and urgency, but I can note that you would like the soonest available follow-up.")

        return " ".join(answers)

    def is_services_question(self, text):
        profile = get_industry_profile(self.company_info.get("industry"))
        service_question_phrases = [
            "what services",
            "which services",
            "services do you offer",
            "services you offer",
            "do you offer",
            "do you do",
            "do you guys do",
            "do you all do",
            "can you do",
            "can you guys do",
            "can you help with",
            "can you guys help with",
            "if you repair",
            "if you guys repair",
            "if you install",
            "if you guys install",
            "if you service",
            "if you guys service",
            "you repair",
            "you guys repair",
            "you install",
            "you guys install",
            "you service",
            "you guys service",
            "can you repair",
            "can you guys repair",
            "do you guys repair",
            "do you all repair",
            "do yall repair",
            "can you install",
            "can you guys install",
            "do you guys install",
            "do you all install",
            "do yall install",
            "can you service",
            "can you guys service",
            "are you able to repair",
            "are you able to install",
            "are you able to service",
            "do you fix",
            "do you guys fix",
            "can you fix",
            "can you guys fix",
            "do you handle",
            "do you install",
            "do you repair",
            "do you service",
        ]
        service_words = [
            "air conditioning",
            "ac",
            "a c",
            "heat pump",
            "heat pumps",
            "furnace",
            "furnaces",
            "ductless",
            "mini split",
            "mini splits",
            "ductwork",
            "duct work",
            "duct",
            "ducts",
            "vents",
            "indoor air",
            "dehumidifier",
            "dehumidifiers",
            "humidifier",
            "humidifiers",
            "thermostat",
            "thermostats",
        ] + profile.get("service_words", [])
        general_service_question = any(phrase in text for phrase in service_question_phrases)
        mentions_hvac_service = any(word in text for word in service_words)
        return (
            "what services" in text
            or "which services" in text
            or ("services" in text and "offer" in text)
            or (general_service_question and mentions_hvac_service)
        )

    def answer_services_question(self, text):
        profile = get_industry_profile(self.company_info.get("industry"))
        services = self.company_info["services"]
        specific_services = [
            (["critical cooling", "data center cooling", "server room cooling", "computer room cooling", "crac", "crack unit", "crah"], services.get("critical cooling")),
            (["electrical", "power", "breaker", "panel", "switchgear", "ups", "generator"], services.get("electrical")),
            (["preventive maintenance", "pm", "maintenance contract", "service contract"], services.get("preventive maintenance")),
            (["heat pump", "heat pumps"], services.get("heat pump")),
            (["furnace", "furnaces"], services.get("furnace")),
            (["ductless", "mini split"], services.get("ductless")),
            (["ductwork", "duct work", "duct", "ducts", "vents"], services.get("ductwork")),
            (["indoor air", "air quality", "humidity", "humidification", "dehumidifier", "dehumidifiers", "humidifier", "humidifiers"], services.get("indoor air")),
            (["controls", "building automation", "bms", "bas", "sensor", "thermostat", "thermostats"], services.get("thermostat")),
            (["air conditioning", "ac", "a c"], services.get("air conditioning")),
        ]
        for keywords, service in specific_services:
            if service and any(self.matches_service_keyword(text, keyword) for keyword in keywords):
                return f"Yes, we help with {service}."
        return profile.get("general_services_answer", "Yes, we can help with that service.")

    def matches_service_keyword(self, text, keyword):
        if keyword in {"ac", "a c"}:
            return bool(re.search(r"\ba\s*c\b", text))
        return keyword in text

    def is_services_question_only(self, msg):
        text = self.normalize(msg)
        request_phrases = [
            "i need",
            "i want",
            "i would like",
            "schedule",
            "book",
            "send someone",
            "come out",
            "appointment",
            "quote",
            "estimate",
        ]
        return self.is_services_question(text) and not any(phrase in text for phrase in request_phrases)

    def is_service_area_question(self, text):
        service_area_phrases = [
            "service area",
            "service areas",
            "areas do you service",
            "areas do you cover",
            "where do you service",
            "where do you guys service",
            "where do you cover",
            "where do you guys cover",
            "what areas",
            "do you service in",
            "do you service the area",
            "do you service my area",
            "do you service around",
            "do you work in",
            "do you go to",
            "can you come to",
            "able to service",
            "cover",
            "serve",
        ]
        service_cities = [
            "round rock",
            "cedar park",
            "pflugerville",
            "georgetown",
            "downtown austin",
            "austin",
        ]
        matched_service_area_phrase = False
        for phrase in service_area_phrases:
            if phrase in {"cover", "serve"}:
                if re.search(rf"\b{phrase}\b", text):
                    matched_service_area_phrase = True
                    break
            elif phrase in text:
                matched_service_area_phrase = True
                break

        return matched_service_area_phrase or any(
            city in text and any(word in text for word in ["service", "serve", "area", "work", "come"])
            for city in service_cities
        )

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
            "service area",
            "do you service",
            "do you work in",
            "able to service",
            "do you serve",
            "what are your hours",
            "are you open",
            "open today",
            "what areas",
            "areas do you service",
            "areas do you cover",
            "where do you service",
            "where do you guys service",
            "where do you cover",
            "where do you guys cover",
            "how soon",
            "when can you come",
            "available today",
            "earliest appointment",
            "what services",
            "which services",
            "services do you offer",
            "do you offer",
            "do you do",
            "do you guys do",
            "can you help with",
            "can you guys help with",
            "if you repair",
            "if you guys repair",
            "if you install",
            "if you guys install",
            "if you service",
            "if you guys service",
            "you repair",
            "you guys repair",
            "you install",
            "you guys install",
            "you service",
            "you guys service",
            "can you repair",
            "can you guys repair",
            "do you guys repair",
            "do you all repair",
            "do yall repair",
            "can you install",
            "can you guys install",
            "do you guys install",
            "do you all install",
            "do yall install",
            "can you service",
            "can you guys service",
            "are you able to repair",
            "are you able to install",
            "do you fix",
            "do you guys fix",
            "can you fix",
            "can you guys fix",
            "do you install",
            "do you repair",
            "do you fix",
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
        if self.is_services_question_only(msg):
            return True
        return (question_mark or any(x in text for x in question_phrases)) and not any(
            x in text for x in action_phrases
        )

    def is_service_area_only(self, msg):
        text = self.normalize(msg)
        if not self.is_service_area_question(text):
            return False

        issue_phrases = [
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
            "maintenance",
            "tune up",
            "new unit",
            "furnace",
            "heater",
            "air conditioner",
            "duct",
            "ducts",
            "duck",
            "ducks",
            "vent",
            "vents",
        ]
        return not any(phrase in text for phrase in issue_phrases)

    def is_no_service_request(self, msg):
        text = self.normalize(msg)
        no_request_phrases = [
            "just checking",
            "only checking",
            "just asking",
            "only asking",
            "for now",
            "not right now",
            "no service needed",
            "no request",
            "nothing else",
            "that is all",
            "that's all",
        ]
        return any(phrase in text for phrase in no_request_phrases)

    def is_general_question_only_summary(self, msg):
        return "general question only" in self.normalize(msg)

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
            return self.build_greeting()

        if self.awaiting_anything_else:
            return self.handle_anything_else(msg)

        if self.current_step == "phone_confirmation":
            return self.handle_phone_confirmation(msg)

        if self.current_step == "confirmation":
            return self.handle_confirmation(msg)

        if self.current_step == "confirmation_correction":
            self.apply_confirmation_correction(msg)
            self.awaiting_confirmation = False
            return "Thank you, I updated that. " + self.next_question()

        if self.current_step == "clarify_intent":
            faq_answer = self.answer_special_question(msg)
            if faq_answer and (
                self.is_question_only(msg)
                or self.is_service_area_only(msg)
                or self.is_services_question_only(msg)
            ):
                return faq_answer + " What can we help you with today?"
            if self.looks_like_address(msg):
                return "I caught the location. Before that, what problem should the team help with?"
            if self.is_no_service_request(msg):
                self.lead["issue"] = "General question only; no service request stated."
                self.lead["issue_summary"] = "General question only; no service request stated."
                self.apply_classification(
                    "General Inquiry",
                    "Normal",
                    "Caller asked a general question and did not request service.",
                )
                return self.next_question()
            clean_reason = self.clean_customer_reason(msg)
            self.lead["issue"] = clean_reason
            self.lead["issue_summary"] = clean_reason
            self.classify_issue(clean_reason)
            if self.lead["category"] == "General Inquiry" and self.is_vague_issue(msg):
                return "I want the service note to be clear. What problem should the team help with?"
            return self.next_question()

        if self.current_step in {"name", "phone", "email", "address", "zip_code", "preferred_time", "system_status"}:
            return self.advance_after_field(msg)

        faq_answer = self.answer_special_question(msg)

        if faq_answer and not self.lead["issue"] and (
            self.is_question_only(msg)
            or self.is_service_area_only(msg)
            or self.is_services_question_only(msg)
        ):
            self.current_step = "clarify_intent"
            return faq_answer + " What can we help you with today?"

        if not self.lead["issue"] and not self.is_greeting_only(msg):
            clean_reason = self.clean_customer_reason(msg)
            self.lead["issue"] = clean_reason
            self.lead["issue_summary"] = clean_reason
            self.classify_issue(msg)

        if faq_answer and self.lead["category"] == "General Inquiry":
            self.lead["issue"] = ""
            self.lead["issue_summary"] = ""
            self.current_step = "clarify_intent"
            return faq_answer + " What can we help you with today?"

        question = self.next_question()
        if faq_answer:
            return f"{faq_answer} {question}"
        return question

    def advance_after_field(self, msg):
        text = self.normalize(msg)
        control_text = text.strip(" .,-")
        faq_answer = self.answer_special_question(msg)
        if faq_answer and self.is_question_only(msg):
            return faq_answer + " " + self.prompt_for_current_step()

        if self.current_step == "email" and control_text in {"skip", "no", "none", "no email"}:
            self.lead["email"] = "Skipped"

        if self.current_step == "phone" and self.lead["phone"] and not self.lead["phone_confirmed"]:
            self.current_step = "phone_confirmation"
            self.awaiting_phone_confirmation = True
            return self.prompt_for_phone_confirmation()

        if self.current_step == "address" and not self.lead["address"]:
            if self.looks_like_address(msg):
                self.lead["address"] = msg.strip()
                zip_code = self.extract_zip_code(msg)
                if zip_code:
                    self.lead["zip_code"] = zip_code
            elif self.lead["category"] == "Sales" and self.looks_like_service_location(msg):
                self.lead["address"] = msg.strip()
                zip_code = self.extract_zip_code(msg)
                if zip_code:
                    self.lead["zip_code"] = zip_code
            elif self.address_prompt_count >= 2:
                if self.address_candidate and self.looks_like_service_location(self.address_candidate):
                    self.lead["address"] = self.address_candidate
                else:
                    self.lead["address"] = "Needs team review"
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

        if self.current_step == "zip_code":
            zip_code = self.extract_zip_code(msg)
            self.lead["zip_code"] = zip_code or msg.strip()

        if self.current_step == "system_status":
            self.lead["system_status"] = msg.strip()
            if self.is_likely_emergency(text):
                self.lead["priority"] = "High"

        return self.next_question()

    def prompt_for_current_step(self):
        if self.current_step == "name":
            return self.prompt_for_name()
        if self.current_step == "phone":
            return self.prompt_for_phone()
        if self.current_step == "phone_confirmation":
            return self.prompt_for_phone_confirmation()
        if self.current_step == "address":
            return self.prompt_for_address()
        if self.current_step == "zip_code":
            return self.prompt_for_zip_code()
        if self.current_step == "system_status":
            return self.prompt_for_system_status()
        if self.current_step == "email":
            return self.prompt_for_email()
        if self.current_step == "preferred_time":
            return self.prompt_for_preferred_time()
        return self.next_question()

    def next_question(self):
        category = self.lead["category"]

        if (
            self.lead["phone_confirmed"]
            and category in {"", "General Inquiry"}
            and self.is_vague_issue(self.lead["issue_summary"] or self.lead["issue"])
            and not self.is_general_question_only_summary(self.lead["issue_summary"] or self.lead["issue"])
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

        if category in {"Support", "Sales"} and not self.lead["zip_code"]:
            self.current_step = "zip_code"
            return self.prompt_for_zip_code()

        if self.should_probe_for_operational_risk(category):
            self.current_step = "system_status"
            return self.prompt_for_system_status()

        if category in {"Sales", "Billing"} and not self.lead["email"]:
            self.current_step = "email"
            return self.prompt_for_email()

        if not self.lead["preferred_time"] and category in {"Support", "Sales", "Billing", "Complaint", "Human Request", "Scheduling", "General Inquiry"}:
            self.current_step = "preferred_time"
            return self.prompt_for_preferred_time()

        if not self.awaiting_anything_else and category in {"Support", "Sales", "Billing", "Complaint", "Human Request", "Scheduling", "General Inquiry"}:
            return self.ask_anything_else()

        return self.submit_request()

    def should_probe_for_operational_risk(self, category):
        if self.lead["system_status"]:
            return False
        if category == "Support":
            return True
        if not (self.lead["issue_summary"] or self.lead["issue"]):
            return False
        if self.is_general_question_only_summary(self.lead["issue_summary"] or self.lead["issue"]):
            return False
        return category in {
            "Sales",
            "General Inquiry",
            "Human Request",
            "Scheduling",
            "Complaint",
        }

    def prompt_for_name(self):
        category = self.lead["category"]
        is_vertex_profile = self.is_vertex_profile()
        if category == "Support" and self.lead["priority"] == "High":
            safety_note = ""
            if self.lead["danger_flag"] and not self.lead["safety_note_given"]:
                self.lead["safety_note_given"] = True
                safety_note = get_industry_profile(self.company_info.get("industry"))["safety_note"]
            if is_vertex_profile:
                return (
                    "Understood. I will mark this as a high-priority facility service issue "
                    "and capture the essentials for the right team."
                    + safety_note
                    + " Can I get your first and last name?"
                )
            return (
                "Oh no, that sounds miserable. I am glad you called. "
                "Let me get the essentials so the right person can help."
                + safety_note
                + " Can I get your first and last name?"
            )
        if category == "Support":
            if is_vertex_profile:
                return (
                    "Understood. I will capture the service details clearly for the facility team. "
                    "Can I get your first and last name?"
                )
            return (
                "Got it. I will keep this simple and make sure the note is clear. "
                "Can I get your first and last name?"
            )
        if category == "Sales":
            if is_vertex_profile:
                return (
                    "I can route that request to the right commercial team. "
                    "Can I get your first and last name?"
                )
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
        if self.is_vertex_profile():
            return (
                "Thank you. What facility name, campus, or service address is this for?"
            )
        if self.lead["category"] == "Sales":
            return (
                "Perfect. The location helps the team confirm the service area and prepare the right options before they call. "
                "What city or service address is this for?"
            )
        return (
            "Thank you. What is the service address?"
        )

    def prompt_for_zip_code(self):
        return "And what is the ZIP code for that location?"

    def prompt_for_system_status(self):
        profile = get_industry_profile(self.company_info.get("industry"))
        if self.lead["priority"] == "High":
            return (
                "That helps. Just so the team understands the urgency, "
                + profile["status_question_high"]
            )
        if self.is_vertex_profile():
            return (
                "Before I route this, is anything down, alarming, overheating, losing power, "
                "or affecting critical equipment right now?"
            )
        return (
            "That helps. Just so the team has a better starting point, "
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
        if category == "General Inquiry":
            return (
                "No problem. If the team needs to follow up, "
                "what is the best callback time?"
            )
        return "Thanks. What is the best time for our team to follow up?"

    def intro_for_category(self):
        category = self.lead["category"]
        is_vertex_profile = self.is_vertex_profile()
        if category == "Support":
            safety_note = ""
            if self.lead["danger_flag"] and not self.lead["safety_note_given"]:
                self.lead["safety_note_given"] = True
                safety_note = get_industry_profile(self.company_info.get("industry"))["safety_note"]
            if is_vertex_profile and self.lead["priority"] == "High":
                return "Understood. I will mark this as a high-priority facility service issue." + safety_note
            if is_vertex_profile:
                return "Understood. I will get this documented for the facility service team." + safety_note
            if self.lead["priority"] == "High":
                return "I am sorry you are dealing with that. I will mark this as a high-priority service issue." + safety_note
            return "I am sorry you are dealing with that. I will get this noted for the service team." + safety_note
        if category == "Sales":
            if is_vertex_profile:
                return "I can route that request to the right commercial team."
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
        negative = {
            "no",
            "not correct",
            "incorrect",
            "wrong",
            "that is wrong",
            "that's wrong",
            "not right",
            "that is not right",
            "that's not right",
            "change that",
            "update that",
            "wait",
        }

        if any(phrase == text or phrase in text for phrase in affirmative):
            self.awaiting_confirmation = False
            return self.submit_request()

        if any(phrase == text or phrase in text for phrase in negative):
            self.awaiting_confirmation = False
            self.lead["possible_transcription_error"] = True
            self.lead["sms_review_required"] = True
            self.lead["verification_status"] = "Needs Team Review"
            self.current_step = "confirmation_correction"
            return (
                "No problem. Please restate the part that sounded wrong, "
                "or say the corrected service note."
            )

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
        self.current_step = "anything_else"
        return (
            "Got it. Is there anything else you would like to ask or have the team know?"
        )

    def handle_anything_else(self, msg):
        text = self.normalize(msg).strip(" .,-")
        nothing_else = {"no", "nope", "nothing else", "that is all", "that's all", "all good"}
        faq_answer = self.answer_special_question(msg)

        if faq_answer and (self.is_question_only(msg) or self.is_service_area_only(msg)):
            return faq_answer + " Is there anything else you would like to ask or have the team know?"

        if any(phrase == text or (" " in phrase and phrase in text) for phrase in nothing_else):
            return self.submit_request()

        self.apply_update(msg)
        return "I added that to the request. " + self.submit_request()

    def apply_confirmation_correction(self, msg):
        normalized = self.normalize(msg)
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
            self.lead["address"] = self.clean_corrected_address(msg)
            unit = self.extract_unit(msg)
            if unit:
                self.lead["unit"] = unit
        elif self.looks_like_time_correction(normalized):
            self.lead["preferred_time"] = self.clean_corrected_time(msg)
        elif not phone and not email and not name:
            corrected_reason = self.clean_corrected_reason(msg)
            if corrected_reason:
                self.lead["issue"] = corrected_reason
                self.lead["issue_summary"] = corrected_reason
                self.classify_issue(corrected_reason)

        self.lead["possible_transcription_error"] = False
        self.lead["sms_review_required"] = False
        self.lead["verification_status"] = "Corrected By Caller"

    def clean_corrected_address(self, msg):
        cleaned = re.sub(
            r"^(?:the\s+)?(?:correct\s+)?address\s+(?:is|should be)\s+",
            "",
            msg.strip(),
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", cleaned).strip(" .,-")

    def looks_like_time_correction(self, normalized):
        return any(
            phrase in normalized
            for phrase in [
                "best time",
                "good time",
                "better time",
                "call me",
                "reach me",
                "tomorrow",
                "today",
                "morning",
                "afternoon",
                "evening",
                "after",
                "before",
                "anytime",
            ]
        )

    def clean_corrected_time(self, msg):
        cleaned = re.sub(
            r"^(?:the\s+)?(?:best|good|better)\s+time\s+(?:is|would be|should be)\s+",
            "",
            msg.strip(),
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", cleaned).strip(" .,-")

    def clean_corrected_reason(self, msg):
        cleaned = re.sub(
            r"\b(?:send|sent)\s+(?:this|it|that)?\s*(?:over|through)\b",
            "",
            msg,
            flags=re.IGNORECASE,
        )
        changed = True
        cleaned = cleaned.strip()
        while changed:
            changed = False
            next_cleaned = re.sub(
                r"^(?:um|uh|yeah|yes|actually|sorry|no|wait|i said)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
            if next_cleaned != cleaned:
                cleaned = next_cleaned
                changed = True
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
        return cleaned

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
        reason = (self.lead["issue_summary"] or self.lead["issue"] or "your request").strip(" .,-")
        closing_appreciation = self.build_closing_appreciation(reason)
        if self.lead["sms_review_required"]:
            self.lead["verified"] = False
            self.lead["verification_status"] = "Needs Team Review"
            closing_message = (
                f"I have your reason for calling noted as: {reason}. "
                "I have submitted the request so the team has it, and I flagged anything that may need confirmation. "
                + closing_appreciation
            )
        else:
            self.lead["verified"] = True
            self.lead["verification_status"] = "Voice Confirmed"
            closing_message = (
                f"I have your reason for calling noted as: {reason}. "
                "I have submitted your request, and the team will follow up soon. "
                + closing_appreciation
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
            ("ZIP Code", self.lead["zip_code"]),
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

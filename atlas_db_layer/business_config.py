from dataclasses import dataclass

from repositories import BusinessRepository


@dataclass(frozen=True)
class BusinessConfig:
    business_id: int | None
    company_name: str
    assistant_name: str
    greeting_name: str
    industry: str
    notification_email: str
    timezone: str
    service_areas: str


DEFAULT_BUSINESS_CONFIG = BusinessConfig(
    business_id=None,
    company_name="ABC Heating & Air",
    assistant_name="Atlas",
    greeting_name="ABC Heating & Air",
    industry="hvac",
    notification_email="",
    timezone="America/Chicago",
    service_areas="Austin, Round Rock, Cedar Park, Pflugerville, Georgetown, and nearby areas",
)


def get_business_config_for_call(session, to_phone):
    business = BusinessRepository(session).get_by_twilio_number(to_phone)
    if not business:
        return DEFAULT_BUSINESS_CONFIG

    return BusinessConfig(
        business_id=business.id,
        company_name=business.name,
        assistant_name=business.assistant_name,
        greeting_name=business.greeting_name,
        industry=business.industry,
        notification_email=business.notification_email,
        timezone=business.timezone,
        service_areas=business.service_areas or DEFAULT_BUSINESS_CONFIG.service_areas,
    )


def apply_business_config_to_bot(bot, config: BusinessConfig):
    bot.company_info["name"] = config.greeting_name
    bot.company_info["service_areas"] = config.service_areas
    bot.company_info["assistant_name"] = config.assistant_name
    bot.company_info["industry"] = config.industry
    bot.company_info["notification_email"] = config.notification_email
    return bot

import argparse
import sys
from pathlib import Path


DB_LAYER_DIR = Path(__file__).resolve().parent / "atlas_db_layer"
sys.path.insert(0, str(DB_LAYER_DIR))

from database import init_db, session_scope
from repositories import BusinessRepository


def main():
    parser = argparse.ArgumentParser(description="Seed the first Atlas pilot business.")
    parser.add_argument("--name", required=True, help="Business name, for example 'ABC Heating & Air'.")
    parser.add_argument("--twilio-number", required=True, help="Twilio phone number for inbound calls.")
    parser.add_argument("--assistant-name", default="Atlas", help="Virtual assistant name.")
    parser.add_argument("--timezone", default="America/Chicago", help="Business timezone.")
    args = parser.parse_args()

    init_db()
    with session_scope() as session:
        business = BusinessRepository(session).create_business(
            name=args.name,
            twilio_number=args.twilio_number,
            assistant_name=args.assistant_name,
            timezone=args.timezone,
        )
        print(f"Seeded business id={business.id}: {business.name}")


if __name__ == "__main__":
    main()

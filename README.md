# Atlas Receptionist

Atlas is a Flask/Twilio AI receptionist prototype for local service businesses.

Current capabilities:

- Answers inbound Twilio calls.
- Uses a British male TTS voice by default.
- Captures caller name, phone, service address, issue, urgency, and preferred follow-up time.
- Sends a completed-call email notification to the business when SMTP settings are configured.
- Saves completed calls to local transcript files.
- Can connect to a SQLAlchemy database layer for multi-business routing, returning-customer recognition, service requests, and future appointment requests.

## Project Structure

```text
twilio_app.py
ai_receptionist.py
atlas_db_layer/
  appointment_service.py
  business_config.py
  database.py
  models.py
  repositories.py
  schema.sql
seed_first_business.py
requirements.txt
render.yaml
.env.example
.gitignore
```

## Local Setup

Create a virtual environment if you want one:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Create your local `.env` from the example:

```bash
cp .env.example .env
```

Then edit `.env` and add your real Twilio credentials.

Start Flask locally:

```bash
python3 twilio_app.py
```

Check the running version:

```bash
curl http://127.0.0.1:5002/version
```

## Seed The First Business

For local SQLite testing:

```bash
python3 seed_first_business.py --name "ABC Heating & Air" --twilio-number "+15125551212" --industry hvac
```

Use your real Twilio number. The app maps inbound calls by Twilio's `To` number.

Supported industry profiles:

```text
hvac
plumbing
roofing
electrical
general
```

Each Twilio number can map to a different business and industry:

```bash
python3 seed_first_business.py --name "Demo Plumbing" --twilio-number "+15125550001" --industry plumbing
python3 seed_first_business.py --name "Demo Roofing" --twilio-number "+15125550002" --industry roofing
python3 seed_first_business.py --name "Demo Electrical" --twilio-number "+15125550003" --industry electrical
```

To attach a business-specific notification email:

```bash
python3 seed_first_business.py --name "ABC Heating & Air" --twilio-number "+15125551212" --industry hvac --notification-email "owner@example.com"
```

## Email Notifications

SMS follow-up is disabled by default:

```text
SMS_FOLLOWUP_ENABLED=0
```

To email completed call summaries to the business, configure SMTP:

```text
BUSINESS_NOTIFICATION_EMAIL=owner@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=notifications@example.com
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=notifications@example.com
```

If a business has its own `notification_email`, Atlas uses that first. Otherwise it falls back to `BUSINESS_NOTIFICATION_EMAIL`.

## Twilio Webhook

After deploying, set your Twilio Voice webhook to:

```text
https://your-render-app.onrender.com/voice
```

Use `POST`.

## Render

Create a Render web service from this GitHub repo.

Recommended start command:

```bash
gunicorn twilio_app:app
```

Recommended build command:

```bash
pip install -r requirements.txt
```

Set environment variables in Render instead of committing secrets.

## Database

Locally, the default database is:

```text
sqlite:///atlas_local.db
```

On Render, create a Render Postgres database and set:

```text
DATABASE_URL=<Render internal Postgres URL>
```

For the pilot phase, `DB_AUTO_INIT=1` lets the app create tables automatically at startup. Later, replace this with migrations.

## Appointment Status

Atlas currently captures preferred appointment times as appointment requests.

It should say:

```text
I will include that preferred time so the team can confirm availability.
```

It should not say:

```text
You are booked for tomorrow at 2 PM.
```

Confirmed booking should wait until Google Calendar or another calendar provider is connected.

# GitHub And Render Checklist

## 1. Final Local Safety Check

- Confirm `.env` exists only locally and is not committed.
- Confirm `.gitignore` includes `.env`, transcript files, SQLite files, and `__pycache__/`.
- Confirm no real call transcripts are in the repo.
- Confirm no Twilio secrets are in code.
- Confirm your app starts locally:

```bash
python3 twilio_app.py
```

- Confirm version endpoint works:

```bash
curl http://127.0.0.1:5002/version
```

Expected:

```text
twilio_app_version: atlas-github-render-ready-2026-06-23
database_layer_available: true
```

If `database_layer_available` is false locally, install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## 2. Seed Local Test Business

Run:

```bash
python3 seed_first_business.py --name "ABC Heating & Air" --twilio-number "+1YOURTWILIONUMBER" --industry hvac
```

Then place a test call and confirm the app can sort the call by the Twilio `To` number.

## 3. Create GitHub Repo

- Create a private repo first.
- Suggested repo name: `atlas-receptionist`.
- Do not upload old output folders, transcript logs, `.env`, or local databases.
- Commit only the clean project folder contents.

Example local commands from inside this folder:

```bash
git init
git add .
git commit -m "Initial Atlas receptionist app"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/atlas-receptionist.git
git push -u origin main
```

## 4. Create Render Services

Create a Render Postgres database first.

Then create a Render Web Service connected to the GitHub repo.

Use:

```text
Build command: pip install -r requirements.txt
Start command: gunicorn twilio_app:app
```

## 5. Add Render Environment Variables

Set these in the Render web service:

```text
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER
PUBLIC_BASE_URL
REVIEW_BASE_URL
TWILIO_TTS_VOICE
TWILIO_TTS_LANGUAGE
DATABASE_URL
DB_AUTO_INIT
```

Use:

```text
DB_AUTO_INIT=1
TWILIO_TTS_VOICE=Polly.Brian-Generative
TWILIO_TTS_LANGUAGE=en-GB
```

Set `PUBLIC_BASE_URL` and `REVIEW_BASE_URL` to your Render app URL:

```text
https://your-render-app.onrender.com
```

## 6. Seed Render Database

After the first successful deploy, seed the first business in Render.

Options:

- Use Render Shell if available.
- Run a one-off command from the Render dashboard.
- Temporarily seed locally against Render's external database URL if Render provides one.

Command:

```bash
python3 seed_first_business.py --name "ABC Heating & Air" --twilio-number "+1YOURTWILIONUMBER"
```

## 7. Connect Twilio

In Twilio, set the phone number Voice webhook to:

```text
https://your-render-app.onrender.com/voice
```

Method:

```text
POST
```

Test:

```text
https://your-render-app.onrender.com/version
```

## 8. Test Calls Before Demo

Run these live scenarios:

- First-time repair caller.
- Returning caller from the same phone number.
- Caller with unclear service address, then team-review flag.
- Billing/general inquiry.
- High-priority no AC call.

Confirm:

- Atlas says the right business name.
- Returning caller greeting works.
- Call transcript saves.
- Service request saves.
- Preferred appointment time saves as a request, not a confirmed booking.
- No SMS review language is spoken when `SMS_FOLLOWUP_ENABLED=0`.
- Completed-call email notification is sent when SMTP settings are configured.

## 9. Before Approaching Businesses

Prepare:

- A short demo phone number.
- A one-page explanation of what Atlas does.
- A clear note that appointment booking is currently request capture until calendar sync is connected.
- A privacy statement: call details are stored for the business and not sold.
- A cleanup plan for test data.

Recommended positioning:

```text
Atlas answers missed or overflow calls, captures service requests, recognizes repeat callers, and gives your team clean call summaries by email.
```

## 10. Later Improvements

- Add Alembic migrations.
- Add Google Calendar OAuth and `business_calendars`.
- Add admin dashboard.
- Re-enable customer SMS review after Twilio messaging registration is approved.
- Add Twilio webhook signature validation.
- Add structured logging.
- Add tests around database save and returning-customer greeting.

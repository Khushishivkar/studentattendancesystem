# Roll Call

Attendance management app built with Flask. Teachers sign in, mark Present / Late / Absent
for each day, and see reports and low-attendance alerts.

## Features
- Sign-in with a first-run setup screen
- Daily attendance sheet with date and section filters, "All present" shortcut, editable past days
- Dashboard: today's summary, 14-day trend, students below the attendance threshold
- Students: add, add several at once, edit, delete, search, per-student history
- Reports by date range and section, with CSV download
- Safe forms (CSRF protection, POST for every change)

## Run locally
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 and create your account.

## Deploy on Render
1. Push this folder to a GitHub repo.
2. On Render choose **New > Blueprint** and select the repo. `render.yaml` creates the web service and a Postgres database.
3. Or update your existing web service: set the start command to
   `gunicorn app:app --workers 1 --threads 4 --timeout 60`, then add the environment variables
   `SECRET_KEY`, `DATABASE_URL` (from a Render Postgres database), `PYTHON_VERSION=3.12.3` and `TIMEZONE=Asia/Kolkata`.

Without `DATABASE_URL` the app uses SQLite, which Render's free web services erase on every deploy or restart.
Use Postgres to keep data.

## Settings (environment variables)
| Name | Default | Purpose |
|------|---------|---------|
| `SECRET_KEY` | dev value | Signs sessions. Set a long random value in production |
| `DATABASE_URL` | local SQLite | Postgres connection string |
| `TIMEZONE` | `Asia/Kolkata` | Decides what "today" means |
| `LOW_ATTENDANCE_THRESHOLD` | `75` | Percent below which a student is flagged |

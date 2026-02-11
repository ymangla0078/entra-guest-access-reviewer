# Entra Guest Access Reviewer (MVP)

A lightweight demo app that identifies potentially stale Microsoft Entra ID guest accounts from CSV exports.

## What it does
- Accepts a CSV export containing guest user records
- Flags likely stale guest access based on sign-in recency thresholds (90/180 days)
- Produces a reviewer-friendly table with recommended next actions

## How to get input CSV (Entra)
1. Open Microsoft Entra admin center.
2. Go to **Users** → **All users**.
3. Click **Download users** (CSV export).
4. Ensure CSV includes columns: `userPrincipalName`, `displayName`, `userType`, `accountEnabled`, `lastSignInDateTime`.
5. Upload that CSV in the app.

## Why this matters
Security teams often run quarterly access reviews manually. This MVP demonstrates how Provyra can automate first-pass analysis and reduce review effort.

## Security disclaimer
- Demo only. Recommendations are not auto-enforced.
- Keep least-privilege and human approval for any disable/removal decisions.
- Do not upload sensitive data beyond what is needed for testing.

## Run locally
```bash
pip install -r requirements.txt
python app.py
```

Health endpoint: `/health`

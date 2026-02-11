import io
import os
from datetime import datetime, timezone

import pandas as pd
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

HTML = """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Entra Guest Access Reviewer (MVP)</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <style>
    body { font-family: Arial, sans-serif; max-width: 920px; margin: 24px auto; padding: 0 16px; }
    .box { border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    h1 { margin-bottom: 8px; }
    .note { background: #fff8e1; border: 1px solid #ffd54f; }
    .small { color: #555; font-size: 14px; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #f5f5f5; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 12px; }
    .high { background: #ffebee; color: #b71c1c; }
    .medium { background: #fff3e0; color: #e65100; }
  </style>
</head>
<body>
  <h1>Entra Guest Access Reviewer (MVP)</h1>
  <p>Upload a CSV export of guest users to identify stale access candidates for manual review.</p>

  <div class=\"box note\">
    <strong>Security disclaimer (MVP):</strong>
    <ul>
      <li>This prototype processes uploaded CSV in-memory and does not persist files by design.</li>
      <li>Do not upload production secrets or sensitive attributes you cannot share in a demo tool.</li>
      <li>Findings are recommendations only; a human reviewer must approve any access removal.</li>
    </ul>
  </div>

  <div class=\"box\">
    <form method=\"post\" enctype=\"multipart/form-data\">
      <label>CSV file (expected columns: userPrincipalName, displayName, userType, accountEnabled, lastSignInDateTime)</label><br/><br/>
      <input type=\"file\" name=\"file\" accept=\".csv\" required />
      <button type=\"submit\">Analyze</button>
    </form>
  </div>

  {% if summary %}
  <div class=\"box\">
    <h3>Summary</h3>
    <p class=\"small\">Total guests: <strong>{{ summary.total_guests }}</strong> | Stale (>=90 days): <strong>{{ summary.stale_90 }}</strong> | Stale (>=180 days): <strong>{{ summary.stale_180 }}</strong></p>
  </div>

  <div class=\"box\">
    <h3>Flagged guests</h3>
    {% if rows %}
      <table>
        <thead><tr><th>User</th><th>UPN</th><th>Days since sign-in</th><th>Priority</th><th>Suggested action</th></tr></thead>
        <tbody>
          {% for r in rows %}
            <tr>
              <td>{{ r.displayName }}</td>
              <td>{{ r.userPrincipalName }}</td>
              <td>{{ r.days_since_signin }}</td>
              <td><span class=\"badge {{ 'high' if r.priority=='High' else 'medium' }}\">{{ r.priority }}</span></td>
              <td>{{ r.action }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <p>No stale guests found based on current thresholds.</p>
    {% endif %}
  </div>
  {% endif %}
</body>
</html>
"""


def _to_days(v):
    if pd.isna(v):
        return None
    ts = pd.to_datetime(v, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return int((datetime.now(timezone.utc) - ts.to_pydatetime()).days)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "entra-guest-access-reviewer", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(HTML, summary=None, rows=[])

    f = request.files.get("file")
    if not f:
        return render_template_string(HTML, summary=None, rows=[])

    raw = f.read()
    df = pd.read_csv(io.BytesIO(raw))

    # Normalize expected schema
    for col in ["displayName", "userPrincipalName", "userType", "accountEnabled", "lastSignInDateTime"]:
        if col not in df.columns:
            df[col] = None

    guests = df[df["userType"].astype(str).str.lower() == "guest"].copy()
    guests["days_since_signin"] = guests["lastSignInDateTime"].apply(_to_days)

    def classify(days):
        if days is None:
            return ("Medium", "Manual review: no sign-in timestamp")
        if days >= 180:
            return ("High", "Candidate to disable/remove after owner confirmation")
        if days >= 90:
            return ("Medium", "Send owner attestation request")
        return (None, None)

    priorities = guests["days_since_signin"].apply(classify)
    guests["priority"] = priorities.apply(lambda x: x[0])
    guests["action"] = priorities.apply(lambda x: x[1])

    flagged = guests[guests["priority"].notna()].copy()
    flagged = flagged.sort_values(by=["priority", "days_since_signin"], ascending=[True, False], na_position="last")

    summary = {
        "total_guests": int(len(guests)),
        "stale_90": int((guests["days_since_signin"].fillna(-1) >= 90).sum()),
        "stale_180": int((guests["days_since_signin"].fillna(-1) >= 180).sum()),
    }

    rows = flagged[["displayName", "userPrincipalName", "days_since_signin", "priority", "action"]].fillna("N/A").to_dict("records")
    return render_template_string(HTML, summary=summary, rows=rows)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))

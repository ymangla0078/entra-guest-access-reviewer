import csv
import io
import os
from datetime import datetime, timezone

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
    .steps { margin: 0; padding-left: 18px; }
  </style>
</head>
<body>
  <h1>Entra Guest Access Reviewer (MVP)</h1>
  <p>Upload a CSV export of guest users to identify stale access candidates for manual review.</p>

  <div class=\"box\">
    <h3 style=\"margin-top:0\">How to use (step-by-step)</h3>
    <ol class=\"steps\">
      <li>In Microsoft Entra admin center, export your users list as CSV (Users → All users → Download users).</li>
      <li>Make sure CSV includes these columns (case-sensitive): <code>userPrincipalName</code>, <code>displayName</code>, <code>userType</code>, <code>accountEnabled</code>, <code>lastSignInDateTime</code>.</li>
      <li>Upload the CSV below and click <b>Analyze</b>.</li>
      <li>Review flagged guests and confirm actions with app/data owners before disabling or removing access.</li>
    </ol>
  </div>

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

  {% if error %}
  <div class=\"box\" style=\"border-color:#f44336;background:#ffebee\">{{ error }}</div>
  {% endif %}

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


REQUIRED_COLS = ["displayName", "userPrincipalName", "userType", "accountEnabled", "lastSignInDateTime"]


def _to_days(value: str | None):
    if not value:
        return None
    try:
        v = value.strip().replace("Z", "+00:00")
        ts = datetime.fromisoformat(v)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).days)
    except Exception:
        return None


def _classify(days):
    if days is None:
        return ("Medium", "Manual review: no sign-in timestamp")
    if days >= 180:
        return ("High", "Candidate to disable/remove after owner confirmation")
    if days >= 90:
        return ("Medium", "Send owner attestation request")
    return (None, None)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "entra-guest-access-reviewer", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(HTML, summary=None, rows=[], error=None)

    f = request.files.get("file")
    if not f:
        return render_template_string(HTML, summary=None, rows=[], error="Please upload a CSV file.")

    try:
        text = f.read().decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return render_template_string(HTML, summary=None, rows=[], error="Invalid CSV: missing header row.")

        # normalize missing columns by adding empty values per row
        rows = []
        for r in reader:
            row = {k: (r.get(k) or "") for k in set(REQUIRED_COLS + list(r.keys()))}
            rows.append(row)

        guests = [r for r in rows if str(r.get("userType", "")).strip().lower() == "guest"]

        flagged = []
        stale_90 = 0
        stale_180 = 0

        for g in guests:
            days = _to_days(g.get("lastSignInDateTime"))
            if days is not None and days >= 90:
                stale_90 += 1
            if days is not None and days >= 180:
                stale_180 += 1

            priority, action = _classify(days)
            if priority:
                flagged.append(
                    {
                        "displayName": g.get("displayName") or "N/A",
                        "userPrincipalName": g.get("userPrincipalName") or "N/A",
                        "days_since_signin": days if days is not None else "N/A",
                        "priority": priority,
                        "action": action,
                    }
                )

        priority_rank = {"High": 0, "Medium": 1}
        flagged.sort(key=lambda x: (priority_rank.get(x["priority"], 9), -(x["days_since_signin"] if isinstance(x["days_since_signin"], int) else -1)))

        summary = {
            "total_guests": len(guests),
            "stale_90": stale_90,
            "stale_180": stale_180,
        }

        return render_template_string(HTML, summary=summary, rows=flagged, error=None)

    except Exception as e:
        return render_template_string(HTML, summary=None, rows=[], error=f"CSV processing error: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))

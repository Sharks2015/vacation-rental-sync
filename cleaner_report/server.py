"""
Cleaner Report App — Backend Server

Serves the cleaner report web app and handles:
  POST /verify-pin     → checks PIN against Airtable Cleaners table,
                          returns cleaner name + assigned property names
  POST /submit-report  → emails report to owner, forwards to GHL webhook
  GET  /               → serves index.html
"""
import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from flask import Flask, jsonify, request, send_from_directory
from pyairtable import Api
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = Flask(__name__, static_folder=os.path.dirname(__file__))

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]

# Email config (optional — set in .env to enable notifications)
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
NOTIFY_EMAIL  = os.environ.get("NOTIFY_EMAIL", "hello@paradiseshinecleaning.com")

GHL_WEBHOOK_URL = os.environ.get("GHL_WEBHOOK_URL", "")


@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "index.html")


_STATIC = ["logo.jpg", "icon-192.png", "icon-512.png", "icon-apple.png",
           "manifest.json", "sw.js"]

@app.route("/<path:filename>")
def static_files(filename):
    if filename in _STATIC:
        return send_from_directory(os.path.dirname(__file__), filename)
    return "Not found", 404


@app.route("/verify-pin", methods=["POST"])
def verify_pin():
    pin = str(request.json.get("pin", "")).strip()
    if not pin:
        return jsonify({"error": "PIN requerido"}), 400

    api = Api(AIRTABLE_API_KEY)

    cleaners = api.table(AIRTABLE_BASE_ID, "Cleaners").all()
    match = next(
        (r for r in cleaners if str(r["fields"].get("Pin", r["fields"].get("PIN", ""))) == pin),
        None,
    )

    if not match:
        return jsonify({"error": "PIN incorrecto"}), 401

    f = match["fields"]
    prop_ids = f.get("Properties", [])
    prop_names = []

    if prop_ids:
        all_props = api.table(AIRTABLE_BASE_ID, "Properties").all()
        lookup = {p["id"]: p["fields"].get("Name", "") for p in all_props}
        prop_names = [lookup[pid] for pid in prop_ids if pid in lookup]

    return jsonify({"name": f.get("Name", "").strip(), "properties": prop_names})


def _send_email(subject: str, body: str) -> None:
    if not SMTP_USER or not SMTP_PASSWORD:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = NOTIFY_EMAIL
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_USER, [NOTIFY_EMAIL], msg.as_string())
    except Exception as exc:
        app.logger.error("Email send failed: %s", exc)


def _forward_to_ghl(payload: dict) -> None:
    if not GHL_WEBHOOK_URL:
        return
    try:
        requests.post(GHL_WEBHOOK_URL, json=payload, timeout=8)
    except Exception as exc:
        app.logger.error("GHL forward failed: %s", exc)


@app.route("/submit-report", methods=["POST"])
def submit_report():
    data = request.json or {}
    prop         = data.get("property", "—")
    cleaner      = data.get("cleaner", "—")
    supplies     = data.get("supplies_needed", "Ninguno")
    damages      = data.get("damages_notes", "Ninguno")
    submitted_at = data.get("submitted_at", "—")

    subject = f"🧹 Reporte de limpieza — {prop}"
    body = (
        f"Propiedad:    {prop}\n"
        f"Limpiador(a): {cleaner}\n"
        f"Fecha/Hora:   {submitted_at}\n\n"
        f"── Suministros necesarios ──\n{supplies}\n\n"
        f"── Daños / Notas ──\n{damages}\n"
    )

    # Fire email and GHL in background so the client doesn't wait
    threading.Thread(target=_send_email, args=(subject, body), daemon=True).start()
    threading.Thread(target=_forward_to_ghl, args=(data,), daemon=True).start()

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)

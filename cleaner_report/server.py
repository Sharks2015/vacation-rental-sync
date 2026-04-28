import os
import base64
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from pyairtable import Api

load_dotenv()

BASEDIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASEDIR, static_url_path="")

_airtable = None

def get_airtable():
    global _airtable
    if _airtable is None:
        _airtable = Api(os.getenv("AIRTABLE_API_KEY"))
    return _airtable

def table(name):
    return get_airtable().table(os.getenv("AIRTABLE_BASE_ID"), name)

NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "hello@paradiseshinecleaning.com")
GHL_WEBHOOK_URL = os.getenv("GHL_WEBHOOK_URL", "")

SUPPLY_LABELS = {
    "toilet_paper": "Toilet Paper",
    "paper_towels": "Paper Towels",
    "sponge": "Sponge",
    "dish_soap": "Dish Soap",
    "hand_soap": "Hand Soap",
    "laundry_pods": "Laundry Pods",
    "dish_pods": "Dish Pods",
    "soap_bars": "Soap Bars",
    "shampoo": "Shampoo",
    "conditioner": "Conditioner",
    "body_wash": "Body Wash",
    "trash_kitchen": "Kitchen Trash Bags",
    "trash_bathroom": "Bathroom Trash Bags",
    "detergent": "Laundry Detergent",
    "bleach": "Bleach",
    "shampoo_refill": "Shampoo Refill",
    "conditioner_refill": "Conditioner Refill",
    "body_wash_refill": "Body Wash Refill",
    "snacks": "Snacks",
    "waters": "Waters",
    "toothbrushes": "Toothbrushes",
    "razors": "Razors",
    "cotton_swabs": "Cotton Swabs",
    "hand_wipes": "Hand Wipes",
    "mouthwash": "Mouthwash",
    "toilet_bands": "Toilet Bands",
    "stain_remover": "Stain Remover",
    "shampoo_bottles": "Shampoo Bottles",
    "conditioner_bottles": "Conditioner Bottles",
    "body_wash_bottles": "Body Wash Bottles",
    "soap_bottles": "Soap Bottles",
    "lotion_bottles": "Lotion Bottles",
    "toiletry_bags": "Toiletry Bags",
}


@app.route("/")
def index():
    return send_from_directory(BASEDIR, "index.html")


@app.route("/verify-pin", methods=["POST"])
def verify_pin():
    data = request.get_json() or {}
    pin = str(data.get("pin", "")).strip()
    if not pin:
        return jsonify({"success": False, "error": "PIN required"}), 400

    try:
        records = table("Cleaners").all(formula=f"{{PIN}}='{pin}'")
    except Exception as e:
        print(f"Airtable error: {e}")
        return jsonify({"success": False, "error": "Server error"}), 500

    if not records:
        return jsonify({"success": False, "error": "PIN not found"}), 401

    fields = records[0]["fields"]
    cleaner_name = fields.get("Name", "Cleaner")
    property_ids = fields.get("Properties", [])

    properties = []
    props_tbl = table("Properties")
    for pid in property_ids:
        try:
            p = props_tbl.get(pid)
            name = p["fields"].get("Name", "")
            if name:
                properties.append(name)
        except Exception:
            pass

    return jsonify({"success": True, "name": cleaner_name, "properties": properties})


@app.route("/submit-report", methods=["POST"])
def submit_report():
    data = request.get_json() or {}
    cleaner_name = data.get("cleaner_name", "")
    property_name = data.get("property_name", "")
    fully_stocked = data.get("fully_stocked", False)
    supplies = data.get("supplies", {})
    damage_notes = data.get("damage_notes", "")
    photos = data.get("photos", [])

    manager = _get_property_manager(property_name)

    try:
        _send_email(cleaner_name, property_name, fully_stocked, supplies, damage_notes, photos, manager)
    except Exception as e:
        print(f"Email error: {e}")

    if GHL_WEBHOOK_URL:
        try:
            _forward_to_ghl(cleaner_name, property_name, fully_stocked, supplies, damage_notes, manager)
        except Exception as e:
            print(f"GHL webhook error: {e}")

    try:
        _save_report(cleaner_name, property_name, fully_stocked, supplies, damage_notes, photos)
    except Exception as e:
        print(f"Save report error: {e}")

    return jsonify({"success": True})


@app.route("/history", methods=["GET"])
def get_history():
    cleaner_name = request.args.get("cleaner", "")
    try:
        reports_tbl = table("Cleaning Reports")
        formula = f"{{Cleaner Name}}='{cleaner_name}'" if cleaner_name else ""
        records = reports_tbl.all(formula=formula) if formula else reports_tbl.all()
        reports = []
        for r in sorted(records, key=lambda x: x["fields"].get("Submitted At", ""), reverse=True)[:50]:
            f = r["fields"]
            reports.append({
                "property": f.get("Property", ""),
                "cleaner": f.get("Cleaner Name", ""),
                "submitted_at": f.get("Submitted At", ""),
                "fully_stocked": f.get("Fully Stocked", False),
                "supplies_flagged": f.get("Supplies Flagged", ""),
                "damage_notes": f.get("Damage Notes", ""),
                "photo_count": f.get("Photo Count", 0),
            })
        return jsonify({"success": True, "reports": reports})
    except Exception as e:
        print(f"History error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _save_report(cleaner_name, property_name, fully_stocked, supplies, damage_notes, photos):
    flagged = "" if fully_stocked else ", ".join(
        f"{SUPPLY_LABELS.get(k, k)}: {STATUS_LABELS.get(v, v)}"
        for k, v in supplies.items() if v
    )
    record = {
        "Property": property_name,
        "Cleaner Name": cleaner_name,
        "Submitted At": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Fully Stocked": fully_stocked,
        "Photo Count": len([p for p in photos if p]),
    }
    if flagged:
        record["Supplies Flagged"] = flagged
    if damage_notes:
        record["Damage Notes"] = damage_notes
    table("Cleaning Reports").create(record)


def _get_property_manager(property_name):
    try:
        records = table("Properties").all(formula=f"{{Name}}='{property_name}'")
        if not records:
            return {}
        fields = records[0]["fields"]
        manager_ids = fields.get("Property Manager", [])
        if not manager_ids:
            return {}
        mgr = table("Property Managers").get(manager_ids[0])
        f = mgr["fields"]
        return {
            "name": f.get("Name", ""),
            "email": f.get("Email", ""),
            "phone": f.get("Phone", ""),
        }
    except Exception as e:
        print(f"Manager lookup error: {e}")
        return {}


STATUS_LABELS = {"running_low": "⚠️ Running Low", "completely_out": "🔴 Completely Out"}
STATUS_COLORS = {"running_low": "#FEF3C7", "completely_out": "#FEE2E2"}


def _supplies_html(fully_stocked, supplies):
    if fully_stocked:
        return "<p style='color:#059669;font-weight:600'>✅ All supplies fully stocked</p>"
    if not supplies:
        return "<p style='color:#6B7280'>No supply issues reported.</p>"
    rows = "".join(
        f"<tr style='background:{STATUS_COLORS.get(v,'white')}'>"
        f"<td style='padding:8px 16px;border-bottom:1px solid #F3F4F6'>"
        f"{SUPPLY_LABELS.get(k, k.replace('_',' ').title())}</td>"
        f"<td style='padding:8px 16px;border-bottom:1px solid #F3F4F6;font-weight:600'>"
        f"{STATUS_LABELS.get(v, v)}</td></tr>"
        for k, v in supplies.items() if v
    )
    return (
        "<table style='border-collapse:collapse;width:100%;max-width:420px;font-size:15px'>"
        "<thead><tr style='background:#F3F4F6'>"
        "<th style='padding:10px 16px;text-align:left'>Item</th>"
        "<th style='padding:10px 16px;text-align:left'>Status</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _build_email(cleaner_name, property_name, fully_stocked, supplies, damage_notes, photos, manager, recipient_email, recipient_name):
    smtp_user = os.getenv("SMTP_USER", "")
    subject = f"Cleaning Report — {property_name} — {datetime.now().strftime('%b %d, %Y')}"

    mgr_line = ""
    if manager:
        mgr_line = (
            f"<p><strong>Property Manager:</strong> {manager.get('name','')} &nbsp;|&nbsp; "
            f"{manager.get('email','')} &nbsp;|&nbsp; {manager.get('phone','')}</p>"
        )

    dmg_section = ""
    if damage_notes:
        dmg_section = (
            f"<div style='margin:20px 0;padding:16px;background:#FEF2F2;border-left:4px solid #EF4444;border-radius:8px'>"
            f"<strong style='color:#B91C1C'>Damages, Smells &amp; Stains:</strong>"
            f"<p style='margin:8px 0 0;color:#374151'>{damage_notes}</p></div>"
        )

    photo_tags = "".join(
        f"<img src='cid:photo{i}' style='max-width:100%;border-radius:10px;margin-bottom:12px;display:block'>"
        for i in range(len(photos))
    )
    photo_section = f"<h3 style='color:#1B3A6B'>Photos</h3>{photo_tags}" if photos else ""

    html = f"""
    <html><body style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;
      color:#1F2937;max-width:600px;margin:auto;padding:24px'>
      <div style='background:#1B3A6B;padding:24px;border-radius:12px 12px 0 0;text-align:center'>
        <h1 style='color:white;margin:0;font-size:22px'>Paradise Shine Cleaning</h1>
        <p style='color:#BFDBFE;margin:6px 0 0;font-size:14px'>Cleaning Report</p>
      </div>
      <div style='background:white;padding:24px;border:1px solid #E5E7EB;border-top:none;border-radius:0 0 12px 12px'>
        <p><strong>Property:</strong> {property_name}</p>
        <p><strong>Cleaner:</strong> {cleaner_name}</p>
        <p><strong>Date:</strong> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
        {mgr_line}
        <hr style='border:none;border-top:1px solid #E5E7EB;margin:20px 0'>
        <h3 style='color:#1B3A6B'>Inventory</h3>
        {_supplies_html(fully_stocked, supplies)}
        {dmg_section}
        {photo_section}
      </div>
    </body></html>
    """

    msg = MIMEMultipart("related")
    msg["From"] = smtp_user
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    for i, photo_b64 in enumerate(photos):
        try:
            if "," in photo_b64:
                photo_b64 = photo_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(photo_b64)
            img = MIMEImage(img_bytes)
            img.add_header("Content-ID", f"<photo{i}>")
            img.add_header("Content-Disposition", "inline", filename=f"photo_{i+1}.jpg")
            msg.attach(img)
        except Exception as e:
            print(f"Photo attach error [{i}]: {e}")

    return msg


def _send_email(cleaner_name, property_name, fully_stocked, supplies, damage_notes, photos, manager):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")

    recipients = [NOTIFY_EMAIL]

    # If there are photos or damage notes, also email the property manager
    manager_email = manager.get("email", "") if manager else ""
    if (photos or damage_notes) and manager_email and manager_email != NOTIFY_EMAIL:
        recipients.append(manager_email)

    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        for recipient in recipients:
            msg = _build_email(
                cleaner_name, property_name, fully_stocked, supplies,
                damage_notes, photos, manager, recipient, recipient
            )
            s.send_message(msg)
            print(f"Email sent to {recipient}")


def _forward_to_ghl(cleaner_name, property_name, fully_stocked, supplies, damage_notes, manager):
    supply_summary = "Fully stocked" if fully_stocked else ", ".join(
        f"{SUPPLY_LABELS.get(k, k)}: {STATUS_LABELS.get(v, v)}"
        for k, v in supplies.items() if v
    ) or "No issues"
    payload = {
        "cleaner_name": cleaner_name,
        "property_name": property_name,
        "damage_notes": damage_notes,
        "manager_name": manager.get("name", ""),
        "manager_email": manager.get("email", ""),
        "manager_phone": manager.get("phone", ""),
        "supplies_summary": supply_summary,
        "submitted_at": datetime.now().isoformat(),
    }
    requests.post(GHL_WEBHOOK_URL, json=payload, timeout=10)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)

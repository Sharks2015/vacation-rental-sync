import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from pyairtable import Api

load_dotenv()

_ET = ZoneInfo("America/New_York")

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

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    api_key=os.getenv("CLOUDINARY_API_KEY", ""),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", ""),
)

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
    smell_notes = data.get("smell_notes", "")
    stain_notes = data.get("stain_notes", "")
    photos = data.get("photos", [])

    def _process():
        # Upload photos to Cloudinary first so we have URLs for everything else
        photo_urls = _upload_photos(photos, property_name)

        manager = _get_property_manager(property_name)

        if GHL_WEBHOOK_URL:
            try:
                _forward_to_ghl(cleaner_name, property_name, fully_stocked,
                                supplies, damage_notes, smell_notes, stain_notes,
                                manager, photo_urls)
            except Exception as e:
                print(f"GHL webhook error: {e}")

        try:
            _save_report(cleaner_name, property_name, fully_stocked,
                         supplies, damage_notes, smell_notes, stain_notes, photo_urls)
        except Exception as e:
            print(f"Save report error: {e}")

    threading.Thread(target=_process, daemon=True).start()
    return jsonify({"success": True})


MANAGER_PIN = os.getenv("MANAGER_PIN", "")


@app.route("/manager")
def manager_dashboard():
    return send_from_directory(BASEDIR, "manager.html")


@app.route("/manager-verify", methods=["POST"])
def manager_verify():
    data = request.get_json() or {}
    pin = str(data.get("pin", "")).strip()
    if not MANAGER_PIN:
        return jsonify({"success": False, "error": "Not configured"}), 500
    if pin != MANAGER_PIN:
        return jsonify({"success": False, "error": "Invalid PIN"}), 401
    return jsonify({"success": True})


@app.route("/manager-reports", methods=["GET"])
def manager_reports():
    try:
        records = table("Cleaning Reports").all()
        reports = []
        properties = set()
        for r in sorted(records, key=lambda x: x["fields"].get("Submitted At", ""), reverse=True):
            f = r["fields"]
            prop = f.get("Property", "")
            if prop:
                properties.add(prop)
            # Extract photo URLs from Airtable attachments field
            photo_attachments = f.get("Photos", [])
            photo_urls = [a.get("url", "") for a in photo_attachments if a.get("url")]
            reports.append({
                "property": prop,
                "cleaner": f.get("Cleaner Name", ""),
                "submitted_at": f.get("Submitted At", ""),
                "fully_stocked": f.get("Fully Stocked", False),
                "supplies_flagged": f.get("Supplies Flagged", ""),
                "damage_notes": f.get("Damage Notes", ""),
                "photo_count": f.get("Photo Count", 0),
                "photo_urls": photo_urls,
            })
        return jsonify({"success": True, "reports": reports, "properties": sorted(properties)})
    except Exception as e:
        print(f"Manager reports error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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


def _upload_photos(photos, property_name):
    if not photos or not os.getenv("CLOUDINARY_CLOUD_NAME"):
        return []
    urls = []
    now_et = datetime.now(_ET)
    ts_folder = now_et.strftime("%Y%m%d_%H%M%S")
    # Visible stamp burned onto the image: "05/09/2026  10:30 PM ET | 931 SE 5th Ave"
    prop_short = property_name[:35].replace("'", "").replace(",", "")
    stamp_text = f"{now_et.strftime('%m/%d/%Y  %I:%M %p ET')}  |  {prop_short}"
    folder = f"psc/{property_name.replace(' ', '_').replace('/', '_')}/{ts_folder}"

    for i, photo_b64 in enumerate(photos):
        if not photo_b64:
            continue
        try:
            data = photo_b64.split(",", 1)[1] if "," in photo_b64 else photo_b64
            public_id = f"{folder}/photo_{i + 1}"

            cloudinary.uploader.upload(
                f"data:image/jpeg;base64,{data}",
                public_id=public_id,
                resource_type="image",
                format="jpg",
                overwrite=True,
            )

            # Burn timestamp + property name onto the image via Cloudinary transformation
            stamped_url, _ = cloudinary_url(
                public_id,
                format="jpg",
                secure=True,
                transformation=[
                    # Dark semi-transparent banner across the bottom
                    {
                        "overlay": {
                            "font_family": "Arial",
                            "font_size": 32,
                            "font_weight": "bold",
                            "text": stamp_text,
                        },
                        "background": "rgb:000000bb",
                        "color": "white",
                        "gravity": "south",
                        "width": "1.0",
                        "crop": "fit",
                        "padding": 12,
                        "y": 0,
                    }
                ],
            )

            urls.append(stamped_url)
            print(f"[Cloudinary] photo {i + 1} stamped → {stamped_url}")
        except Exception as e:
            print(f"[Cloudinary] photo {i + 1} error: {e}")
    return urls


STATUS_LABELS = {"running_low": "Running Low", "completely_out": "Completely Out"}


def _save_report(cleaner_name, property_name, fully_stocked, supplies, damage_notes, smell_notes, stain_notes, photo_urls):
    flagged = "" if fully_stocked else ", ".join(
        f"{SUPPLY_LABELS.get(k, k)}: {STATUS_LABELS.get(v, v)}"
        for k, v in supplies.items() if v
    )
    combined_notes = "\n\n".join(filter(None, [
        f"DAMAGE: {damage_notes}" if damage_notes else "",
        f"SMELL: {smell_notes}" if smell_notes else "",
        f"STAINS:\n{stain_notes}" if stain_notes else "",
    ]))
    record = {
        "Property": property_name,
        "Cleaner Name": cleaner_name,
        "Submitted At": datetime.now(_ET).strftime("%Y-%m-%d %H:%M"),
        "Fully Stocked": fully_stocked,
        "Photo Count": len(photo_urls),
    }
    if flagged:
        record["Supplies Flagged"] = flagged
    if combined_notes:
        record["Damage Notes"] = combined_notes
    if photo_urls:
        record["Photos"] = [{"url": url} for url in photo_urls]
    table("Cleaning Reports").create(record)


def _get_property_manager(property_name):
    try:
        records = table("Properties").all(formula=f"{{Name}}='{property_name}'")
        print(f"[PM] '{property_name}' → {len(records)} record(s) found")
        if not records:
            return {}
        fields = records[0]["fields"]
        manager_ids = fields.get("Property Managers", [])
        print(f"[PM] Manager IDs: {manager_ids}")
        if not manager_ids:
            return {}
        mgr = table("Property Managers").get(manager_ids[0])
        f = mgr["fields"]
        email = (f.get("Email", "") or "").strip()
        print(f"[PM] Found: {f.get('Name', '')} <{email}>")
        cc_phone = fields.get("CC Phone", "")
        return {
            "name": f.get("Name", ""),
            "email": email,
            "phone": f.get("Phone", ""),
            "cc_phone": cc_phone,
        }
    except Exception as e:
        print(f"[PM] Lookup error: {e}")
        return {}


def _forward_to_ghl(cleaner_name, property_name, fully_stocked, supplies, damage_notes, smell_notes, stain_notes, manager, photo_urls):
    supply_summary = "Fully stocked" if fully_stocked else ", ".join(
        f"{SUPPLY_LABELS.get(k, k)}: {STATUS_LABELS.get(v, v)}"
        for k, v in supplies.items() if v
    ) or "No issues"

    submitted_at = datetime.now(_ET).strftime("%B %d, %Y at %I:%M %p ET")

    photo_links = ""
    if photo_urls:
        photo_lines = [f"Photo {i + 1}: {url}" for i, url in enumerate(photo_urls)]
        photo_links = "\n".join(photo_lines)

    # Clean report body — property/cleaner are in the greeting, start from date
    lines = [
        f"Date: {submitted_at}",
        f"Inventory: {supply_summary}",
    ]
    if damage_notes:
        lines += ["", f"Damage: {damage_notes}"]
    if smell_notes:
        lines += ["", f"Smell: {smell_notes}"]
    if stain_notes:
        lines += ["", f"Stains: {stain_notes}"]
    if photo_links:
        lines += ["", f"Photos: {photo_links}"]

    report_body = "\n".join(lines)

    base = {
        "cleaner_name": cleaner_name,
        "property_name": property_name,
        "damage_notes": damage_notes,
        "smell_notes": smell_notes,
        "stain_notes": stain_notes,
        "supplies_summary": supply_summary,
        "report_body": report_body,
        "photo_links": photo_links or "No photos",
        "photo_count": len(photo_urls),
        "submitted_at": submitted_at,
        "notify_email": NOTIFY_EMAIL,
    }

    # Primary manager — GHL sends SMS + email
    requests.post(GHL_WEBHOOK_URL, json={**base,
        "manager_name": manager.get("name", ""),
        "manager_email": manager.get("email", ""),
        "manager_phone": manager.get("phone", ""),
    }, timeout=10)
    print(f"[GHL] Webhook sent — manager: {manager.get('name', '')} | photos: {len(photo_urls)}")

    # CC phone (e.g. Jeanine) — second webhook for SMS only
    cc_phone = manager.get("cc_phone", "")
    if cc_phone:
        requests.post(GHL_WEBHOOK_URL, json={**base,
            "manager_name": "CC",
            "manager_email": "",
            "manager_phone": cc_phone,
        }, timeout=10)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)

"""
Cleaner Report App — Backend Server

Serves the cleaner report web app and handles:
  POST /verify-pin  → checks PIN against Airtable Cleaners table,
                       returns cleaner name + assigned property names
  GET  /            → serves index.html
"""
import os
from flask import Flask, jsonify, request, send_from_directory
from pyairtable import Api
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = Flask(__name__, static_folder=os.path.dirname(__file__))

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)

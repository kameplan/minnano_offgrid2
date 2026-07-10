#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

TARGET_DEVICE_ID = "33c4ee68-fba7-4ba5-98e1-4fb4a062beab"
API_URL = "https://api.nature.global/1/echonetlite/appliances"
OUTPUT_FILE = "data/home_status.json"
JST = timezone(timedelta(hours=9))

def get_token():
    token = os.environ.get("NATURE_REMO_TOKEN")
    if not token:
        print("エラー: 環境変数 NATURE_REMO_TOKEN が設定されていません。", file=sys.stderr)
        sys.exit(1)
    return token

def fetch_appliances(token):
    req = urllib.request.Request(API_URL, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data.get("appliances", [])

def hex_to_int(hex_str, signed=False, bits=32):
    if not hex_str:
        return None
    val = int(hex_str, 16)
    if signed and val >= (1 << (bits - 1)):
        val -= (1 << bits)
    return val

def get_property(appliance, epc):
    for p in appliance.get("properties", []):
        if p.get("epc") == epc:
            return p.get("val")
    return None

def parse_home_status(appliances):
    targets = [a for a in appliances if a.get("Device", {}).get("id") == TARGET_DEVICE_ID]
    result = {"updated_at": datetime.now(JST).isoformat(), "battery": None, "solar": {"power_w": 0}, "grid": None}
    solar_total_w = 0
    solar_found = False
    for a in targets:
        a_type = a.get("type")
        if a_type == "EL_STORAGE_BATTERY":
            soc = hex_to_int(get_property(a, "e4"))
            remaining_wh = hex_to_int(get_property(a, "e2"))
            result["battery"] = {
                "soc_percent": soc,
                "remaining_wh": remaining_wh,
                "remaining_kwh": round(remaining_wh / 1000, 2) if remaining_wh is not None else None,
            }
        elif a_type == "EL_SOLAR_POWER":
            w = hex_to_int(get_property(a, "e0"))
            if w is not None:
                solar_total_w += w
                solar_found = True
        elif a_type == "EL_SMART_METER":
            instantaneous = hex_to_int(get_property(a, "e7"), signed=True)
            if instantaneous is not None:
                result["grid"] = {"power_w": instantaneous, "status": "selling" if instantaneous < 0 else "buying"}
    if solar_found:
        result["solar"]["power_w"] = solar_total_w
    return result

def main():
    token = get_token()
    appliances = fetch_appliances(token)
    status = parse_home_status(appliances)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {OUTPUT_FILE}")
    print(json.dumps(status, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

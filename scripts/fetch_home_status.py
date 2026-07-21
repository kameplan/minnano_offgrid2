#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
import urllib.request
from datetime import datetime, timezone, timedelta

# ====== Nature Remo 設定 ======
TARGET_DEVICE_ID = "33c4ee68-fba7-4ba5-98e1-4fb4a062beab"
NATURE_API_URL = "https://api.nature.global/1/echonetlite/appliances"

# ====== SwitchBot 設定 ======
SWITCHBOT_DEVICES = {
    "outdoor": {"id": "CE2D46455D9C", "label": "外気"},
    "floor1": {"id": "CE736F4619A8", "label": "1F"},
    "floor2": {"id": "F27D74F65E6A", "label": "2F"},
    "attic": {"id": "FAB43A8C00F2", "label": "小屋裏"},
}
SWITCHBOT_API_BASE = "https://api.switch-bot.com/v1.1/devices"

OUTPUT_FILE = "data/home_status.json"
JST = timezone(timedelta(hours=9))


def get_env(name):
    val = os.environ.get(name)
    if not val:
        print(f"エラー: 環境変数 {name} が設定されていません。", file=sys.stderr)
        sys.exit(1)
    return val


# ---------- Nature Remo ----------

def fetch_nature_appliances(token):
    req = urllib.request.Request(NATURE_API_URL, headers={"Authorization": f"Bearer {token}"})
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


def parse_nature_status(appliances):
    targets = [a for a in appliances if a.get("Device", {}).get("id") == TARGET_DEVICE_ID]
    result = {"battery": None, "solar": {"power_w": 0}, "grid": None}
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


# ---------- SwitchBot ----------

def switchbot_headers(token, secret):
    nonce = str(uuid.uuid4())
    t = str(int(round(time.time() * 1000)))
    string_to_sign = f"{token}{t}{nonce}".encode("utf-8")
    sign = base64.b64encode(
        hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    return {
        "Authorization": token,
        "sign": sign,
        "t": t,
        "nonce": nonce,
        "Content-Type": "application/json",
    }


def fetch_switchbot_status(device_id, token, secret):
    req = urllib.request.Request(
        f"{SWITCHBOT_API_BASE}/{device_id}/status",
        headers=switchbot_headers(token, secret),
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data.get("body", {})


def parse_switchbot_status(token, secret):
    result = {}
    for key, info in SWITCHBOT_DEVICES.items():
        try:
            body = fetch_switchbot_status(info["id"], token, secret)
            result[key] = {
                "label": info["label"],
                "temperature": body.get("temperature"),
                "humidity": body.get("humidity"),
            }
        except Exception as e:
            print(f"警告: {info['label']} の取得に失敗しました: {e}", file=sys.stderr)
            result[key] = {"label": info["label"], "temperature": None, "humidity": None}
        time.sleep(1.2)  # レート制限対策

    return result


# ---------- メイン ----------

def main():
    nature_token = get_env("NATURE_REMO_TOKEN")
    switchbot_token = get_env("SWITCHBOT_TOKEN")
    switchbot_secret = get_env("SWITCHBOT_SECRET")

    appliances = fetch_nature_appliances(nature_token)
    
    print("===== Nature API raw data =====")
    print(json.dumps(appliances, ensure_ascii=False, indent=2))
    
    nature_status = parse_nature_status(appliances)
    switchbot_status = parse_switchbot_status(switchbot_token, switchbot_secret)

    status = {
        "updated_at": datetime.now(JST).isoformat(),
        "battery": nature_status["battery"],
        "solar": nature_status["solar"],
        "grid": nature_status["grid"],
        "climate": switchbot_status,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(f"保存しました: {OUTPUT_FILE}")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

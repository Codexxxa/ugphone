import requests
import json
import base64
import hashlib
import re
import secrets
import string
import time
import uuid
from urllib.parse import urljoin

from cryptography.hazmat.primitives import padding as symmetric_padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_WEB_FINGERPRINT = base64.b64encode(uuid.uuid4().hex.encode()).decode()
_FALLBACK_UPDATE_DATE = "1784184578432"
_UPDATE_DATE_CACHE = None


def _build_secret_params(
    aes_key,
    public_key,
    access_token,
    login_id,
    timestamp=None,
    nonce=None,
):
    """Build the RSA/MD5 request metadata used by the current web client."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    alphabet = string.ascii_letters + string.digits
    nonce = nonce or "".join(secrets.choice(alphabet) for _ in range(13))
    pem = public_key.encode()
    if b"BEGIN PUBLIC KEY" not in pem:
        pem = (
            b"-----BEGIN PUBLIC KEY-----\n"
            + pem
            + b"\n-----END PUBLIC KEY-----\n"
        )
    key = serialization.load_pem_public_key(pem)
    encrypted_key = key.encrypt(aes_key.encode(), padding.PKCS1v15())
    signature_source = f"{timestamp}{nonce}{login_id}{access_token}".encode()
    return {
        "secret_pkey": base64.b64encode(encrypted_key).decode(),
        "timestamp": timestamp,
        "nonce": nonce,
        "sign": hashlib.md5(signature_source).hexdigest(),
    }


def _decrypt_secret_response(payload, aes_key):
    """Decrypt AES-CBC (2001) and AES-GCM (2002) API response payloads."""
    code = payload.get("code")
    if code not in (2001, 2002):
        return payload

    packed = base64.b64decode(payload["data"])
    key = hashlib.sha256(aes_key.encode()).digest()
    if code == 2001:
        iv, ciphertext = packed[:16], packed[16:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = symmetric_padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
    else:
        iv, tag, ciphertext = packed[:12], packed[12:28], packed[28:]
        plaintext = AESGCM(key).decrypt(iv, ciphertext + tag, None)

    result = dict(payload)
    result["code"] = 200
    result["data"] = json.loads(plaintext.decode())
    return result


def _secure_post_json(
    url,
    data,
    headers,
    public_key,
    access_token,
    login_id,
    timeout=30,
):
    """POST a signed request and decrypt encrypted API response data."""
    alphabet = string.ascii_letters + string.digits
    aes_key = "".join(secrets.choice(alphabet) for _ in range(32))
    secret_params = _build_secret_params(
        aes_key=aes_key,
        public_key=public_key,
        access_token=access_token,
        login_id=login_id,
    )
    payload = dict(data)
    payload.update(secret_params)
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response_payload = _decrypt_secret_response(response.json(), aes_key)
    return response.status_code, response_payload


def _get_update_date(force_refresh=False):
    """Discover and cache the build identifier required by the UGPhone API."""
    global _UPDATE_DATE_CACHE
    if _UPDATE_DATE_CACHE and not force_refresh:
        return _UPDATE_DATE_CACHE

    portal_url = "https://www.ugphone.com/toc-portal/"
    try:
        portal = requests.get(portal_url, timeout=15)
        portal.raise_for_status()
        script_match = re.search(
            r'<script[^>]+src=["\']([^"\']*index\.[^"\']+\.js)["\']',
            portal.text,
            re.IGNORECASE,
        )
        if not script_match:
            raise ValueError("UGPhone frontend script was not found")

        script = requests.get(urljoin(portal_url, script_match.group(1)), timeout=30)
        script.raise_for_status()
        date_match = re.search(r'["\']update-date["\']\]\s*=\s*(\d+)', script.text)
        if not date_match:
            raise ValueError("UGPhone update-date was not found")
        _UPDATE_DATE_CACHE = date_match.group(1)
    except (requests.RequestException, ValueError):
        _UPDATE_DATE_CACHE = _UPDATE_DATE_CACHE or _FALLBACK_UPDATE_DATE

    return _UPDATE_DATE_CACHE

def attempt_purchase(access_token, login_id, public_key):
    """
    Attempts to purchase the UVIP package on UgPhone.

    Args:
        access_token (str): The UGPHONE-Token.
        login_id (str): The UGPHONE-ID.

    Returns:
        dict: A dictionary containing 'success' (bool) and 'message' (str).
    """

    headers = _get_headers(access_token, login_id)

    try:
        # 1. Claim gems/package (Preserved from original script)
        # It seems this endpoint is used to get some daily resource or check status
        _secure_post_json(
            'https://www.ugphone.com/api/apiv1/fee/newPackage',
            {},
            headers,
            public_key,
            access_token,
            login_id,
            timeout=30,
        )
        # We don't strictly check success here as the original script just prints "Get gems successful"

        # 2. Get Config List to find UVIP config_id
        cf_response = requests.get('https://www.ugphone.com/api/apiv1/info/configList2', headers=headers, timeout=30)
        if cf_response.status_code != 200:
            return {"success": False, "message": f"Failed to get config list. Status: {cf_response.status_code}"}

        cf_data = cf_response.json()
        uvip_config_id = None

        if "data" in cf_data and "list" in cf_data["data"]:
            for item in cf_data["data"]["list"]:
                if item["config_name"] == "UVIP":
                    if "android_version" in item and len(item["android_version"]) > 0:
                        uvip_config_id = item["android_version"][0]["config_id"]
                    break

        if not uvip_config_id:
            return {"success": False, "message": "Could not find UVIP config ID."}

        # 3. Get Network ID
        json_data_meal = {
            'config_id': uvip_config_id,
        }
        network_status, network_dat = _secure_post_json(
            'https://www.ugphone.com/api/apiv1/info/mealList',
            json_data_meal,
            headers,
            public_key,
            access_token,
            login_id,
            timeout=30,
        )
        if network_status != 200:
             return {"success": False, "message": f"Failed to get meal list. Status: {network_status}"}
        if network_dat.get("code") != 200:
             return {"success": False, "message": f"Failed to get meal list. Msg: {network_dat.get('msg', 'Unknown error')}"}
        network_id = None

        try:
            network_id = network_dat["data"]["list"]["subscription"][0]["network_id"]
        except (KeyError, TypeError, IndexError):
            return {"success": False, "message": "Could not extract network ID from meal list."}

        # 4. Query Resource Price (Get Amount ID)
        json_data_price = {
            'order_type': 'newpay',
            'period_time': '4',
            'unit': 'hour',
            'resource_type': 'cloudphone',
            'resource_param': {
                'pay_mode': 'subscription',
                'config_id': uvip_config_id,
                'network_id': network_id,
                'count': 1,
                'use_points': 3, # Preserved from original
                'points': 250,   # Preserved from original
            },
        }

        price_status, am_json = _secure_post_json(
            'https://www.ugphone.com/api/apiv1/fee/queryResourcePrice',
            json_data_price,
            headers,
            public_key,
            access_token,
            login_id,
            timeout=30,
        )

        if price_status != 200:
             return {"success": False, "message": f"Failed to query price. Status: {price_status}"}
        amount_id = None

        if "data" in am_json and am_json["data"] is not None and "amount_id" in am_json["data"]:
            amount_id = am_json["data"]["amount_id"]
        else:
            msg = am_json.get('msg', 'Unknown error')
            return {"success": False, "message": f"Failed to get Amount ID. Msg: {msg}"}

        # 5. Execute Payment
        json_data_pay = {
            'amount_id': amount_id,
            'pay_channel': 'free',
        }

        order_response = requests.post('https://www.ugphone.com/api/apiv1/fee/payment', headers=headers, json=json_data_pay, timeout=30)
        if order_response.status_code != 200:
             return {"success": False, "message": f"Payment request failed. Status: {order_response.status_code}"}

        order_mes = order_response.json()

        if "data" in order_mes and order_mes["data"] is not None and "order_id" in order_mes["data"]:
            order_id = order_mes["data"]["order_id"]
            return {"success": True, "message": f"Ordered successful, Order ID: {order_id}"}
        else:
            msg = order_mes.get('msg', 'Unknown error')
            return {"success": False, "message": f"Order Failed. Msg: {msg}"}

    except requests.Timeout:
        return {"success": False, "message": "Request timed out."}
    except Exception as e:
        return {"success": False, "message": f"Exception occurred: {str(e)}"}

def _validate_web_credentials(access_token, login_id):
    headers = _get_headers(access_token, login_id)
    try:
        response = requests.get('https://www.ugphone.com/api/apiv1/info/configList2', headers=headers, timeout=10)
        if response.status_code == 200:
            json_data = response.json()
            if json_data.get("code") == 200:
                return True, "Credentials valid."
            else:
                return False, f"API Error: {json_data.get('msg', 'Unknown error')}"
        else:
            return False, f"HTTP Error: {response.status_code}"
    except requests.Timeout:
        return False, "Validation request timed out."
    except Exception as e:
        return False, f"Validation error: {str(e)}"


def prepare_credentials(access_token, login_id):
    """Validate web credentials or exchange Android/MQTT credentials for them."""
    is_valid, direct_message = _validate_web_credentials(access_token, login_id)
    origin_terminal = "web" if is_valid else "android"

    exchange_headers = _get_headers(access_token, login_id)
    exchange_headers.update({
        "content-type": "application/x-www-form-urlencoded",
        "terminal": "web",
        "ori-terminal": origin_terminal,
    })
    try:
        response = requests.post(
            "https://www.ugphone.com/api/apiv1/login/replaceTerminalToken",
            headers=exchange_headers,
            data={},
            timeout=15,
        )
        if response.status_code != 200:
            return {
                "success": False,
                "message": f"Token exchange HTTP error: {response.status_code}",
            }

        payload = response.json()
        if payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
            return {
                "success": False,
                "message": f"Token exchange failed: {payload.get('msg', direct_message)}",
            }

        web_token = payload["data"].get("access_token")
        web_login_id = payload["data"].get("login_id")
        public_key = payload["data"].get("public_key")
        if not web_token or not web_login_id or not public_key:
            return {
                "success": False,
                "message": "Token exchange returned incomplete credentials.",
            }

        is_valid, message = _validate_web_credentials(web_token, web_login_id)
        if not is_valid:
            return {"success": False, "message": message}
        return {
            "success": True,
            "message": message,
            "access_token": web_token,
            "login_id": web_login_id,
            "public_key": public_key,
        }
    except requests.Timeout:
        return {"success": False, "message": "Token exchange request timed out."}
    except (requests.RequestException, ValueError) as e:
        return {"success": False, "message": f"Token exchange error: {str(e)}"}


def validate_credentials(access_token, login_id):
    """Backward-compatible direct validation helper."""
    return _validate_web_credentials(access_token, login_id)

def _get_headers(access_token, login_id):
    return {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9',
        'access-token': access_token,
        'content-type': 'application/json;charset=UTF-8',
        'lang': 'en',
        'login-id': login_id,
        'origin': 'https://www.ugphone.com',
        'priority': 'u=1, i',
        'referer': 'https://www.ugphone.com/toc-portal/',
        'sec-ch-ua': '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'terminal': 'web',
        'update-date': _get_update_date(),
        'web-fingerprint': _WEB_FINGERPRINT,
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
    }

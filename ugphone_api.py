import requests
import json

def attempt_purchase(access_token, login_id):
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
        response = requests.post('https://www.ugphone.com/api/apiv1/fee/newPackage', headers=headers, json={}, timeout=30)
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
        network_res = requests.post('https://www.ugphone.com/api/apiv1/info/mealList', headers=headers, json=json_data_meal, timeout=30)
        if network_res.status_code != 200:
             return {"success": False, "message": f"Failed to get meal list. Status: {network_res.status_code}"}

        network_dat = network_res.json()
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

        getammount = requests.post(
            'https://www.ugphone.com/api/apiv1/fee/queryResourcePrice',
            headers=headers,
            json=json_data_price,
            timeout=30
        )

        if getammount.status_code != 200:
             return {"success": False, "message": f"Failed to query price. Status: {getammount.status_code}"}

        am_json = getammount.json()
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

def validate_credentials(access_token, login_id):
    """
    Validates the credentials by making a lightweight API call.

    Returns:
        tuple: (is_valid: bool, message: str)
    """
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

def _get_headers(access_token, login_id):
    return {
        'accept': 'application/json, text/plain, /',
        'accept-language': 'en-US,en;q=0.9',
        'access-token': access_token,
        'content-type': 'application/json;charset=UTF-8',
        'lang': 'en',
        'login-id': login_id,
        'origin': 'https://www.ugphone.com/',
        'priority': 'u=1, i',
        'referer': 'https://www.ugphone.com/toc-portal/',
        'sec-ch-ua': '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'terminal': 'web',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
    }

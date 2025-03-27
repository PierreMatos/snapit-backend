import json
import http.client
import base64
import boto3
import time
from urllib.parse import urlparse

LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"
LIGHTX_UPLOAD_URL = "/external/api/v2/uploadImageUrl"
LIGHTX_EXPAND_URL = "/external/api/v1/expand-photo"
LIGHTX_STATUS_URL = "/external/api/v1/order-status"
LIGHTX_HOST = "api.lightxeditor.com"


def lambda_handler(event, context):
    try:
        # 1. Get image URL from event (from check-order-status result)
        body = json.loads(event.get("body", "{}"))
        #image_url = body.get("imageUrl")
        image_url = "https://d3aa3s3yhl0emm.cloudfront.net/output/lx/avatarify/583a8bf73bb943ab84b1fbad5b2496ba_1024x1024.jpg"

        if not image_url:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing imageUrl parameter"})}

        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": LIGHTX_API_KEY
        }

        # 6. Call expand-photo endpoint
        expand_payload = json.dumps({
            "imageUrl": image_url,
            "leftPadding": -12,
            "rightPadding": -12,
            "topPadding": 238,   # expand vertically to get portrait 10x15cm
            "bottomPadding": 238
        })

        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        conn.request("POST", LIGHTX_EXPAND_URL, expand_payload, headers)
        expand_res = conn.getresponse()
        expand_data = json.loads(expand_res.read().decode())

        order_id = expand_data["body"]["orderId"]

        # 7. Poll for result (max 5 tries)
        for attempt in range(5):
            time.sleep(3)
            status_payload = json.dumps({"orderId": order_id})
            conn.request("POST", LIGHTX_STATUS_URL, status_payload, headers)
            res = conn.getresponse()
            status_data = json.loads(res.read().decode())

            if status_data["body"].get("status") == "active":
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "orderId": order_id,
                        "output": status_data["body"]["output"]
                    })
                }

        return {
            "statusCode": 408,
            "body": json.dumps({"error": "Timeout waiting for formatted image"})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

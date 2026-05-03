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
        image_url = body.get("imageUrl")
        expand_profile = str(body.get("expandProfile") or "default").strip().lower()
        left_padding = body.get("leftPadding")
        right_padding = body.get("rightPadding")
        top_padding = body.get("topPadding")
        bottom_padding = body.get("bottomPadding")
        #image_url = "https://d3aa3s3yhl0emm.cloudfront.net/output/lx/avatarify/583a8bf73bb943ab84b1fbad5b2496ba_1024x1024.jpg"

        if not image_url:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing imageUrl parameter"})}

        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": LIGHTX_API_KEY
        }

        if expand_profile == "big":
            default_paddings = {
                "leftPadding": 0,
                "rightPadding": 0,
                "topPadding": 128,
                "bottomPadding": 128,
            }
        else:
            default_paddings = {
                "leftPadding": -12,
                "rightPadding": -12,
                "topPadding": 238,
                "bottomPadding": 238,
            }

        # Allow explicit padding overrides when provided.
        resolved_paddings = {
            "leftPadding": left_padding if left_padding is not None else default_paddings["leftPadding"],
            "rightPadding": right_padding if right_padding is not None else default_paddings["rightPadding"],
            "topPadding": top_padding if top_padding is not None else default_paddings["topPadding"],
            "bottomPadding": bottom_padding if bottom_padding is not None else default_paddings["bottomPadding"],
        }

        # 6. Call expand-photo endpoint
        expand_payload = json.dumps({
            "imageUrl": image_url,
            "leftPadding": resolved_paddings["leftPadding"],
            "rightPadding": resolved_paddings["rightPadding"],
            "topPadding": resolved_paddings["topPadding"],
            "bottomPadding": resolved_paddings["bottomPadding"]
        })

        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        conn.request("POST", LIGHTX_EXPAND_URL, expand_payload, headers)
        expand_res = conn.getresponse()
        expand_data = json.loads(expand_res.read().decode())

        order_id = expand_data["body"]["orderId"]

        # 7. Poll for result (max 5 tries)
        for attempt in range(5):
            time.sleep(15)
            status_payload = json.dumps({"orderId": order_id})
            conn.request("POST", LIGHTX_STATUS_URL, status_payload, headers)
            res = conn.getresponse()
            status_data = json.loads(res.read().decode())

            # ✅ Check if output exists and is not null/empty
            output_url = status_data.get("body", {}).get("output")
            if output_url:
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "orderId": order_id,
                        "image_url": output_url
                    })
                }

        # If all attempts fail, return an error
        return {
            "statusCode": 408,
            "body": json.dumps({
                "error": "Timed out waiting for image to be ready",
                "orderId": order_id
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

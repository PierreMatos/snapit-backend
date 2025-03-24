import json
import http.client
import time
import boto3

# LightX API Configuration
LIGHTX_STATUS_URL = "/external/api/v1/order-status"
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"

def lambda_handler(event, context):
    try:
        # Parse body and extract single orderId
        body = json.loads(event.get("body", "{}"))
        #order_id = body.get("orderId")
        order_id = "b8c76281183c4b45988fe6210c353e54"

        if not order_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing orderId parameter"})
            }

        conn = http.client.HTTPSConnection("api.lightxeditor.com")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": LIGHTX_API_KEY
        }

        max_retries = 5
        image_url = None

        for attempt in range(max_retries):
            payload = json.dumps({"orderId": order_id})
            conn.request("POST", LIGHTX_STATUS_URL, body=payload, headers=headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))

            if "body" in data and "output" in data["body"] and data["body"]["output"]:
                image_url = data["body"]["output"]
                break

            time.sleep(3)

        if image_url:
            return {
                "statusCode": 200,
                "body": json.dumps({"output": image_url})
            }
        else:
            return {
                "statusCode": 408,
                "body": json.dumps({"error": "Timed out waiting for image to be ready"})
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

import json
import http.client
import time
import boto3
from urllib.parse import urlparse

# LightX API Configuration
LIGHTX_STATUS_URL = "/external/api/v1/order-status"
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"
#FORMAT_IMAGE_LAMBDA_URL = "https://4iwjgqgviulyd5mlh2zxwpgaqq0twkcg.lambda-url.eu-central-1.on.aws/"
FORMAT_IMAGE_LAMBDA_URL = "https://jxyuwcvju3du6ala53rb77vhr40hpvrs.lambda-url.eu-central-1.on.aws/"
overlay_url = "https://snapitbucket.s3.eu-central-1.amazonaws.com/assets/moldura+com+transparencia.png"


def lambda_handler(event, context):
    try:
        # Parse body and extract single orderId
        body = json.loads(event.get("body", "{}"))
        order_id = body.get("orderId")
        #order_id = "b8c76281183c4b45988fe6210c353e54"

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

        max_retries = 10
        image_url = None

        for attempt in range(max_retries):
            payload = json.dumps({"orderId": order_id})
            conn.request("POST", LIGHTX_STATUS_URL, body=payload, headers=headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))

            if "body" in data and "output" in data["body"] and data["body"]["output"]:
                image_url = data["body"]["output"]
                break

            time.sleep(5)

        if not image_url:
            return {
                "statusCode": 408,
                "body": json.dumps({"orderId": order_id, "error": "Timed out waiting for image to be ready"})
            }

        # Step 2: Call format-image Lambda to resize for print
        parsed = urlparse(FORMAT_IMAGE_LAMBDA_URL)
        #format_payload = json.dumps({"imageUrl": image_url, "orderId": order_id})
        format_payload = json.dumps({
            "imageUrl": image_url,
            "orderId": order_id,
            "overlayUrl": overlay_url
        })

        conn = http.client.HTTPSConnection(parsed.hostname)
        conn.request("POST", parsed.path, body=format_payload, headers={"Content-Type": "application/json"})
        format_res = conn.getresponse()
        format_data = json.loads(format_res.read().decode("utf-8"))

        formatted_image_url = format_data.get("image_url")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "orderId": order_id,
                "image_url": formatted_image_url
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

    

    def format_image_for_print(original_url):
        try:
            parsed = urlparse(FORMAT_IMAGE_LAMBDA_URL)

            payload = json.dumps({
                "imageUrl": original_url
            })

            conn = http.client.HTTPSConnection(parsed.hostname)
            conn.request("POST", parsed.path, body=payload, headers={"Content-Type": "application/json"})

            res = conn.getresponse()
            body = res.read().decode()
            format_data = json.loads(body)

            return format_data.get("formattedImageUrl")  # <- o campo retornado pela lambda
        except Exception as e:
            print("[Format Error]", str(e))
            return original_url  # fallback: retorna a original se falhar

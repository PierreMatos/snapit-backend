import json
import os
import http.client
import boto3
from boto3.dynamodb.conditions import Key
from urllib.parse import urlencode, urlparse
import time

# Constants
LIGHTX_AVATAR_URL = "/external/api/v1/avatar"
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"
LIGHTX_HOST = "api.lightxeditor.com"
check_url = "https://jjqikmmu3soj2imtggib56d2ie0zfglz.lambda-url.eu-central-1.on.aws/"

# Initialize AWS clients
lambda_client = boto3.client("lambda")
dynamodb = boto3.resource('dynamodb', region_name='eu-central-1')
filter_table = dynamodb.Table('Filters')

def lambda_handler(event, context):
    try:
        # Step 1: Extract parameters
        body = json.loads(event.get("body", "{}"))

        image_url = body.get("imageUrl")
        gender = body.get("gender")
        city_id = body.get("city_id")
        filter_id = body.get("filterId")
 #       image_url = "https://snapit2025.s3.us-east-1.amazonaws.com/user-uploads/17423971108665155319681902336942.jpg"
#        filter_id = "braga_male_religioso"

        # Step 2: Fetch filter data from DynamoDB
        filter_response = filter_table.get_item(Key={"id": filter_id})
        filter_item = filter_response.get("Item")

        if not filter_item:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"Filter with ID '{filter_id}' not found."})
            }

        style_image_url = filter_item.get("image_style")
        text_prompt = filter_item.get("prompt")

        if not text_prompt:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Filter data is incomplete."})
            }

        # Step 3: Call LightX avatar API
        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": LIGHTX_API_KEY
        }

        payload = json.dumps({
            "imageUrl": image_url,
            "styleImageUrl": style_image_url,
            "textPrompt": text_prompt
        })

        conn.request("POST", LIGHTX_AVATAR_URL, payload, headers)
        res = conn.getresponse()
        response_data = json.loads(res.read().decode("utf-8"))
        if "body" in response_data and "orderId" in response_data["body"]:
            order_id = response_data["body"]["orderId"]

            try:
                # Step 4: Check order status (get final image)
                parsed = urlparse(check_url)
                check_payload = json.dumps({ "orderId": order_id })

                conn = http.client.HTTPSConnection(parsed.hostname)
                conn.request("POST", parsed.path, body=check_payload, headers={"Content-Type": "application/json"})

                res = conn.getresponse()
                body = res.read().decode()
                check_data = json.loads(body)

                return {
                    "statusCode": 200,
                    "body":  json.dumps({
                        "orderId": order_id,
                        "output": check_data
                    })
                }

            except Exception as e:
                print(f"[CheckOrderStatus Error] {str(e)}")
                return {
                    "statusCode": 500,
                    "body": json.dumps({
                        "orderId": order_id,
                        "output": None,
                        "error": str(e)
                    })
                }

        else:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "No orderId returned from LightX"})
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

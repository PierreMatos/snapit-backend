import json
import http.client
import time
import os
import boto3

# LightX API Configuration
LIGHTX_STATUS_URL = "/external/api/v1/order-status"
LIGHTX_API_KEY = "009243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"

# DynamoDB Configuration
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("SnapItOrders")  # Change to your table name

def lambda_handler(event, context):
    try:
        # Extract orderIds from POST request body
        body = json.loads(event["body"])
        order_ids = body.get("orderIds", [])
        #order_ids = ["ba7b041b24514f42b89aa8c89cdc6357","cd0286bd7ea24ce4a14a227eb081c037"]

        if not order_ids:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing orderIds parameter", "images": []})
            }

        conn = http.client.HTTPSConnection("api.lightxeditor.com")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": LIGHTX_API_KEY
        }

        images = []

        for order_id in order_ids:
            attempt = 0
            max_retries = 5  # Retry up to 5 times if output is null
            image_url = None  # Store the output URL if found

            while attempt < max_retries:
                payload = json.dumps({"orderId": order_id})
                conn.request("POST", LIGHTX_STATUS_URL, payload, headers)
                res = conn.getresponse()
                data = json.loads(res.read().decode("utf-8"))

                if "body" in data and "output" in data["body"] and data["body"]["output"]:
                    image_url = data["body"]["output"]
                    break  # Exit retry loop if image URL is found

                attempt += 1
                time.sleep(3)  # Wait 3 seconds before retrying

            if image_url:
                images.append(image_url)
                # Save to DynamoDB
                table.put_item(Item={
                    "orderid": image_url,
                })

        return {
            "statusCode": 200,
            "body": json.dumps({"images": images})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


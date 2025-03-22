import boto3
import json
import http.client
import os

# Constants
LIGHTX_API_KEY = "009243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"
LIGHTX_GENERATE_URL = "/external/api/v1/avatar"
LIGHTX_HOST = "api.lightxeditor.com"

dynamodb = boto3.resource('dynamodb')
filter_table = dynamodb.Table('Filter')

def lambda_handler(event, context):
    city_id = int(event["queryStringParameters"]["city_id"])
    image_url = event["queryStringParameters"]["imageUrl"]
    gender = event["queryStringParameters"]["gender"]

    # Fetch filters from DynamoDB
    response = filter_table.scan(
        FilterExpression="city_id = :cid AND gender = :gender",
        ExpressionAttributeValues={
            ":cid": city_id,
            ":gender": gender
        }
    )
    filters = response.get("Items", [])

    conn = http.client.HTTPSConnection(LIGHTX_HOST)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": LIGHTX_API_KEY
    }

    order_ids = []

    for f in filters:
        payload = json.dumps({
            "imageUrl": image_url,
            "styleImageUrl": f["image_style"],
            "textPrompt": f["prompt"]
        })

        conn.request("POST", LIGHTX_GENERATE_URL, payload, headers)
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8"))

        if "body" in data and "orderId" in data["body"]:
            order_ids.append(data["body"]["orderId"])

    return {
        "statusCode": 200,
        "body": json.dumps({"orderIds": order_ids})
    }

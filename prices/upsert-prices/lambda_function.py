"""Lambda function: Upsert Prices - PUT /api/prices/{cityId}"""
import json
import os
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

PRICES_TABLE_NAME = os.environ.get("PRICES_TABLE_NAME", "Prices")
prices_table = dynamodb.Table(PRICES_TABLE_NAME)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def get_cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def handle_options():
    return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}


def extract_city_id(event):
    path_params = event.get("pathParameters") or {}
    if path_params.get("cityId"):
        return str(path_params["cityId"]).strip()

    query = event.get("queryStringParameters") or {}
    if query.get("cityId"):
        return str(query["cityId"]).strip()

    raw_path = (event.get("rawPath") or event.get("path") or "").strip("/")
    parts = raw_path.split("/")
    if len(parts) >= 3 and parts[-2] == "prices":
        return parts[-1].strip()
    return ""


def parse_price(value, key):
    if value is None:
        raise ValueError(f"Missing {key}")
    number = float(value)
    if number < 0:
        raise ValueError(f"{key} must be >= 0")
    return round(number, 2)


def lambda_handler(event, context):
    try:
        method = (
            (event.get("requestContext") or {})
            .get("http", {})
            .get("method", "")
            .upper()
        )
        if method == "OPTIONS":
            return handle_options()
        if method != "PUT":
            return get_cors_response(405, {"error": "Method not allowed"})

        city_id = extract_city_id(event)
        if not city_id:
            return get_cors_response(400, {"error": "Missing cityId"})

        body = {}
        if event.get("body"):
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

        price1 = parse_price(body.get("price1"), "price1")
        price2 = parse_price(body.get("price2"), "price2")
        price3 = parse_price(body.get("price3"), "price3")
        price4 = parse_price(body.get("price4"), "price4")

        currency = str(body.get("currency") or "EUR").upper()
        updated_at = datetime.now(timezone.utc).isoformat()

        item = {
            "cityId": city_id,
            "price1": price1,
            "price2": price2,
            "price3": price3,
            "price4": price4,
            "currency": currency,
            "updatedAt": updated_at,
        }
        prices_table.put_item(Item=item)

        return get_cors_response(
            200,
            {
                "success": True,
                "message": f"Prices updated for cityId={city_id}",
                "prices": item,
            },
        )
    except ValueError as exc:
        return get_cors_response(400, {"error": str(exc)})
    except Exception as exc:
        print(f"Error upserting prices: {str(exc)}")
        return get_cors_response(500, {"error": f"Failed to update prices: {str(exc)}"})

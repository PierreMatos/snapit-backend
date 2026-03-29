"""Lambda function: Get Prices - GET /api/prices/{cityId}"""
import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

PRICES_TABLE_NAME = os.environ.get("PRICES_TABLE_NAME", "Prices")
prices_table = dynamodb.Table(PRICES_TABLE_NAME)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

DEFAULT_PRICE_CONFIG = {
    "price1": 10,
    "price2": 20,
    "price3": 25,
    "price4": 30,
    "currency": "EUR",
}


def get_cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def handle_options():
    return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}


def convert_decimals(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: convert_decimals(v) for k, v in value.items()}
    if isinstance(value, list):
        return [convert_decimals(v) for v in value]
    return value


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
        if method != "GET":
            return get_cors_response(405, {"error": "Method not allowed"})

        city_id = extract_city_id(event)
        if not city_id:
            return get_cors_response(400, {"error": "Missing cityId"})

        item = None

        # Try PK=id first (current expected schema).
        try:
            response = prices_table.get_item(Key={"id": city_id})
            item = response.get("Item")
        except Exception as exc:
            if "ValidationException" not in str(exc):
                raise

        # Fallback for legacy schema where PK is cityId.
        if not item:
            try:
                response = prices_table.get_item(Key={"cityId": city_id})
                item = response.get("Item")
            except Exception as exc:
                if "ValidationException" not in str(exc):
                    raise

        # Final fallback for unexpected table schemas.
        if not item:
            scan_response = prices_table.scan(
                FilterExpression=Attr("id").eq(city_id) | Attr("cityId").eq(city_id),
                Limit=1
            )
            items = scan_response.get("Items", [])
            if items:
                item = items[0]

        if not item:
            default_payload = {"id": city_id, "cityId": city_id, **DEFAULT_PRICE_CONFIG}
            return get_cors_response(200, default_payload)

        item = convert_decimals(item)
        for key, default_value in DEFAULT_PRICE_CONFIG.items():
            if key not in item:
                item[key] = default_value

        return get_cors_response(200, item)
    except Exception as exc:
        print(f"Error getting prices: {str(exc)}")
        return get_cors_response(500, {"error": f"Failed to get prices: {str(exc)}"})

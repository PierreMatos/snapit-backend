import json
import os
import re
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError


dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
FILTERS_TABLE_NAME = os.environ.get("FILTERS_TABLE_NAME", "Filters")
filters_table = dynamodb.Table(FILTERS_TABLE_NAME)

DEFAULT_CITY_ID = 0
DEFAULT_TOOL = "single-avatar-generation"
DEFAULT_TOOL_URL = "https://fz7v4pd43xjhvwe3xfvqpbk3le0ozggd.lambda-url.eu-central-1.on.aws/"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def get_cors_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handle_options():
    return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}


def convert_decimals(obj):
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, list):
        return [convert_decimals(x) for x in obj]
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    return obj


def parse_body(event):
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def normalize_path(path):
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path

    # Remove known API Gateway stage prefixes from REST API v1 paths.
    parts = [p for p in path.split("/") if p]
    if parts and parts[0].lower() in {
        "prod",
        "dev",
        "test",
        "staging",
        "beta",
        "alpha",
        "v1",
        "v2",
        "production",
        "development",
    }:
        parts = parts[1:]
    return "/" + "/".join(parts)


def extract_method_and_path(event):
    request_context = event.get("requestContext") or {}
    http_ctx = request_context.get("http") or {}

    method = (http_ctx.get("method") or event.get("httpMethod") or "").upper()
    path = event.get("rawPath") or event.get("path") or ""
    if not path:
        route_key = request_context.get("routeKey") or ""
        if route_key and " " in route_key:
            _, path = route_key.split(" ", 1)

    return method, normalize_path(path)


def slugify_title(title):
    text = re.sub(r"[^\w\s-]", "", str(title or "").strip().lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text


def normalize_gender(value):
    if value is None:
        return "female"
    text = str(value).strip().lower()
    return text if text else "female"


def normalize_default(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def build_filter_payload(body, existing_id=None):
    title = str(body.get("title") or "").strip()
    if not title:
        return None, "Missing required field: title"

    filter_id = existing_id or slugify_title(title)
    if not filter_id:
        return None, "Could not generate valid id from title"

    prompt = str(body.get("textPrompt") or body.get("prompt") or "").strip()
    if not prompt:
        return None, "Missing required field: textPrompt"

    avatar_reference_url = str(
        body.get("avatarReferenceUrl") or body.get("image_style") or body.get("styleImageUrl") or ""
    ).strip()
    if not avatar_reference_url:
        return None, "Missing required field: avatarReferenceUrl"

    item = {
        "id": filter_id,
        "city_id": DEFAULT_CITY_ID,
        "default": normalize_default(body.get("default", False)),
        "gender": normalize_gender(body.get("gender")),
        "image_style": avatar_reference_url,
        "styleImageUrl": avatar_reference_url,
        "imageUrl": str(body.get("imageUrl") or body.get("cover_image") or "").strip(),
        "prompt": prompt,
        "title": title,
        "tool": DEFAULT_TOOL,
        "tool_url": DEFAULT_TOOL_URL,
    }

    # Keep existing cover image if explicitly provided.
    cover_image = str(body.get("cover_image") or "").strip()
    if cover_image:
        item["cover_image"] = cover_image
    elif item["imageUrl"]:
        item["cover_image"] = item["imageUrl"]

    return item, None


def list_filters(query_params):
    city_param = (query_params or {}).get("city_id")

    scan_kwargs = {}
    if city_param is not None:
        city_text = str(city_param).strip()
        expressions = [Attr("city_id").eq(city_text)]
        try:
            expressions.append(Attr("city_id").eq(int(city_text)))
        except Exception:
            pass

        expr = expressions[0]
        for extra in expressions[1:]:
            expr = expr | extra
        scan_kwargs["FilterExpression"] = expr

    items = []
    response = filters_table.scan(**scan_kwargs)
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = filters_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **scan_kwargs)
        items.extend(response.get("Items", []))

    converted = convert_decimals(items)
    converted.sort(key=lambda x: str(x.get("title") or x.get("id") or "").lower())
    return get_cors_response(200, {"filters": converted})


def get_filter(filter_id):
    response = filters_table.get_item(Key={"id": filter_id})
    item = response.get("Item")
    if not item:
        return get_cors_response(404, {"error": f"Filter '{filter_id}' not found"})
    return get_cors_response(200, {"filter": convert_decimals(item)})


def create_filter(body):
    item, error = build_filter_payload(body)
    if error:
        return get_cors_response(400, {"error": error})

    try:
        filters_table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        return get_cors_response(201, {"success": True, "filter": convert_decimals(item)})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return get_cors_response(409, {"error": f"Filter id '{item['id']}' already exists"})
        return get_cors_response(500, {"error": f"Failed to create filter: {str(exc)}"})


def update_filter(filter_id, body):
    existing_resp = filters_table.get_item(Key={"id": filter_id})
    existing = existing_resp.get("Item")
    if not existing:
        return get_cors_response(404, {"error": f"Filter '{filter_id}' not found"})

    payload, error = build_filter_payload(body, existing_id=filter_id)
    if error:
        return get_cors_response(400, {"error": error})

    # Preserve existing cover_image unless explicitly overwritten.
    if "cover_image" not in body and existing.get("cover_image"):
        payload["cover_image"] = existing.get("cover_image")

    filters_table.put_item(Item=payload)
    return get_cors_response(200, {"success": True, "filter": convert_decimals(payload)})


def set_cover_image(filter_id, body):
    cover_image = str(body.get("cover_image") or body.get("coverImage") or body.get("imageUrl") or "").strip()
    if not cover_image:
        return get_cors_response(400, {"error": "Missing required field: cover_image"})

    try:
        response = filters_table.update_item(
            Key={"id": filter_id},
            UpdateExpression="SET cover_image = :cover, imageUrl = :cover",
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeValues={":cover": cover_image},
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return get_cors_response(404, {"error": f"Filter '{filter_id}' not found"})
        return get_cors_response(500, {"error": f"Failed to set cover image: {str(exc)}"})

    updated = convert_decimals(response.get("Attributes") or {})
    return get_cors_response(200, {"success": True, "filter": updated})


def lambda_handler(event, context):
    try:
        method, path = extract_method_and_path(event)
        if method == "OPTIONS":
            return handle_options()

        query_params = event.get("queryStringParameters") or {}
        body = parse_body(event)

        if method == "GET" and path == "/api/filters":
            return list_filters(query_params)

        if method == "POST" and path == "/api/filters":
            return create_filter(body)

        if path.startswith("/api/filters/"):
            suffix = path[len("/api/filters/") :]
            parts = [p for p in suffix.split("/") if p]
            if not parts:
                return get_cors_response(404, {"error": "Route not found"})

            filter_id = parts[0]

            if method == "GET" and len(parts) == 1:
                return get_filter(filter_id)

            if method == "PUT" and len(parts) == 1:
                return update_filter(filter_id, body)

            if method == "PUT" and len(parts) == 2 and parts[1] == "cover-image":
                return set_cover_image(filter_id, body)

        return get_cors_response(404, {"error": f"Route not found: {method} {path}"})
    except Exception as exc:
        print(f"Unhandled error in filters lambda: {exc}")
        return get_cors_response(500, {"error": f"Internal server error: {str(exc)}"})

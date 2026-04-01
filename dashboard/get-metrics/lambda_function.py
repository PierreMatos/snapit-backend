"""Lambda function: Dashboard metrics - GET /api/dashboard/metrics"""
import base64
import json
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Attr


dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

REQUESTS_TABLE_NAME = os.environ.get("REQUESTS_TABLE_NAME", "Requests")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "Orders")

LISBON_TZ = ZoneInfo("Europe/Lisbon")
BASELINE_DATE_STR = "2026-03-30"

requests_table = dynamodb.Table(REQUESTS_TABLE_NAME)
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
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


def decode_jwt_payload(token):
    try:
        parts = str(token).split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padded = payload + "=" * ((4 - len(payload) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        parsed = json.loads(decoded)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def extract_claims(event):
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    jwt_claims = (authorizer.get("jwt") or {}).get("claims")
    if isinstance(jwt_claims, dict):
        return jwt_claims
    claims = authorizer.get("claims")
    if isinstance(claims, dict):
        return claims

    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization") or ""
    if isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
        return decode_jwt_payload(auth_header.split(" ", 1)[1])
    return {}


def normalize_groups(raw_groups):
    if isinstance(raw_groups, list):
        return [str(g).strip().lower() for g in raw_groups if str(g).strip()]
    if isinstance(raw_groups, str):
        return [g.strip().lower() for g in raw_groups.split(",") if g.strip()]
    return []


def parse_iso_or_none(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LISBON_TZ)
    except Exception:
        return None


def parse_order_lisbon_dt(order):
    capture_ts = parse_iso_or_none(order.get("captureTimestamp"))
    if capture_ts:
        return capture_ts

    paid_ts = parse_iso_or_none(order.get("paidTimestamp"))
    if paid_ts:
        return paid_ts

    date_str = order.get("date")
    if date_str:
        try:
            naive = datetime.strptime(str(date_str), "%Y-%m-%d")
            return naive.replace(tzinfo=LISBON_TZ)
        except Exception:
            return None
    return None


def to_float(value):
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return 0.0


def init_metrics():
    return {"photosTaken": 0, "orders": 0, "sales": 0, "revenue": 0.0}


def add_request_metric(metrics):
    metrics["photosTaken"] += 1


def add_order_metric(metrics, order_status, order_price):
    metrics["orders"] += 1
    if str(order_status).lower() == "paid":
        metrics["sales"] += 1
        metrics["revenue"] += to_float(order_price)


def list_all_items(table):
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return items


def lambda_handler(event, context):
    try:
        method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "").upper()
        if method == "OPTIONS":
            return handle_options()
        if method and method != "GET":
            return get_cors_response(405, {"error": "Method not allowed"})

        claims = extract_claims(event)
        user_sub = claims.get("sub") or claims.get("username") or claims.get("cognito:username") or "unknown"
        user_email = claims.get("email") or claims.get("cognito:username") or claims.get("username") or "unknown"
        groups = normalize_groups(claims.get("cognito:groups") or claims.get("groups"))
        is_admin = "admins" in groups

        baseline_start = datetime.strptime(BASELINE_DATE_STR, "%Y-%m-%d").replace(tzinfo=LISBON_TZ)
        now_lisbon = datetime.now(tz=LISBON_TZ)
        today_start = now_lisbon.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        all_requests = list_all_items(requests_table)
        all_orders = list_all_items(orders_table)

        overall = init_metrics()
        daily = init_metrics()
        user_overall = init_metrics()
        per_user = {}

        for req in all_requests:
            req_dt = parse_iso_or_none(req.get("creation_date"))
            if not req_dt:
                continue
            if not (baseline_start <= req_dt <= now_lisbon):
                continue

            req_sub = req.get("createdBySub") or "unknown"
            req_email = req.get("createdByEmail") or "unknown"
            user_key = f"{req_sub}|{req_email}"
            if user_key not in per_user:
                per_user[user_key] = {
                    "sub": str(req_sub),
                    "email": str(req_email),
                    "photosTaken": 0,
                    "orders": 0,
                    "sales": 0,
                    "revenue": 0.0,
                }

            add_request_metric(overall)
            per_user[user_key]["photosTaken"] += 1

            if today_start <= req_dt < today_end:
                add_request_metric(daily)

            if str(req_sub) == str(user_sub):
                add_request_metric(user_overall)

        for order in all_orders:
            order_dt = parse_order_lisbon_dt(order)
            if not order_dt:
                continue
            if not (baseline_start <= order_dt <= now_lisbon):
                continue

            status = str(order.get("status") or "").lower()
            price = order.get("price", 0)
            seller_sub = order.get("sellerSub") or "unknown"
            seller_email = order.get("sellerEmail") or "unknown"
            user_key = f"{seller_sub}|{seller_email}"
            if user_key not in per_user:
                per_user[user_key] = {
                    "sub": str(seller_sub),
                    "email": str(seller_email),
                    "photosTaken": 0,
                    "orders": 0,
                    "sales": 0,
                    "revenue": 0.0,
                }

            add_order_metric(overall, status, price)
            add_order_metric(per_user[user_key], status, price)

            if today_start <= order_dt < today_end:
                add_order_metric(daily, status, price)

            if str(seller_sub) == str(user_sub):
                add_order_metric(user_overall, status, price)

        for value in (overall, daily, user_overall):
            value["revenue"] = round(value["revenue"], 2)
        for item in per_user.values():
            item["revenue"] = round(item["revenue"], 2)

        response = {
            "timezone": "Europe/Lisbon",
            "rangeStart": BASELINE_DATE_STR,
            "rangeEnd": now_lisbon.isoformat(),
            "roleScope": "admin" if is_admin else "self",
            "overall": overall if is_admin else user_overall,
        }

        if is_admin:
            response["daily"] = daily
            response["perUser"] = list(per_user.values())
        else:
            response["currentUser"] = {
                "sub": str(user_sub),
                "email": str(user_email),
                "groups": groups,
            }

        return get_cors_response(200, response)
    except Exception as exc:
        print(f"Error building dashboard metrics: {exc}")
        return get_cors_response(500, {"error": f"Failed to build metrics: {str(exc)}"})

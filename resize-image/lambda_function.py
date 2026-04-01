import json
import http.client
import base64
import boto3
import time
import os
from urllib.parse import urlparse

DEFAULT_LIGHTX_API_KEY = os.environ.get("LIGHTX_API_KEY", "")
LIGHTX_TOKENS_TABLE = os.environ.get('LIGHTX_TOKENS_TABLE', 'LightxUserTokens')
REQUEST_TABLE_NAME = os.environ.get('REQUEST_TABLE_NAME', 'Requests')
AVATAR_TABLE_NAME = os.environ.get('AVATAR_TABLE_NAME', 'Avatars')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
LIGHTX_UPLOAD_URL = "/external/api/v2/uploadImageUrl"
LIGHTX_EXPAND_URL = "/external/api/v1/expand-photo"
LIGHTX_STATUS_URL = "/external/api/v1/order-status"
LIGHTX_HOST = "api.lightxeditor.com"

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
tokens_table = dynamodb.Table(LIGHTX_TOKENS_TABLE)
requests_table = dynamodb.Table(REQUEST_TABLE_NAME)
avatars_table = dynamodb.Table(AVATAR_TABLE_NAME)

def extract_jwt_claims(event):
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
        token = auth_header.split(" ", 1)[1].strip()
        parts = token.split(".")
        if len(parts) >= 2:
            try:
                payload = parts[1]
                padded = payload + "=" * ((4 - len(payload) % 4) % 4)
                decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
                parsed = json.loads(decoded)
                if isinstance(parsed, dict):
                    return parsed
            except Exception as decode_error:
                print(f"Failed decoding bearer token payload: {decode_error}")
    return {}

def get_request_id_by_order_id(order_id):
    if not order_id:
        return None
    try:
        response = avatars_table.get_item(Key={"id": order_id})
        item = response.get("Item") or {}
        return item.get("requestId") or item.get("request_id")
    except Exception as e:
        print(f"Unable to load avatar row for orderId={order_id}: {e}")
        return None

def get_user_sub_by_request_id(request_id):
    if not request_id:
        return None
    try:
        response = requests_table.get_item(Key={"id": request_id})
        item = response.get("Item") or {}
        return item.get("createdBySub")
    except Exception as e:
        print(f"Unable to load request row for requestId={request_id}: {e}")
        return None

def get_lightx_token_for_user_sub(user_sub):
    def _read_token_with_pk(pk_name, key_value):
        if not key_value:
            return None
        try:
            response = tokens_table.get_item(Key={pk_name: key_value})
            item = response.get("Item") or {}
            if not item:
                return None
            if item.get("active") is False:
                return None
            token = item.get("apiKey")
            if isinstance(token, str) and token.strip():
                return token.strip()
            return None
        except Exception as e:
            print(f"Failed reading token mapping for {pk_name}={key_value}: {e}")
            return None
    def _read_token_any_pk(key_value):
        # Support both token table PK styles: id and userSub.
        return _read_token_with_pk("id", key_value) or _read_token_with_pk("userSub", key_value)
    return _read_token_any_pk(user_sub) or _read_token_any_pk("default") or DEFAULT_LIGHTX_API_KEY or None

def resolve_lightx_api_key(event, request_id=None, order_id=None):
    claims = extract_jwt_claims(event or {})
    user_sub = claims.get("sub") or claims.get("username") or claims.get("cognito:username")
    resolved_request_id = request_id or get_request_id_by_order_id(order_id)
    if not user_sub:
        user_sub = get_user_sub_by_request_id(resolved_request_id)
    return get_lightx_token_for_user_sub(user_sub)


def lambda_handler(event, context):
    try:
        # 1. Get image URL from event (from check-order-status result)
        body = json.loads(event.get("body", "{}"))
        image_url = body.get("imageUrl")
        order_id = body.get("orderId")
        request_id = body.get("requestId")
        #image_url = "https://d3aa3s3yhl0emm.cloudfront.net/output/lx/avatarify/583a8bf73bb943ab84b1fbad5b2496ba_1024x1024.jpg"

        if not image_url:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing imageUrl parameter"})}
        lightx_api_key = resolve_lightx_api_key(event, request_id=request_id, order_id=order_id)
        if not lightx_api_key:
            return {"statusCode": 503, "body": json.dumps({"error": "No LightX API token configured for this user"})}

        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": lightx_api_key
        }

        # 6. Call expand-photo endpoint
        expand_payload = json.dumps({
            "imageUrl": image_url,
            "leftPadding": -12,
            "rightPadding": -12,
            "topPadding": 238,   # expand vertically to get portrait 10x15cm
            "bottomPadding": 238
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

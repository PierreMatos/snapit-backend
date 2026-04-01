# Lambda function: check-lightx-status-proxy
import json
import os
import http.client
import base64
import boto3
from urllib.parse import urlparse

# Configuration
LIGHTX_STATUS_URL = "https://api.lightxeditor.com/external/api/v1/order-status"
# Store API key in Lambda Environment Variables for security
DEFAULT_LIGHTX_API_KEY = os.environ.get("LIGHTX_API_KEY", "")
LIGHTX_TOKENS_TABLE = os.environ.get('LIGHTX_TOKENS_TABLE', 'LightxUserTokens')
REQUEST_TABLE_NAME = os.environ.get('REQUEST_TABLE_NAME', 'Requests')
AVATAR_TABLE_NAME = os.environ.get('AVATAR_TABLE_NAME', 'Avatars')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
# Allow your specific Amplify origin (or '*' for testing, but be specific for production)
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', "https://master.d1m6exe13kof96.amplifyapp.com") 

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

def resolve_lightx_api_key(event, order_id=None, request_id=None):
    claims = extract_jwt_claims(event or {})
    user_sub = claims.get("sub") or claims.get("username") or claims.get("cognito:username")
    resolved_request_id = request_id or get_request_id_by_order_id(order_id)
    if not user_sub:
        user_sub = get_user_sub_by_request_id(resolved_request_id)
    return get_lightx_token_for_user_sub(user_sub)

def lambda_handler(event, context):
    
    # Prepare CORS headers - send them with every response
    cors_headers = {
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "POST, OPTIONS", # Specify allowed methods
        "Access-Control-Allow-Headers": "Content-Type"  # Specify allowed headers
    }

    # Handle CORS Preflight OPTIONS request (API Gateway might handle this too)
    if event.get('httpMethod') == 'OPTIONS':
        print("Handling OPTIONS request for CORS preflight")
        return {
            'statusCode': 204, # No Content for OPTIONS
            'headers': cors_headers,
            'body': ''
        }

    # --- Main POST request handling ---
    conn = None # Initialize connection variable
    try:
        # Parse request body from frontend
        try:
            body = json.loads(event.get("body", "{}"))
            order_id = body.get("orderId")
            request_id = body.get("requestId")
        except json.JSONDecodeError:
             print("Error: Invalid JSON in request body")
             return {
                 "statusCode": 400,
                 "headers": {**cors_headers, "Content-Type": "application/json"},
                 "body": json.dumps({"error": "Invalid JSON format in request body"})
             }

        if not order_id:
            print("Error: Missing orderId in request body")
            return {
                "statusCode": 400,
                "headers": {**cors_headers, "Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing orderId"})
            }
        
        lightx_api_key = resolve_lightx_api_key(event, order_id=order_id, request_id=request_id)
        if not lightx_api_key:
             print("ERROR: LIGHTX_API_KEY environment variable not set!")
             return {
                 "statusCode": 500,
                 "headers": {**cors_headers, "Content-Type": "application/json"},
                 "body": json.dumps({"error": "API Key configuration error on server"})
             }

        # Prepare request to LightX API using http.client
        parsed_url = urlparse(LIGHTX_STATUS_URL)
        hostname = parsed_url.netloc
        path = parsed_url.path
        
        headers_to_lightx = {
            "Content-Type": "application/json",
            "x-api-key": lightx_api_key,
            "Accept": "application/json"
        }
        payload_to_lightx = json.dumps({"orderId": order_id})

        print(f"Calling LightX Status API: Host={hostname}, Path={path} for OrderId={order_id}")
        conn = http.client.HTTPSConnection(hostname, timeout=10) # Add timeout
        
        conn.request("POST", path, body=payload_to_lightx, headers=headers_to_lightx)
        
        res = conn.getresponse()
        res_status = res.status
        res_reason = res.reason
        res_body_bytes = res.read()
        
        print(f"LightX API Response Status: {res_status} {res_reason}")

        # Check if LightX call was successful
        if res_status < 200 or res_status >= 300:
            print(f"Error from LightX API: Status={res_status}, Body={res_body_bytes.decode('utf-8', errors='ignore')[:500]}") # Log partial error body
            # Return a 502 Bad Gateway if the downstream service fails
            return {
                 "statusCode": 502, 
                 "headers": {**cors_headers, "Content-Type": "application/json"},
                 "body": json.dumps({"error": f"Downstream service error: LightX API returned status {res_status}"})
            }
            
        # Decode and parse the successful LightX response body
        res_body_str = res_body_bytes.decode("utf-8")
        print(f"LightX API Response Body (raw): {res_body_str[:500]}...") # Log partial success body
        
        try:
            lightx_data = json.loads(res_body_str)
        except json.JSONDecodeError as json_err:
            print(f"Error decoding JSON from LightX: {json_err}")
            return {
                 "statusCode": 502, # Bad Gateway - downstream service returned invalid data
                 "headers": {**cors_headers, "Content-Type": "application/json"},
                 "body": json.dumps({"error": "Invalid JSON response from downstream service"})
            }

        # Extract the relevant 'body' part from the LightX response
        # (Adjust if the actual structure is different, e.g., status/output might be top-level)
        status_info = lightx_data.get("body", {}) 
        if not isinstance(status_info, dict):
             print(f"Warning: Expected 'body' in LightX response to be a dictionary, but got {type(status_info)}. Using empty dict.")
             status_info = {} # Default to empty dict if format is unexpected

        # Successfully got data from LightX, return it to frontend
        return {
            "statusCode": 200,
            "headers": {**cors_headers, "Content-Type": "application/json"},
            "body": json.dumps(status_info) # Return the inner 'body' content from LightX
        }

    except http.client.HTTPException as http_err:
         # Catches errors related to the HTTP connection/protocol itself
         print(f"HTTP client error calling LightX: {http_err}")
         return {
             "statusCode": 502, # Bad Gateway - couldn't communicate properly
             "headers": {**cors_headers, "Content-Type": "application/json"},
             "body": json.dumps({"error": "Failed to communicate with status service"})
         }
    except Exception as e:
        # General catch-all for unexpected errors in the handler
        print(f"Unhandled Lambda Handler error: {e}", exc_info=True) # Add exc_info for stack trace in logs
        return {
            "statusCode": 500, 
            "headers": {**cors_headers, "Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal server error"})
        }
    finally:
        # Ensure the connection is always closed
        if conn:
            conn.close()
            print("Closed http.client connection.")

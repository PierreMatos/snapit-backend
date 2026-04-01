import json
import os
import http.client
import time
import logging
import base64
import boto3
from urllib.parse import urlparse

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Configuration (Use Environment Variables) ---
# LightX API
LIGHTX_HOST = os.environ.get('LIGHTX_HOST', 'api.lightxeditor.com')
LIGHTX_STATUS_PATH = os.environ.get('LIGHTX_STATUS_PATH', '/external/api/v1/order-status')
# IMPORTANT: Store API keys securely (Secrets Manager or Lambda Environment Variables)
DEFAULT_LIGHTX_API_KEY = os.environ.get("LIGHTX_API_KEY", "")
LIGHTX_TOKENS_TABLE = os.environ.get('LIGHTX_TOKENS_TABLE', 'LightxUserTokens')
REQUEST_TABLE_NAME = os.environ.get('REQUEST_TABLE_NAME', 'Requests')
AVATAR_TABLE_NAME = os.environ.get('AVATAR_TABLE_NAME', 'Avatars')
DYNAMODB_REGION = os.environ.get('AWS_REGION', 'eu-central-1')

# Format Image Lambda
# Ensure this URL is set in your Lambda environment variables
FORMAT_IMAGE_LAMBDA_URL = "https://jxyuwcvju3du6ala53rb77vhr40hpvrs.lambda-url.eu-central-1.on.aws/"
OVERLAY_URL = os.environ.get('OVERLAY_URL', "https://snapitbucket.s3.eu-central-1.amazonaws.com/assets/moldura+com+transparencia.png") # Optional overlay

# Polling Parameters (Matching LightX Docs)
MAX_STATUS_RETRIES = 5
# Polling schedule (wait BEFORE each poll, in ms).
# No immediate check at t=0; first poll happens after the first delay.
DEFAULT_STATUS_POLL_DELAYS_MS = "10000,5000,5000,15000"
# ----------------------------------------------

dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
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
                logger.warning(f"Failed decoding bearer token payload: {decode_error}")
    return {}

def get_request_id_by_order_id(order_id):
    if not order_id:
        return None
    try:
        response = avatars_table.get_item(Key={"id": order_id})
        item = response.get("Item") or {}
        return item.get("requestId") or item.get("request_id")
    except Exception as e:
        logger.warning(f"Unable to load avatar row for orderId={order_id}: {e}")
        return None

def get_user_sub_by_request_id(request_id):
    if not request_id:
        return None
    try:
        response = requests_table.get_item(Key={"id": request_id})
        item = response.get("Item") or {}
        return item.get("createdBySub")
    except Exception as e:
        logger.warning(f"Unable to load request row for requestId={request_id}: {e}")
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
            logger.warning(f"Failed reading token mapping for {pk_name}={key_value}: {e}")
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

    token = get_lightx_token_for_user_sub(user_sub)
    if token:
        masked_sub = f"{str(user_sub)[:8]}..." if user_sub else "default"
        logger.info(f"Resolved LightX token mapping for userSub={masked_sub}")
    return token


def get_poll_delays_seconds():
    """Returns normalized polling delays, each applied before a polling attempt."""
    delays_ms_raw = os.environ.get("STATUS_POLL_DELAYS_MS")
    if not delays_ms_raw:
        delays_ms_raw = DEFAULT_STATUS_POLL_DELAYS_MS

    parsed_delays = []
    expected_attempts = max(MAX_STATUS_RETRIES, 1)

    for token in delays_ms_raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            delay_ms = int(token)
            if delay_ms < 0:
                logger.warning(f"Ignoring negative delay value: {delay_ms}ms")
                continue
            parsed_delays.append(delay_ms / 1000.0)
        except ValueError:
            logger.warning(f"Ignoring invalid delay token in STATUS_POLL_DELAYS_MS: '{token}'")

    if not parsed_delays:
        logger.warning(
            "No valid polling delays found. Falling back to DEFAULT_STATUS_POLL_DELAYS_MS."
        )
        parsed_delays = [int(token.strip()) / 1000.0 for token in DEFAULT_STATUS_POLL_DELAYS_MS.split(",")]

    # Keep at most MAX_STATUS_RETRIES delays (each delay maps to one polling attempt).
    if len(parsed_delays) > expected_attempts:
        logger.warning(
            f"Received {len(parsed_delays)} polling delays; only first {expected_attempts} will be used."
        )
        parsed_delays = parsed_delays[:expected_attempts]

    logger.info(
        f"Using poll delays (seconds): {parsed_delays} with max retries={MAX_STATUS_RETRIES}"
    )
    return parsed_delays

def call_lightx_status_api(order_id, lightx_api_key):
    """Calls the LightX order status API once."""
    conn = None
    if not lightx_api_key:
        logger.error("LightX API Key is not configured.")
        return None, "API key configuration error."

    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": lightx_api_key
        }
        payload = json.dumps({"orderId": order_id})

        logger.info(f"Checking LightX status for orderId: {order_id}")
        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        conn.request("POST", LIGHTX_STATUS_PATH, body=payload, headers=headers)
        
        res = conn.getresponse()
        response_body = res.read().decode("utf-8")
        logger.debug(f"LightX Status Response Status: {res.status}")
        logger.debug(f"LightX Status Response Body: {response_body}")

        if res.status < 200 or res.status >= 300:
             logger.error(f"LightX Status API Error: Status={res.status}, Body={response_body}")
             # Treat non-2xx as a potentially transient error during polling
             return None, f"LightX API returned status {res.status}" 

        data = json.loads(response_body)
        
        # Expecting structure like {"body": {"status": "active/failed", "output": "url_or_null"}}
        if "body" in data and isinstance(data["body"], dict):
             return data["body"], None # Return the inner body dict and no error
        else:
             logger.error(f"Unexpected LightX status response format: {data}")
             return None, "Unexpected response format from LightX status API"

    except http.client.HTTPException as e:
        logger.error(f"HTTP request to LightX status failed: {e}", exc_info=True)
        return None, f"HTTP request failed: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from LightX status: {e}", exc_info=True)
        try:
             logger.error(f"Response body was: {response_body[:1000]}") 
        except NameError:
             pass 
        return None, "Invalid JSON response from LightX status"
    except Exception as e:
        logger.error(f"Unexpected error during LightX status request: {e}", exc_info=True)
        return None, f"Unexpected error: {str(e)}"
    finally:
        if conn:
            conn.close()


def call_format_image_lambda(image_url, order_id, request_id=None):
    """Calls the format-image Lambda function."""
    conn = None
    if not FORMAT_IMAGE_LAMBDA_URL:
        logger.error("FORMAT_IMAGE_LAMBDA_URL environment variable is not set.")
        return None, "Format Image Lambda URL not configured."
        
    try:
        parsed_url = urlparse(FORMAT_IMAGE_LAMBDA_URL)
        payload_dict = {"imageUrl": image_url, "orderId": order_id}
        if request_id:
            payload_dict["requestId"] = request_id
        # Only include overlayUrl if it's defined and not empty
        if OVERLAY_URL: 
            payload_dict["overlayUrl"] = OVERLAY_URL
            
        format_payload = json.dumps(payload_dict)
        
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        logger.info(f"Calling Format Image Lambda for orderId: {order_id}")
        conn = http.client.HTTPSConnection(parsed_url.hostname)
        # Use path from parsed URL which includes any potential base path
        conn.request("POST", parsed_url.path, body=format_payload, headers=headers) 
        
        res = conn.getresponse()
        response_body = res.read().decode("utf-8")
        logger.debug(f"Format Image Lambda Response Status: {res.status}")
        logger.debug(f"Format Image Lambda Response Body: {response_body}")

        if res.status < 200 or res.status >= 300:
             logger.error(f"Format Image Lambda Error: Status={res.status}, Body={response_body}")
             return None, f"Format Image Lambda returned status {res.status}"

        format_data = json.loads(response_body)
        
        # Adjust according to the actual response structure of format-image lambda
        # Assuming it returns {"image_url": "..."} or similar in its body
        if isinstance(format_data, dict) and "body" in format_data and isinstance(format_data["body"], str):
             # Handle if format-image returns a stringified body (API Gateway proxy)
             inner_body = json.loads(format_data["body"])
             formatted_image_url = inner_body.get("image_url")
        elif isinstance(format_data, dict):
              # Handle if format-image returns direct JSON or pre-parsed body
             formatted_image_url = format_data.get("image_url") 
        else:
             formatted_image_url = None

        if not formatted_image_url:
            logger.error(f"Could not extract formatted image URL from response: {format_data}")
            return None, "Formatted image URL not found in response"
            
        logger.info(f"Successfully formatted image for orderId: {order_id}")
        return formatted_image_url, None # Return URL and no error

    except http.client.HTTPException as e:
        logger.error(f"HTTP request to Format Image Lambda failed: {e}", exc_info=True)
        return None, f"HTTP request failed: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from Format Image Lambda: {e}", exc_info=True)
        try:
             logger.error(f"Response body was: {response_body[:1000]}") 
        except NameError:
             pass 
        return None, "Invalid JSON response from Format Image Lambda"
    except Exception as e:
        logger.error(f"Unexpected error during Format Image Lambda call: {e}", exc_info=True)
        return None, f"Unexpected error: {str(e)}"
    finally:
        if conn:
            conn.close()


def lambda_handler(event, context):
    try:
        logger.debug(f"Received event: {event}")
        
        if isinstance(event.get("body"), dict):
            body = event["body"]
        else:
            body = json.loads(event.get("body", "{}"))

        order_id = body.get("orderId")
        request_id = body.get("requestId")

        if not order_id:
            logger.warning("Missing orderId parameter in request body.")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing orderId parameter"})
            }

        resolved_request_id = request_id or get_request_id_by_order_id(order_id)
        lightx_api_key = resolve_lightx_api_key(event, request_id=resolved_request_id, order_id=order_id)
        if not lightx_api_key:
            return {
                "statusCode": 503,
                "body": json.dumps({"error": "No LightX API token configured for this user"})
            }

        poll_delays_seconds = get_poll_delays_seconds()
        total_attempts = min(MAX_STATUS_RETRIES, len(poll_delays_seconds))
        max_wait_seconds = sum(poll_delays_seconds[:total_attempts])

        original_image_url = None
        final_status = "pending" # Track the final status observed

        # --- Polling Loop ---
        for attempt in range(total_attempts):
            delay_seconds = poll_delays_seconds[attempt]
            logger.debug(f"Waiting {delay_seconds}s before poll attempt {attempt + 1}...")
            time.sleep(delay_seconds)

            logger.info(f"Polling attempt {attempt + 1}/{total_attempts} for orderId {order_id}")
            status_body, error = call_lightx_status_api(order_id, lightx_api_key)

            if error:
                # Log the error but continue polling unless it's a fatal config error
                logger.warning(f"Attempt {attempt + 1} failed: {error}. Retrying...")
                # Potentially add logic here to stop retrying on specific errors (e.g., auth failure)
                
            elif status_body:
                current_status = status_body.get("status")
                logger.info(f"Attempt {attempt + 1}: LightX status is '{current_status}'")

                if current_status == "active":
                    original_image_url = status_body.get("output")
                    if original_image_url:
                         final_status = "active"
                         logger.info(f"Order {order_id} is active. Output URL received.")
                         break # Exit loop on success
                    else:
                         logger.warning(f"Order {order_id} is active but 'output' field is missing or empty.")
                         # Treat as pending and continue polling? Or fail? Let's treat as pending for now.
                         final_status = "pending_no_output" 
                         
                elif current_status == "failed":
                    final_status = "failed"
                    logger.warning(f"Order {order_id} processing failed according to LightX.")
                    break # Exit loop on failure
                
                # else status is likely "pending" or similar, continue polling

        # --- End Polling Loop ---


        # --- Process Polling Results ---
        if final_status == "active" and original_image_url:
            # Step 2: Call format-image Lambda
            formatted_image_url, format_error = call_format_image_lambda(original_image_url, order_id, resolved_request_id)

            if format_error:
                 # Failed to format, return error but include original URL maybe?
                 logger.error(f"Failed to format image for order {order_id}: {format_error}")
                 return {
                     "statusCode": 502, # Bad Gateway - downstream format lambda failed
                     "body": json.dumps({
                         "orderId": order_id,
                         "status": "formatting_failed",
                         "original_image_url": original_image_url, # Provide original if formatting failed
                         "error": f"Failed to format image: {format_error}"
                     })
                 }
            else:
                # Success!
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "orderId": order_id,
                        "status": "completed",
                        "image_url": formatted_image_url # Return the *formatted* URL
                    })
                }
                
        elif final_status == "failed":
             # LightX reported failure
             return {
                 "statusCode": 200, # Request OK, but job failed
                 "body": json.dumps({
                     "orderId": order_id,
                     "status": "failed",
                     "error": "Image generation failed at LightX."
                 })
             }
        elif final_status == "pending_no_output":
             # Active but no URL - internal error or unexpected state
             return {
                  "statusCode": 500, 
                  "body": json.dumps({
                       "orderId": order_id, 
                       "status": "error",
                       "error": "Image generation finished but no output URL was provided by LightX."
                  })
             }
        else:
             # Polling timed out (reached max retries without active/failed)
             logger.warning(f"Polling timed out for orderId {order_id} after {total_attempts} attempts.")
             return {
                 "statusCode": 408, # Request Timeout - polling timed out
                 "body": json.dumps({
                     "orderId": order_id,
                     "status": "timeout",
                     "error": (
                         f"Timed out after {total_attempts} polling attempts "
                         f"(~{max_wait_seconds:.1f}s total wait) waiting for image generation to complete."
                     )
                 })
             }

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in request body.", exc_info=True)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON format in request body"})
        }
    except Exception as e:
        logger.error(f"Unhandled exception in lambda_handler: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }
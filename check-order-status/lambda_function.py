import json
import os
import http.client
import time
import logging
from urllib.parse import urlparse

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Configuration (Use Environment Variables) ---
# LightX API
LIGHTX_HOST = os.environ.get('LIGHTX_HOST', 'api.lightxeditor.com')
LIGHTX_STATUS_PATH = os.environ.get('LIGHTX_STATUS_PATH', '/external/api/v1/order-status')
# IMPORTANT: Store API keys securely (Secrets Manager or Lambda Environment Variables)
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"

# Format Image Lambda
# Ensure this URL is set in your Lambda environment variables
FORMAT_IMAGE_LAMBDA_URL = "https://jxyuwcvju3du6ala53rb77vhr40hpvrs.lambda-url.eu-central-1.on.aws/"
OVERLAY_URL = os.environ.get('OVERLAY_URL', "https://snapitbucket.s3.eu-central-1.amazonaws.com/assets/moldura+com+transparencia.png") # Optional overlay

# Polling Parameters (Matching LightX Docs)
MAX_STATUS_RETRIES = 5
STATUS_RETRY_INTERVAL_SECONDS = 3
# ----------------------------------------------

def call_lightx_status_api(order_id):
    """Calls the LightX order status API once."""
    conn = None
    if not LIGHTX_API_KEY:
        logger.error("LightX API Key is not configured.")
        return None, "API key configuration error."

    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": LIGHTX_API_KEY
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


def call_format_image_lambda(image_url, order_id):
    """Calls the format-image Lambda function."""
    conn = None
    if not FORMAT_IMAGE_LAMBDA_URL:
        logger.error("FORMAT_IMAGE_LAMBDA_URL environment variable is not set.")
        return None, "Format Image Lambda URL not configured."
        
    try:
        parsed_url = urlparse(FORMAT_IMAGE_LAMBDA_URL)
        payload_dict = {"imageUrl": image_url, "orderId": order_id}
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

        if not order_id:
            logger.warning("Missing orderId parameter in request body.")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing orderId parameter"})
            }

        original_image_url = None
        final_status = "pending" # Track the final status observed

        # --- Polling Loop ---
        for attempt in range(MAX_STATUS_RETRIES):
            logger.info(f"Polling attempt {attempt + 1}/{MAX_STATUS_RETRIES} for orderId {order_id}")
            status_body, error = call_lightx_status_api(order_id)

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

            # Wait before the next attempt, but not after the last one
            if attempt < MAX_STATUS_RETRIES - 1:
                logger.debug(f"Waiting {STATUS_RETRY_INTERVAL_SECONDS}s before next poll...")
                time.sleep(STATUS_RETRY_INTERVAL_SECONDS)
        # --- End Polling Loop ---


        # --- Process Polling Results ---
        if final_status == "active" and original_image_url:
            # Step 2: Call format-image Lambda
            formatted_image_url, format_error = call_format_image_lambda(original_image_url, order_id)

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
             logger.warning(f"Polling timed out for orderId {order_id} after {MAX_STATUS_RETRIES} attempts.")
             return {
                 "statusCode": 408, # Request Timeout - polling timed out
                 "body": json.dumps({
                     "orderId": order_id,
                     "status": "timeout",
                     "error": f"Timed out after {MAX_STATUS_RETRIES * STATUS_RETRY_INTERVAL_SECONDS} seconds waiting for image generation to complete."
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
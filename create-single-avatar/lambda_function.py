import json
import os
import http.client
import boto3
from boto3.dynamodb.conditions import Key
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Use environment variables for configuration and secrets
DYNAMODB_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
FILTER_TABLE_NAME = os.environ.get('FILTER_TABLE_NAME', 'Filters') # Ensure this matches your table name
LIGHTX_HOST = os.environ.get('LIGHTX_HOST', 'api.lightxeditor.com')
LIGHTX_AVATAR_PATH = os.environ.get('LIGHTX_AVATAR_PATH', '/external/api/v1/avatar')
# IMPORTANT: Store API keys securely, e.g., in Secrets Manager or Lambda environment variables
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
filter_table = dynamodb.Table(FILTER_TABLE_NAME)

def make_lightx_request(image_url, style_image_url, text_prompt):
    """Sends the avatar creation request to the LightX API."""
    if not LIGHTX_API_KEY:
        logger.error("LightX API Key is not configured in environment variables.")
        return None, "API key configuration error."

    conn = None # Initialize conn to None
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json", # Be explicit about accepted response type
            "x-api-key": LIGHTX_API_KEY
        }

        payload = json.dumps({
            "imageUrl": image_url,
            "styleImageUrl": style_image_url,
            "textPrompt": text_prompt
        })

        logger.info(f"Sending request to LightX: Host={LIGHTX_HOST}, Path={LIGHTX_AVATAR_PATH}")
        conn = http.client.HTTPSConnection(LIGHTX_HOST)
        conn.request("POST", LIGHTX_AVATAR_PATH, payload, headers)
        
        res = conn.getresponse()
        response_body = res.read().decode("utf-8")
        
        logger.info(f"LightX Response Status: {res.status}")
        logger.debug(f"LightX Response Body: {response_body}") # Log body only at debug level

        if res.status < 200 or res.status >= 300:
             logger.error(f"LightX API Error: Status={res.status}, Body={response_body}")
             return None, f"LightX API returned status {res.status}"

        response_data = json.loads(response_body)

        # Adjust based on actual LightX response structure - assuming orderId is top-level or in a 'body' field
        order_id = None
        if isinstance(response_data, dict):
             if "orderId" in response_data:
                  order_id = response_data["orderId"]
             elif "body" in response_data and isinstance(response_data["body"], dict) and "orderId" in response_data["body"]:
                  order_id = response_data["body"]["orderId"]
             elif "body" in response_data and isinstance(response_data["body"], str):
                  # Handle case where body might be a JSON string (common with API Gateway proxy)
                  try:
                       inner_body = json.loads(response_data["body"])
                       order_id = inner_body.get("orderId")
                  except json.JSONDecodeError:
                       logger.error(f"Failed to decode inner body string from LightX: {response_data['body']}")


        if not order_id:
            logger.error(f"Could not extract orderId from LightX response: {response_data}")
            return None, "orderId not found in LightX response"

        logger.info(f"Successfully initiated LightX job. Order ID: {order_id}")
        return order_id, None # Success, return order_id and no error

    except http.client.HTTPException as e:
        logger.error(f"HTTP request to LightX failed: {e}", exc_info=True)
        return None, f"HTTP request failed: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from LightX: {e}", exc_info=True)
        # Include response_body in log if available and not too large
        try:
             logger.error(f"Response body was: {response_body[:1000]}") # Log first 1KB
        except NameError:
             pass # response_body might not be defined if connection failed earlier
        return None, "Invalid JSON response from LightX"
    except Exception as e:
        logger.error(f"Unexpected error during LightX request: {e}", exc_info=True)
        return None, f"Unexpected error: {str(e)}"
    finally:
        if conn:
            conn.close()


def lambda_handler(event, context):
    try:
        logger.debug(f"Received event: {event}") # Log incoming event at debug level
        
        # Step 1: Extract parameters
        # Check if the body is already parsed (e.g., by API Gateway direct integration)
        if isinstance(event.get("body"), dict):
            body = event["body"]
        else:
            # Assume body is a JSON string (standard proxy integration)
            body = json.loads(event.get("body", "{}"))

        image_url = body.get("imageUrl")
        # gender = body.get("gender") # Not used in this version, can be removed if not needed later
        # city_id = body.get("city_id") # Not used in this version
        filter_id = body.get("filterId")

        if not all([image_url, filter_id]):
             logger.warning("Missing required parameters: imageUrl or filterId")
             return {
                 "statusCode": 400,
                 "body": json.dumps({"error": "Missing required parameters: imageUrl, filterId"})
             }

        # Step 2: Fetch filter data from DynamoDB
        logger.info(f"Fetching filter details for filterId: {filter_id}")
        try:
            filter_response = filter_table.get_item(Key={"id": filter_id})
            filter_item = filter_response.get("Item")

            if not filter_item:
                logger.warning(f"Filter with ID '{filter_id}' not found.")
                return {
                    "statusCode": 404,
                    "body": json.dumps({"error": f"Filter with ID '{filter_id}' not found."})
                }
        except Exception as e:
             logger.error(f"DynamoDB get_item error for filterId {filter_id}: {e}", exc_info=True)
             return {
                 "statusCode": 500,
                 "body": json.dumps({"error": "Failed to retrieve filter details"})
             }


        style_image_url = filter_item.get("image_style")
        text_prompt = filter_item.get("prompt")

        if not style_image_url or not text_prompt:
             logger.error(f"Filter data incomplete for filterId {filter_id}. Missing style_image or prompt.")
             return {
                 "statusCode": 500,
                 # Be careful not to expose too much detail about internal data structures in error messages
                 "body": json.dumps({"error": "Filter configuration data is incomplete."}) 
             }

        # Step 3: Call LightX avatar API and get orderId
        order_id, error = make_lightx_request(image_url, style_image_url, text_prompt)

        if error:
            # Error already logged in make_lightx_request
            return {
                # Use 502 Bad Gateway if the downstream service failed
                "statusCode": 502, 
                "body": json.dumps({"error": f"Failed to initiate avatar creation: {error}", "filterId": filter_id})
            }

        # Step 4: Immediately return the orderId
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Avatar creation request accepted.",
                "orderId": order_id,
                "filterId": filter_id
            })
        }

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in request body.", exc_info=True)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON format in request body"})
        }
    except Exception as e:
        # General error handler for unexpected issues in the handler itself
        logger.error(f"Unhandled exception in lambda_handler: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }
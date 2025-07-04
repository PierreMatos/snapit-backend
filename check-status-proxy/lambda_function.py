# Lambda function: check-lightx-status-proxy
import json
import os
import http.client
from urllib.parse import urlparse

# Configuration
LIGHTX_STATUS_URL = "https://api.lightxeditor.com/external/api/v1/order-status"
# Store API key in Lambda Environment Variables for security
LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools"
# Allow your specific Amplify origin (or '*' for testing, but be specific for production)
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', "https://master.d1m6exe13kof96.amplifyapp.com") 

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
        
        if not LIGHTX_API_KEY:
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
            "x-api-key": LIGHTX_API_KEY,
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

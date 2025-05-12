import boto3
import http.client
import json
import os
from urllib.parse import urlparse
from boto3.dynamodb.conditions import Attr

# Use environment variables for table name and region for better practice
DYNAMODB_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
FILTER_TABLE_NAME = os.environ.get('FILTER_TABLE_NAME', 'Filters') # Replace 'Filters' with your actual table name if different

dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
filter_table = dynamodb.Table(FILTER_TABLE_NAME)

def make_downstream_request(tool_url, image_url, gender, city_id, filter_id):
    """Makes a POST request to the specified tool_url."""
    try:
        parsed_url = urlparse(tool_url)
        
        payload = json.dumps({
            "imageUrl": image_url,
            "gender": gender,
            "city_id": city_id,
            "filterId": filter_id
        })

        conn = http.client.HTTPSConnection(parsed_url.hostname)
        # Ensure path includes query string if it exists in the original tool_url
        request_path = parsed_url.path
        if parsed_url.query:
             request_path += "?" + parsed_url.query
             
        conn.request("POST", request_path, body=payload, headers={"Content-Type": "application/json", "Accept": "application/json"})

        res = conn.getresponse()
        raw_body = res.read().decode('utf-8') # Specify encoding
        conn.close() # Close the connection

        if res.status < 200 or res.status >= 300:
             print(f"Error response from {tool_url}: {res.status} {res.reason} - Body: {raw_body}")
             return None, f"Downstream service error: {res.status}"

        # Attempt to parse the response body as JSON
        try:
            # Check if the downstream Lambda follows the API Gateway proxy integration format
            outer_response = json.loads(raw_body)
            if isinstance(outer_response, dict) and "body" in outer_response and "statusCode" in outer_response:
                 # If it looks like a proxy response, parse the inner body
                 if isinstance(outer_response["body"], str):
                      parsed_body = json.loads(outer_response["body"])
                 else: # Assume body is already parsed if not a string
                      parsed_body = outer_response["body"]
            else:
                 # Assume the response is the direct JSON payload
                 parsed_body = outer_response
        except json.JSONDecodeError:
             print(f"Failed to decode JSON response from {tool_url}: {raw_body}")
             return None, "Invalid JSON response from downstream service"
             
        # Extract orderId, assuming it's directly in the parsed_body
        order_id = parsed_body.get("orderId")
        if not order_id:
             print(f"orderId not found in response from {tool_url}. Response: {parsed_body}")
             # Returning the whole body might be useful for debugging
             return parsed_body, "orderId not found in response" 
             
        return order_id, None # Return order_id and no error

    except http.client.HTTPException as e:
        print(f"HTTP request failed for {tool_url}: {e}")
        return None, f"HTTP request failed: {str(e)}"
    except json.JSONDecodeError as e:
        print(f"JSON decoding failed for response from {tool_url}: {e}")
        return None, f"Failed to decode response: {str(e)}"
    except Exception as e:
        # Catch any other unexpected errors during the request
        print(f"Unexpected error calling {tool_url}: {e}")
        return None, f"Unexpected error: {str(e)}"


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        image_url = body.get("imageUrl")
        gender = body.get("gender")
        city_id = body.get("city_id")

        if not all([image_url, gender, city_id]):
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required parameters: imageUrl, gender, city_id"})
            }

        # Fetch filters from DB based on city_id
        # Consider using query instead of scan if you have a GSI on city_id for performance
        response = filter_table.scan(
            FilterExpression=Attr('city_id').eq(city_id)
            # Add more filters here if needed, e.g., Attr('gender').eq(gender)
            # Or filter after fetching if the logic is more complex
        )
        filters = response.get("Items", [])

        if not filters:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"No filters found for city_id: {city_id}"})
            }

        # --- Selection Logic ---
        # For now, just take the first filter.
        # TODO: Implement logic to select the specific filter based on gender, photo type, etc.
        selected_filter = filters[0]
        tool_url = selected_filter.get("tool_url")
        filter_id = selected_filter.get("id")

        if not tool_url or not filter_id:
             return {
                 "statusCode": 500,
                 "body": json.dumps({"error": "Selected filter is missing 'tool_url' or 'id'"})
             }
             
        # Call the selected downstream Lambda function
        order_id, error = make_downstream_request(tool_url, image_url, gender, city_id, filter_id)

        if error:
            # Decide if the error from the downstream service should be a 500 or potentially a different code
            return {
                "statusCode": 502, # Bad Gateway might be appropriate if downstream fails
                "body": json.dumps({"error": f"Failed to process avatar creation: {error}", "filterId": filter_id})
            }

        # Successfully received orderId
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Avatar creation initiated successfully.",
                "orderId": order_id,
                "filterId": filter_id # Include the filterId used
            })
        }

    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON format in request body"})
        }
    except Exception as e:
        # General error handler for unexpected issues
        print(f"Unhandled exception: {e}") # Log the error for debugging
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }

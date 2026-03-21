import boto3
import http.client
import json
import os
import time
# import uuid # No longer needed for avatar_id
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

# Use environment variables for table name and region for better practice
DYNAMODB_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
FILTER_TABLE_NAME = os.environ.get('FILTER_TABLE_NAME', 'Filters') # Replace 'Filters' with your actual table name if different
REQUEST_TABLE_NAME = os.environ.get('REQUEST_TABLE_NAME', 'Requests') 
AVATAR_TABLE_NAME = os.environ.get('AVATAR_TABLE_NAME', 'Avatars')   

dynamodb = boto3.resource('dynamodb', region_name=DYNAMODB_REGION)
filter_table = dynamodb.Table(FILTER_TABLE_NAME)
request_table = dynamodb.Table(REQUEST_TABLE_NAME)
avatar_table = dynamodb.Table(AVATAR_TABLE_NAME)   

def make_downstream_request(tool_url, image_url, gender, city_id, filter_id):
    """Makes a POST request to the specified tool_url."""
    parsed_url = urlparse(tool_url)

    payload = json.dumps({
        "imageUrl": image_url,
        "gender": gender,
        "city_id": city_id,
        "filterId": filter_id
    })

    # Ensure path includes query string if it exists in the original tool_url
    request_path = parsed_url.path
    if parsed_url.query:
         request_path += "?" + parsed_url.query

    max_attempts = 3
    last_error = None

    for attempt in range(1, max_attempts + 1):
        conn = None
        try:
            conn = http.client.HTTPSConnection(parsed_url.hostname, timeout=20)
            conn.request("POST", request_path, body=payload, headers={"Content-Type": "application/json", "Accept": "application/json"})

            res = conn.getresponse()
            raw_body = res.read().decode('utf-8', errors='replace')

            # Retry transient 5xx from downstream
            if 500 <= res.status <= 599:
                body_snippet = raw_body[:300]
                last_error = f"Downstream service error: {res.status} (attempt {attempt}/{max_attempts}) body={body_snippet}"
                print(f"Downstream 5xx from {tool_url}: {last_error}")
                if attempt < max_attempts:
                    time.sleep(0.5 * attempt)
                    continue
                return None, last_error

            if res.status < 200 or res.status >= 300:
                body_snippet = raw_body[:300]
                print(f"Error response from {tool_url}: {res.status} {res.reason} - Body: {body_snippet}")
                return None, f"Downstream service error: {res.status} body={body_snippet}"

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
                 print(f"Failed to decode JSON response from {tool_url}: {raw_body[:300]}")
                 return None, "Invalid JSON response from downstream service"

            # Extract orderId, assuming it's directly in the parsed_body
            order_id = parsed_body.get("orderId") if isinstance(parsed_body, dict) else None
            if not order_id:
                 print(f"orderId not found in response from {tool_url}. Response: {str(parsed_body)[:300]}")
                 # Returning the whole body might be useful for debugging
                 return parsed_body, "orderId not found in response"

            return order_id, None # Return order_id and no error

        except http.client.HTTPException as e:
            last_error = f"HTTP request failed: {str(e)} (attempt {attempt}/{max_attempts})"
            print(f"HTTP request failed for {tool_url}: {last_error}")
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            return None, last_error
        except Exception as e:
            # Catch any other unexpected errors during the request
            last_error = f"Unexpected error: {str(e)} (attempt {attempt}/{max_attempts})"
            print(f"Unexpected error calling {tool_url}: {last_error}")
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            return None, last_error
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    return None, last_error or "Downstream request failed"


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        image_url = body.get("imageUrl")
        gender = body.get("gender")
        city_id = body.get("city_id")
        requested_filter_id = body.get("filter_id")
        request_id = body.get("requestId") # Get request_id from frontend
        consent = body.get("consent") or {}
        # user_id = body.get("user_id")

        if not all([image_url, gender, city_id, requested_filter_id, request_id]): # Add request_id to check
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required parameters: imageUrl, gender, city_id, filter_id, requestId"})
            }

        # GDPR consent validation
        consent_given = consent.get("given") is True
        consent_timestamp = consent.get("timestamp")
        consent_version = consent.get("version")
        if not consent_given:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Consent is required before image processing", "consentRequired": True})
            }
        if not consent_timestamp or not consent_version:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid consent payload", "consentRequired": True})
            }
            
        # --- Generate Timestamps ---
        creation_timestamp = datetime.now(timezone.utc).isoformat()
        retention_expiry = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

        # --- Store Request Info (Conditional Put) ---
        try:
            request_table.put_item(
                Item={
                    'id': request_id, # Use request_id from frontend
                    'city_id': city_id,
                    'gender': gender,
                    'imageUrl': image_url,
                    'filter_id': requested_filter_id,
                    # compatibility field already used in other places
                    'photo_url': image_url,
                    # GDPR fields
                    'consentGiven': True,
                    'consentTimestamp': consent_timestamp,
                    'consentVersion': consent_version,
                    'retentionExpiry': retention_expiry,
                    'creation_date': creation_timestamp,
                    # 'user_id': user_id,
                    # 'gender': gender 
                },
                ConditionExpression='attribute_not_exists(id)' 
            )
            print(f"Successfully created Request record for id: {request_id}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                print(f"Request record for id {request_id} already exists. Skipping creation.")
                pass 
            else:
                print(f"Error writing to Requests table: {e.response['Error']['Message']}")
                return {"statusCode": 500, "body": json.dumps({"error": "Failed to save request details"})}
        except Exception as db_error:
             print(f"Unexpected error writing to Requests table: {db_error}")
             return {"statusCode": 500, "body": json.dumps({"error": "Failed to save request details"})}


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
        # Find the filter that matches the requested_filter_id
        selected_filter = None
        for f in filters:
            if f.get("id") == requested_filter_id:
                selected_filter = f
                break
        
        if not selected_filter:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"Filter with id '{requested_filter_id}' not found for city_id: {city_id}"})
            }

        tool_url = selected_filter.get("tool_url")
        filter_id = selected_filter.get("id") # This will be the requested_filter_id

        if not tool_url or not filter_id: # filter_id will always be present if selected_filter is found
             return {
                 "statusCode": 500,
                 "body": json.dumps({"error": "Selected filter is missing 'tool_url' or 'id'"})
             }
             
        # Call the selected downstream Lambda function
        order_id, error = make_downstream_request(tool_url, image_url, gender, city_id, filter_id)

        if error or not order_id:
            # If make_downstream_request returns an error OR fails to return an order_id
            error_message = error or "Downstream service did not return an orderId."
            return {
                "statusCode": 502, 
                "body": json.dumps({"error": f"Failed to process avatar creation: {error_message}", "filterId": filter_id})
            }

        # --- Store Initial Avatar Info (Using order_id as PK) ---
        try:
            avatar_table.put_item(
                Item={
                    'id': order_id, # <<< Use order_id as the primary key for Avatars table
                    'request_id': request_id, # Link back to the main request (from frontend)
                    'filter_id': filter_id,
                    # 'order_id': order_id, # Redundant if id is order_id
                    'status': 'PENDING', 
                    'creation_date': creation_timestamp,
                    # 'output_url': None 
                }
                # No ConditionExpression needed here assuming order_id from LightX is unique
            )
            print(f"Successfully created Avatar record for id (order_id): {order_id}")
        except Exception as db_error:
             print(f"Error writing initial item to Avatars table: {db_error}")
             return {
                 "statusCode": 500, 
                 "body": json.dumps({
                     "error": "Failed to save initial avatar tracking data", 
                     "orderId": order_id, 
                     "filterId": filter_id 
                 })
             }

        # Successfully received orderId and saved initial avatar state
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Avatar creation initiated successfully.",
                "orderId": order_id,
                "filterId": filter_id # Return filterId and orderId (no separate avatarId)
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

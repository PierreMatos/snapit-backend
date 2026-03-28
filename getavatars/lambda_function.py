import json
import boto3
import os
import re

# Initialize DynamoDB client
# It's good practice to initialize outside the handler for potential reuse
dynamodb = boto3.resource('dynamodb')
# Table name from environment variable or a default
AVATARS_TABLE_NAME = os.environ.get('AVATARS_TABLE_NAME', 'Avatars')
REQUEST_TABLE_NAME = os.environ.get('REQUEST_TABLE_NAME', 'Requests')
ORDERS_TABLE_NAME = os.environ.get('ORDERS_TABLE_NAME', 'Orders')
table = dynamodb.Table(AVATARS_TABLE_NAME)
request_table = dynamodb.Table(REQUEST_TABLE_NAME)
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)
UUID_V4_PATTERN = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

def clean_request_id(raw_id: str) -> str:
    """
    Enforce UUID-only request IDs.
    """
    if not raw_id:
        return ""
    request_id = str(raw_id).strip()
    if re.fullmatch(UUID_V4_PATTERN, request_id):
        return request_id.lower()
    return ""


def get_request_metadata(request_id: str) -> dict:
    """Fetch request metadata needed by internal tools."""
    try:
        response = request_table.get_item(Key={"id": request_id})
        item = response.get("Item", {})
        return {
            "requestPhotoUrl": item.get("photo_url"),
            "cityId": item.get("city_id")
        }
    except Exception as exc:
        print(f"Warning: failed to fetch request metadata for {request_id}: {exc}")
        return {"requestPhotoUrl": None, "cityId": None}


def normalize_avatar_ids(raw_avatar_ids):
    """Normalize avatarIds from list/string/legacy formats into a list of strings."""
    if raw_avatar_ids is None:
        return []
    if isinstance(raw_avatar_ids, list):
        result = []
        for item in raw_avatar_ids:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                value = item.get("S") or item.get("s") or item.get("id")
                if value:
                    result.append(str(value).strip())
            elif item is not None:
                result.append(str(item).strip())
        return [x for x in result if x]
    if isinstance(raw_avatar_ids, str):
        text = raw_avatar_ids.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                return normalize_avatar_ids(parsed)
            except Exception:
                pass
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    return [str(raw_avatar_ids).strip()] if str(raw_avatar_ids).strip() else []


def get_avatar_items_from_orders(request_id: str):
    """Fallback: fetch avatar items via Orders.requestId -> Orders.avatarIds -> Avatars.id."""
    try:
        order_scan = orders_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('requestId').eq(request_id)
        )
        orders = order_scan.get("Items", [])
        if not orders:
            return []

        avatar_ids = []
        for order in orders:
            for avatar_id in normalize_avatar_ids(order.get("avatarIds")):
                if avatar_id not in avatar_ids:
                    avatar_ids.append(avatar_id)

        if not avatar_ids:
            return []

        response = dynamodb.batch_get_item(
            RequestItems={
                AVATARS_TABLE_NAME: {
                    "Keys": [{"id": avatar_id} for avatar_id in avatar_ids]
                }
            }
        )
        return response.get("Responses", {}).get(AVATARS_TABLE_NAME, [])
    except Exception as exc:
        print(f"Warning: fallback fetch via Orders failed for {request_id}: {exc}")
        return []

def lambda_handler(event, context):
    """
    Lambda function to fetch avatars based on request_id.
    Assumes request_id is passed as a path parameter via API Gateway.
    e.g., /avatars/{request_id}
    """
    print(f"Received event: {json.dumps(event)}")

    request_id_value = ""

    # Only extract from pathParameters
    if 'pathParameters' in event and event['pathParameters'] is not None:
        if 'request_id' in event['pathParameters']:
            raw_id = event['pathParameters']['request_id']
            request_id_value = clean_request_id(raw_id)
            print(f"Extracted and cleaned request_id from pathParameters: {request_id_value}")
        elif 'request-id' in event['pathParameters']:
            raw_id = event['pathParameters']['request-id']
            request_id_value = clean_request_id(raw_id)
            print(f"Extracted and cleaned request_id from pathParameters: {request_id_value}")

    if not request_id_value:
        error_payload = {
            'error': 'Invalid request_id. UUID is required.',
            'pathParameters_in_event': event.get('pathParameters') if isinstance(event, dict) else None
        }
        print(f"Error: request_id not found. Details: {json.dumps(error_payload)}")
        return {
            'statusCode': 400,
            'headers': { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
            'body': json.dumps(error_payload)
        }

    print(f"Fetching avatars for request_id: {request_id_value} from table: {AVATARS_TABLE_NAME}")

    try:
        request_metadata = get_request_metadata(request_id_value)

        # Using scan as per previous change. Consider GSI for performance with large tables.
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('request_id').eq(request_id_value)
        )
        raw_items = response.get('Items', [])
        if not raw_items:
            print(f"No avatar items found by request_id scan. Falling back via Orders table for {request_id_value}.")
            raw_items = get_avatar_items_from_orders(request_id_value)
        
        # Transform items for the frontend
        formatted_items = []
        for item in raw_items:
            formatted_item = {
                'id': item.get('id'), # This is the unique ID of the image/filter record
                'originalUrl': item.get('output_url'),
                'thumbnailUrl': item.get('output_url'), # Using output_url for thumbnail as well
                'alt': f"Avatar style {item.get('filter_id', item.get('id', ''))}",
                'filter_id': item.get('filter_id'), # Keep other fields if needed by frontend later
                'status': item.get('status'),
                'creation_date': item.get('creation_date'),
                'requestId': request_id_value,
                'requestPhotoUrl': request_metadata.get('requestPhotoUrl'),
                'cityId': request_metadata.get('cityId')
            }
            # Ensure essential URLs are present
            if formatted_item['originalUrl']:
                 formatted_items.append(formatted_item)
            else:
                print(f"Skipping item due to missing output_url: {item.get('id')}")

        if not formatted_items:
            print(f"No items with output_url found for request_id: {request_id_value}")
            return {
                'statusCode': 200,
                'headers': { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
                'body': json.dumps([]) # Return empty list if no valid items
            }

        print(f"Found and formatted {len(formatted_items)} items for request_id: {request_id_value}")
        return {
            'statusCode': 200,
            'headers': { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
            'body': json.dumps(formatted_items)
        }

    except Exception as e:
        print(f"Error querying DynamoDB or processing: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'headers': { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
            'body': json.dumps({'error': 'Could not retrieve avatars', 'details': str(e)})
        }

# For local testing (won't run in Lambda with this event if it's the simple one)
if __name__ == '__main__':
    # Test case: HTTP API v2.0 like event
    mock_http_api_v2_event = {
        "version": "2.0",
        "routeKey": "GET /api/avatars/{request_id}",
        "rawPath": "/api/avatars/test-request-123",
        "pathParameters": {
            "request_id": "test-request-123-http-v2"
        }
    }
    print("--- Testing with HTTP API v2.0 like event --- ")
    # print(lambda_handler(mock_http_api_v2_event, {}))
    print("Note: Local DynamoDB test requires setup/mocking.") 
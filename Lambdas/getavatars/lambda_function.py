import json
import boto3
import os

# Initialize DynamoDB client
# It's good practice to initialize outside the handler for potential reuse
dynamodb = boto3.resource('dynamodb')
# Table name from environment variable or a default
AVATARS_TABLE_NAME = os.environ.get('AVATARS_TABLE_NAME', 'Avatars')
table = dynamodb.Table(AVATARS_TABLE_NAME)

def lambda_handler(event, context):
    """
    Lambda function to fetch avatars based on request_id.
    Assumes request_id is passed as a path parameter via API Gateway.
    e.g., /avatars/{request_id}
    """
    print(f"Received event: {json.dumps(event)}")

    request_id_value = "0bd40165-4113-40aa-bdcf-6b83f7804155"

    # Only extract from pathParameters
    if 'pathParameters' in event and event['pathParameters'] is not None:
        if 'request_id' in event['pathParameters']:
            request_id_value = event['pathParameters']['request_id']
            print(f"Extracted request_id from pathParameters (key: request_id): {request_id_value}")
        elif 'request-id' in event['pathParameters']:
            request_id_value = event['pathParameters']['request-id']
            print(f"Extracted request_id from pathParameters (key: request-id): {request_id_value}")

    if not request_id_value:
        error_payload = {
            'error': 'request_id could not be extracted from the path',
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
        # Using scan as per previous change. Consider GSI for performance with large tables.
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('request_id').eq(request_id_value)
        )
        raw_items = response.get('Items', [])
        
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
                'creation_date': item.get('creation_date')
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
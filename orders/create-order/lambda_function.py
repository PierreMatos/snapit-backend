"""Lambda function: Create Order - POST /api/orders"""
import json
import os
import boto3
import uuid
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))

# Table names from environment variables or defaults
ORDERS_TABLE_NAME = os.environ.get('ORDERS_TABLE_NAME', 'Orders')
AVATARS_TABLE_NAME = os.environ.get('AVATARS_TABLE_NAME', 'Avatars')
ORDER_COUNTER_TABLE_NAME = os.environ.get('ORDER_COUNTER_TABLE_NAME', 'OrderCounter')

# Initialize tables
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)
avatars_table = dynamodb.Table(AVATARS_TABLE_NAME)
order_counter_table = dynamodb.Table(ORDER_COUNTER_TABLE_NAME)

# CORS headers
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
}

def get_cors_response(status_code, body):
    """Helper to create response with CORS headers"""
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body) if isinstance(body, dict) else body
    }

def handle_options():
    """Handle CORS preflight OPTIONS request"""
    return {
        "statusCode": 204,
        "headers": CORS_HEADERS,
        "body": ""
    }

def generate_order_id():
    """Generate sequential order ID (A1, A2, A3, etc.) using counter table"""
    try:
        try:
            response = order_counter_table.update_item(
                Key={"id": "order_counter"},
                UpdateExpression="ADD #count :incr SET #updated = :now",
                ExpressionAttributeNames={
                    "#count": "count",
                    "#updated": "updated_at"
                },
                ExpressionAttributeValues={
                    ":incr": 1,
                    ":now": datetime.now(timezone.utc).isoformat()
                },
                ReturnValues="UPDATED_NEW"
            )
            count = response["Attributes"]["count"]
            return f"A{count}"
        except ClientError as e:
            if e.response['Error']['Code'] in ['ResourceNotFoundException', 'ValidationException']:
                try:
                    order_counter_table.put_item(
                        Item={
                            "id": "order_counter",
                            "count": 1,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }
                    )
                    return "A1"
                except Exception:
                    return f"A{int(datetime.now(timezone.utc).timestamp())}"
            else:
                return f"A{int(datetime.now(timezone.utc).timestamp())}"
    except Exception as e:
        print(f"Error generating order ID: {str(e)}")
        return f"A{int(datetime.now(timezone.utc).timestamp())}"

def get_avatars_by_ids(avatar_ids):
    """Batch get avatars from DynamoDB"""
    if not avatar_ids:
        return []
    
    try:
        avatars = []
        for i in range(0, len(avatar_ids), 100):
            chunk = avatar_ids[i:i+100]
            keys = [{"id": avatar_id} for avatar_id in chunk]
            
            response = dynamodb.batch_get_item(
                RequestItems={
                    AVATARS_TABLE_NAME: {
                        "Keys": keys
                    }
                }
            )
            
            chunk_avatars = response.get("Responses", {}).get(AVATARS_TABLE_NAME, [])
            avatars.extend(chunk_avatars)
        
        avatar_map = {avatar["id"]: avatar for avatar in avatars}
        
        result = []
        for avatar_id in avatar_ids:
            if avatar_id in avatar_map:
                avatar = avatar_map[avatar_id]
                result.append({
                    "avatarId": avatar["id"],
                    "outputUrl": avatar.get("output_url", ""),
                    "filterId": avatar.get("filter_id", ""),
                    "creationDate": avatar.get("creation_date", "")
                })
        
        return result
    except Exception as e:
        print(f"Error fetching avatars: {str(e)}")
        return []

def lambda_handler(event, context):
    """Create a new order"""
    try:
        # Handle CORS preflight
        request_context = event.get("requestContext", {})
        http_method = request_context.get("http", {}).get("method", "")
        if http_method == "OPTIONS":
            return handle_options()
        
        # Parse request body
        body = {}
        if event.get("body"):
            try:
                body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
            except json.JSONDecodeError:
                return get_cors_response(400, {"error": "Invalid JSON in request body"})
        
        request_id = body.get("requestId")
        city_id = body.get("cityId")
        price = body.get("price")
        avatar_ids = body.get("avatarIds", [])
        
        # Validation
        if not request_id:
            return get_cors_response(400, {"error": "Missing requestId"})
        if not city_id:
            return get_cors_response(400, {"error": "Missing cityId"})
        if price is None:
            return get_cors_response(400, {"error": "Missing price"})
        if not avatar_ids or len(avatar_ids) == 0:
            return get_cors_response(400, {"error": "Missing or empty avatarIds"})
        
        # Generate order ID and get current date
        order_id = generate_order_id()
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        capture_timestamp = datetime.now(timezone.utc).isoformat()
        
        # Get first avatar's output_url for imageUrl
        avatars = get_avatars_by_ids([avatar_ids[0]])
        image_url = avatars[0]["outputUrl"] if avatars else ""
        
        # Generate unique ID for the order item
        order_item_id = str(uuid.uuid4())
        
        # Create order item
        order_item = {
            "id": order_item_id,
            "orderId": order_id,
            "date": current_date,
            "status": "active",
            "price": price,
            "paidTimestamp": None,
            "captureTimestamp": capture_timestamp,
            "cityId": city_id,
            "requestId": request_id,
            "imageUrl": image_url,
            "avatarIds": avatar_ids
        }
        
        # Save to DynamoDB
        orders_table.put_item(Item=order_item)
        
        return get_cors_response(200, {
            "success": True,
            "order": order_item
        })
        
    except Exception as e:
        print(f"Error creating order: {str(e)}")
        import traceback
        traceback.print_exc()
        return get_cors_response(500, {"error": f"Failed to create order: {str(e)}"})

"""Lambda function: Update Order Avatars - PUT /api/orders/{orderId}/avatars"""
import json
import os
import boto3
from decimal import Decimal
from botocore.exceptions import ClientError

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))

# Table names
ORDERS_TABLE_NAME = os.environ.get('ORDERS_TABLE_NAME', 'Orders')
AVATARS_TABLE_NAME = os.environ.get('AVATARS_TABLE_NAME', 'Avatars')

# Initialize tables
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)
avatars_table = dynamodb.Table(AVATARS_TABLE_NAME)

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

def convert_decimals(obj):
    """Recursively convert Decimal objects to int/float for JSON serialization"""
    if isinstance(obj, Decimal):
        # Convert Decimal to int if it's a whole number, otherwise float
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    return obj

def get_avatars_by_ids(avatar_ids):
    """Get avatars from DynamoDB by IDs"""
    if not avatar_ids:
        return []
    
    avatars = []
    
    # Use individual get_item calls - more reliable than batch_get_item
    for avatar_id in avatar_ids:
        try:
            print(f"Fetching avatar: {avatar_id}")
            response = avatars_table.get_item(Key={"id": avatar_id})
            
            if "Item" in response:
                avatar = response["Item"]
                print(f"Found avatar: {avatar_id}")
                avatars.append(avatar)
            else:
                print(f"Avatar {avatar_id} not found in table")
        except Exception as e:
            print(f"Error fetching avatar {avatar_id}: {str(e)}")
            import traceback
            traceback.print_exc()
    
    print(f"Total avatars found: {len(avatars)} out of {len(avatar_ids)} requested")
    print(f"Requested IDs: {avatar_ids}")
    print(f"Found IDs: {[a.get('id') for a in avatars]}")
    
    # Format results
    result = []
    for avatar in avatars:
        result.append({
            "avatarId": avatar.get("id"),
            "outputUrl": avatar.get("output_url", ""),
            "filterId": avatar.get("filter_id", ""),
            "creationDate": avatar.get("creation_date", "")
        })
    
    return result

def lambda_handler(event, context):
    """Update order's avatar IDs"""
    try:
        # Handle CORS preflight
        request_context = event.get("requestContext", {})
        http_method = request_context.get("http", {}).get("method", "")
        if http_method == "OPTIONS":
            return handle_options()
        
        # Get orderId from path parameters
        path_parameters = event.get("pathParameters") or {}
        order_id = path_parameters.get("orderId") or path_parameters.get("orderid")
        
        if not order_id:
            return get_cors_response(400, {"error": "Missing orderId in path"})
        
        # Parse request body
        body = {}
        if event.get("body"):
            try:
                body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
            except json.JSONDecodeError:
                return get_cors_response(400, {"error": "Invalid JSON in request body"})
        
        new_avatar_ids = body.get("avatarIds")
        
        if not new_avatar_ids:
            return get_cors_response(400, {"error": "Missing avatarIds"})
        
        if not isinstance(new_avatar_ids, list) or len(new_avatar_ids) == 0:
            return get_cors_response(400, {"error": "avatarIds must be a non-empty array"})
        
        # Validate that all avatar IDs exist
        avatars = get_avatars_by_ids(new_avatar_ids)
        if len(avatars) != len(new_avatar_ids):
            missing_ids = set(new_avatar_ids) - {a["avatarId"] for a in avatars}
            return get_cors_response(400, {
                "error": f"Some avatar IDs do not exist: {list(missing_ids)}"
            })
        
        # The table's primary key is "id", but we want to find by "orderId"
        # First, find the order by scanning for orderId
        from boto3.dynamodb.conditions import Attr
        
        order = None
        order_primary_key = None
        
        # Try get_item first (in case there's a GSI)
        try:
            response = orders_table.get_item(Key={"orderId": order_id})
            if "Item" in response:
                order = response["Item"]
                order_primary_key = {"orderId": order_id}
        except Exception as e:
            # If ValidationException, orderId is not the PK - that's expected
            if "ValidationException" not in str(e) and "does not match the schema" not in str(e):
                raise
        
        # If not found via get_item, scan for orderId
        if not order:
            try:
                scan_response = orders_table.scan(
                    FilterExpression=Attr("orderId").eq(order_id)
                )
                items = scan_response.get("Items", [])
                if not items:
                    return get_cors_response(404, {
                        "error": f"Order {order_id} not found",
                        "message": f"No order found with orderId: {order_id}"
                    })
                order = items[0]
                # Get the primary key (id) from the found order
                order_primary_key = {"id": order.get("id")}
                if not order_primary_key["id"]:
                    return get_cors_response(500, {"error": "Order found but missing primary key 'id'"})
            except Exception as scan_err:
                print(f"Error scanning for order: {str(scan_err)}")
                return get_cors_response(500, {
                    "error": f"Failed to find order: {str(scan_err)}"
                })
        
        # Get first avatar's output_url for imageUrl
        first_avatar = avatars[0] if avatars else None
        new_image_url = first_avatar["outputUrl"] if first_avatar else ""
        
        # Update order using the primary key (id)
        updated_response = orders_table.update_item(
            Key=order_primary_key,
            UpdateExpression="SET avatarIds = :avatarIds, imageUrl = :imageUrl",
            ExpressionAttributeValues={
                ":avatarIds": new_avatar_ids,
                ":imageUrl": new_image_url
            },
            ReturnValues="ALL_NEW"
        )
        
        updated_order = updated_response.get("Attributes")
        
        # Add avatars to response
        order_dict = dict(updated_order)
        order_dict["avatars"] = avatars
        
        # Convert Decimal objects to int/float for JSON serialization
        order_dict = convert_decimals(order_dict)
        
        return get_cors_response(200, {
            "success": True,
            "order": order_dict
        })
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return get_cors_response(404, {"error": f"Order {order_id} not found"})
        print(f"Error updating order avatars: {str(e)}")
        return get_cors_response(500, {"error": f"Failed to update order avatars: {str(e)}"})
    except Exception as e:
        print(f"Error updating order avatars: {str(e)}")
        import traceback
        traceback.print_exc()
        return get_cors_response(500, {"error": f"Failed to update order avatars: {str(e)}"})

"""Lambda function: Get Order - GET /api/orders/{orderId}"""
import json
import os
import boto3

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))

# Table names
ORDERS_TABLE_NAME = os.environ.get('ORDERS_TABLE_NAME', 'Orders')
AVATARS_TABLE_NAME = os.environ.get('AVATARS_TABLE_NAME', 'Avatars')
REQUESTS_TABLE_NAME = os.environ.get('REQUESTS_TABLE_NAME', 'Requests')

# Initialize tables
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)
avatars_table = dynamodb.Table(AVATARS_TABLE_NAME)
requests_table = dynamodb.Table(REQUESTS_TABLE_NAME)

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

def get_request_by_id(request_id):
    """Get request details from Requests table"""
    try:
        response = requests_table.get_item(Key={"id": request_id})
        return response.get("Item")
    except Exception as e:
        print(f"Error fetching request: {str(e)}")
        return None

def lambda_handler(event, context):
    """Get order details with avatars and request info"""
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
        
        # The table's primary key is "id", but we want to query by "orderId"
        # Since orderId is not the primary key, we need to scan with a filter
        from boto3.dynamodb.conditions import Attr
        
        order = None
        
        # Try get_item first (in case there's a GSI on orderId)
        try:
            response = orders_table.get_item(Key={"orderId": order_id})
            if "Item" in response:
                order = response["Item"]
        except Exception as e:
            # If ValidationException, orderId is not the PK - that's expected, use scan
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
                order = items[0]  # Take first match
            except Exception as scan_err:
                print(f"Error scanning for order: {str(scan_err)}")
                import traceback
                traceback.print_exc()
                return get_cors_response(500, {
                    "error": f"Failed to query order: {str(scan_err)}"
                })
        
        # Get avatars
        avatar_ids = order.get("avatarIds", [])
        avatars = get_avatars_by_ids(avatar_ids)
        
        # Get request details
        request_id = order.get("requestId")
        request = None
        if request_id:
            request = get_request_by_id(request_id)
        
        # Build response
        order_dict = dict(order)
        order_dict["avatars"] = avatars
        if request:
            order_dict["request"] = request
        
        return get_cors_response(200, {"order": order_dict})
        
    except Exception as e:
        print(f"Error viewing order: {str(e)}")
        import traceback
        traceback.print_exc()
        return get_cors_response(500, {"error": f"Failed to get order: {str(e)}"})

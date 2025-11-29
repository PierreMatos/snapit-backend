"""Lambda function: List Orders - GET /api/orders"""
import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

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
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    return obj

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
    """List orders for a given date with optional status filter"""
    try:
        # Handle CORS preflight
        request_context = event.get("requestContext", {})
        http_method = request_context.get("http", {}).get("method", "")
        if http_method == "OPTIONS":
            return handle_options()
        
        # Get query string parameters
        query_string_parameters = event.get("queryStringParameters") or {}
        
        # Get date from query params or use today
        date = query_string_parameters.get("date")
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Get status filter (optional)
        status = query_string_parameters.get("status")
        
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return get_cors_response(400, {"error": "Invalid date format. Use YYYY-MM-DD"})
        
        # Query using GSI DateStatusIndex
        # If GSI doesn't exist or query fails, fall back to scan with filter
        from boto3.dynamodb.conditions import Attr
        
        all_orders = []
        
        try:
            if status:
                # Query with both date and status
                try:
                    response = orders_table.query(
                        IndexName="DateStatusIndex",
                        KeyConditionExpression=Key("date").eq(date) & Key("status").eq(status)
                    )
                    all_orders.extend(response.get("Items", []))
                except Exception as query_err:
                    print(f"GSI query failed: {str(query_err)}, falling back to scan")
                    # Fallback to scan
                    scan_response = orders_table.scan(
                        FilterExpression=Attr("date").eq(date) & Attr("status").eq(status)
                    )
                    all_orders.extend(scan_response.get("Items", []))
            else:
                # Query by date only (need to get all statuses)
                for status_val in ["active", "paid", "cancelled"]:
                    try:
                        response = orders_table.query(
                            IndexName="DateStatusIndex",
                            KeyConditionExpression=Key("date").eq(date) & Key("status").eq(status_val)
                        )
                        all_orders.extend(response.get("Items", []))
                    except Exception as query_err:
                        print(f"GSI query failed for status {status_val}: {str(query_err)}, using scan")
                        # Fallback to scan for this status
                        scan_response = orders_table.scan(
                            FilterExpression=Attr("date").eq(date) & Attr("status").eq(status_val)
                        )
                        all_orders.extend(scan_response.get("Items", []))
        except Exception as e:
            print(f"Error querying orders: {str(e)}")
            # Final fallback: scan all orders and filter by date
            try:
                scan_response = orders_table.scan(
                    FilterExpression=Attr("date").eq(date)
                )
                all_orders = scan_response.get("Items", [])
                if status:
                    # Filter by status if provided
                    all_orders = [o for o in all_orders if o.get("status") == status]
            except Exception as scan_err:
                print(f"Scan also failed: {str(scan_err)}")
                return get_cors_response(500, {
                    "error": f"Failed to query orders: {str(scan_err)}"
                })
        
        # Format response
        orders = []
        for order in all_orders:
            avatar_ids = order.get("avatarIds", [])
            # Handle DynamoDB list format if needed
            if avatar_ids and isinstance(avatar_ids[0], dict) and "S" in avatar_ids[0]:
                # Convert from DynamoDB format: [{"S": "1"}, {"S": "2"}] to ["1", "2"]
                avatar_ids = [item.get("S", item.get("s", "")) for item in avatar_ids if isinstance(item, dict)]
            
            avatars = get_avatars_by_ids(avatar_ids)
            
            order_dict = dict(order)
            order_dict["avatars"] = avatars
            # Convert Decimal objects to int/float for JSON serialization
            order_dict = convert_decimals(order_dict)
            orders.append(order_dict)
        
        # Sort orders by captureTimestamp (newest first)
        # Orders without captureTimestamp will be placed at the end
        orders.sort(key=lambda x: x.get("captureTimestamp") or "", reverse=True)
        
        print(f"Found {len(orders)} orders for date {date} with status {status or 'all'}")
        
        return get_cors_response(200, {"orders": orders})
        
    except Exception as e:
        print(f"Error listing orders: {str(e)}")
        import traceback
        traceback.print_exc()
        return get_cors_response(500, {"error": f"Failed to list orders: {str(e)}"})

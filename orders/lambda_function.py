import json
import os
import boto3
import uuid
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))

# Table names from environment variables or defaults
ORDERS_TABLE_NAME = os.environ.get('ORDERS_TABLE_NAME', 'Orders')
AVATARS_TABLE_NAME = os.environ.get('AVATARS_TABLE_NAME', 'Avatars')
REQUESTS_TABLE_NAME = os.environ.get('REQUESTS_TABLE_NAME', 'Requests')
ORDER_COUNTER_TABLE_NAME = os.environ.get('ORDER_COUNTER_TABLE_NAME', 'OrderCounter')

# Initialize tables
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)
avatars_table = dynamodb.Table(AVATARS_TABLE_NAME)
requests_table = dynamodb.Table(REQUESTS_TABLE_NAME)
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
        # Try to increment counter (will create item if it doesn't exist with ADD operation)
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
            # If update fails, try to create the item
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
                except Exception as create_err:
                    # Fallback to timestamp if creation fails
                    print(f"Failed to create counter: {str(create_err)}")
                    return f"A{int(datetime.now(timezone.utc).timestamp())}"
            else:
                # Other error, fallback to timestamp
                print(f"Error updating counter: {str(e)}")
                return f"A{int(datetime.now(timezone.utc).timestamp())}"
    except Exception as e:
        # Fallback to timestamp-based ID on any error
        print(f"Error generating order ID: {str(e)}")
        return f"A{int(datetime.now(timezone.utc).timestamp())}"

def get_avatars_by_ids(avatar_ids):
    """Batch get avatars from DynamoDB"""
    if not avatar_ids:
        return []
    
    try:
        # DynamoDB BatchGetItem can handle up to 100 items
        # Split into chunks if needed
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
        
        # Create a map for quick lookup
        avatar_map = {avatar["id"]: avatar for avatar in avatars}
        
        # Return avatars in the same order as requested IDs
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

def create_order(body):
    """Create a new order"""
    try:
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
        return get_cors_response(500, {"error": f"Failed to create order: {str(e)}"})

def list_orders(query_params):
    """List orders for a given date with optional status filter"""
    try:
        # Get date from query params or use today
        date = query_params.get("date") if query_params else None
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Get status filter (optional)
        status = query_params.get("status") if query_params else None
        
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return get_cors_response(400, {"error": "Invalid date format. Use YYYY-MM-DD"})
        
        # Query using GSI DateStatusIndex
        if status:
            # Query with both date and status
            response = orders_table.query(
                IndexName="DateStatusIndex",
                KeyConditionExpression=Key("date").eq(date) & Key("status").eq(status)
            )
        else:
            # Query by date only (need to get all statuses)
            # Since we can't query GSI with only partition key and no sort key filter,
            # we'll query for each status or use a scan with filter
            # For efficiency, query each status separately
            all_orders = []
            for status_val in ["active", "paid", "cancelled"]:
                try:
                    response = orders_table.query(
                        IndexName="DateStatusIndex",
                        KeyConditionExpression=Key("date").eq(date) & Key("status").eq(status_val)
                    )
                    all_orders.extend(response.get("Items", []))
                except Exception as e:
                    print(f"Error querying status {status_val}: {str(e)}")
            
            # Format response
            orders = []
            for order in all_orders:
                avatar_ids = order.get("avatarIds", [])
                avatars = get_avatars_by_ids(avatar_ids)
                
                order_dict = dict(order)
                order_dict["avatars"] = avatars
                orders.append(order_dict)
            
            return get_cors_response(200, {"orders": orders})
        
        # If status was provided, process the response
        orders = []
        for order in response.get("Items", []):
            avatar_ids = order.get("avatarIds", [])
            avatars = get_avatars_by_ids(avatar_ids)
            
            order_dict = dict(order)
            order_dict["avatars"] = avatars
            orders.append(order_dict)
        
        return get_cors_response(200, {"orders": orders})
        
    except Exception as e:
        print(f"Error listing orders: {str(e)}")
        return get_cors_response(500, {"error": f"Failed to list orders: {str(e)}"})

def update_order_status(order_id, body):
    """Update order status"""
    try:
        new_status = body.get("status")
        
        if not new_status:
            return get_cors_response(400, {"error": "Missing status"})
        
        if new_status not in ["active", "paid", "cancelled"]:
            return get_cors_response(400, {"error": "Invalid status. Must be 'active', 'paid', or 'cancelled'"})
        
        # Get the current order (orderId is the primary key)
        response = orders_table.get_item(Key={"orderId": order_id})
        
        if "Item" not in response:
            return get_cors_response(404, {"error": f"Order {order_id} not found"})
        
        order = response["Item"]
        current_status = order.get("status")
        
        # Prepare update expression
        update_expr = "SET #status = :status"
        expr_names = {"#status": "status"}
        expr_values = {":status": new_status}
        
        # Handle paidTimestamp
        if new_status == "paid":
            paid_timestamp = datetime.now(timezone.utc).isoformat()
            update_expr += ", paidTimestamp = :paidTimestamp"
            expr_values[":paidTimestamp"] = paid_timestamp
        elif current_status == "paid" and new_status != "paid":
            # Changing from paid to something else, clear paidTimestamp
            update_expr += ", paidTimestamp = :null"
            expr_values[":null"] = None
        
        # Update the order
        updated_response = orders_table.update_item(
            Key={"orderId": order_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW"
        )
        
        updated_order = updated_response.get("Attributes")
        
        return get_cors_response(200, {
            "success": True,
            "order": updated_order
        })
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return get_cors_response(404, {"error": f"Order {order_id} not found"})
        print(f"Error updating order status: {str(e)}")
        return get_cors_response(500, {"error": f"Failed to update order status: {str(e)}"})
    except Exception as e:
        print(f"Error updating order status: {str(e)}")
        return get_cors_response(500, {"error": f"Failed to update order status: {str(e)}"})

def view_order(order_id):
    """Get order details with avatars and request info"""
    try:
        # Get order by orderId
        # Note: orderId is the primary key, so we can query directly
        response = orders_table.get_item(Key={"orderId": order_id})
        
        if "Item" not in response:
            return get_cors_response(404, {"error": f"Order {order_id} not found"})
        
        order = response["Item"]
        
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
        return get_cors_response(500, {"error": f"Failed to get order: {str(e)}"})

def update_order_avatars(order_id, body):
    """Update order's avatar IDs"""
    try:
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
        
        # Get current order
        response = orders_table.get_item(Key={"orderId": order_id})
        
        if "Item" not in response:
            return get_cors_response(404, {"error": f"Order {order_id} not found"})
        
        # Get first avatar's output_url for imageUrl
        first_avatar = avatars[0] if avatars else None
        new_image_url = first_avatar["outputUrl"] if first_avatar else ""
        
        # Update order
        orders_table.update_item(
            Key={"orderId": order_id},
            UpdateExpression="SET avatarIds = :avatarIds, imageUrl = :imageUrl",
            ExpressionAttributeValues={
                ":avatarIds": new_avatar_ids,
                ":imageUrl": new_image_url
            },
            ReturnValues="ALL_NEW"
        )
        
        # Get updated order
        updated_response = orders_table.get_item(Key={"orderId": order_id})
        updated_order = updated_response.get("Item")
        
        # Add avatars to response
        order_dict = dict(updated_order)
        order_dict["avatars"] = avatars
        
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
        return get_cors_response(500, {"error": f"Failed to update order avatars: {str(e)}"})

def normalize_path(path):
    """Normalize API Gateway path by removing stage prefix if present"""
    if not path:
        return path
    
    # Ensure path starts with /
    if not path.startswith('/'):
        path = '/' + path
    
    # If path starts with /api, don't normalize - it's part of the resource path
    if path.startswith('/api'):
        return path
    
    # Split path into parts
    path_parts = [p for p in path.split('/') if p]  # Remove empty strings
    
    if not path_parts:
        return path
    
    # Check if first part looks like a stage name
    # API Gateway paths can be: /stage/resource or /resource
    first_part = path_parts[0].lower()
    common_stages = ['prod', 'dev', 'test', 'staging', 'beta', 'alpha', 'v1', 'v2', 'production', 'development']
    
    # Only remove if it's a known stage name (not 'api' or other resource paths)
    if first_part in common_stages and len(path_parts) > 1:
        # Reconstruct path without stage
        return '/' + '/'.join(path_parts[1:])
    else:
        # First part is part of the resource path, return as is
        return '/' + '/'.join(path_parts)

def extract_request_info(event):
    """Extract HTTP method and path from event, handling REST API v1 and HTTP API v2"""
    # Log full event structure for debugging FIRST
    print("=" * 80)
    print("DEBUG: Full event structure:")
    print(json.dumps(event, indent=2, default=str))
    print("=" * 80)
    
    request_context = event.get("requestContext", {})
    
    # Detect API type: HTTP API v2 has requestContext.http, REST API v1 has requestContext.httpMethod
    is_http_api_v2 = "http" in request_context
    
    http_method = ""
    path = ""
    resource_path = ""
    
    if is_http_api_v2:
        # HTTP API v2 format
        print("DEBUG: Detected HTTP API v2 format")
        http_context = request_context.get("http", {})
        http_method = http_context.get("method", "").upper()
        
        # HTTP API v2 uses rawPath for the actual path
        path = event.get("rawPath", "")
        
        # Also check routeKey which contains "METHOD /path"
        route_key = request_context.get("routeKey", "")
        if route_key:
            # routeKey format: "GET /api/orders" or "$default"
            parts = route_key.split(" ", 1)
            if len(parts) == 2 and not http_method:
                http_method = parts[0].upper()
            if len(parts) == 2 and not path:
                path = parts[1]
        
        # If routeKey is $default, it's a catch-all route - get path from pathParameters
        if route_key == "$default" or (not path and route_key):
            path_params = event.get("pathParameters", {})
            if path_params:
                # Check for proxy parameter
                proxy_path = path_params.get("proxy", "") or path_params.get("Proxy", "")
                if proxy_path:
                    path = "/" + proxy_path if not proxy_path.startswith("/") else proxy_path
        
        resource_path = route_key
        
    else:
        # REST API v1 format (standard Lambda proxy integration)
        print("DEBUG: Detected REST API v1 format")
        http_method = event.get("httpMethod", "").upper()
        path = event.get("path", "")
        resource_path = event.get("resource", "")
        
        # Fallback to requestContext for REST API
        if not http_method and request_context:
            http_method = request_context.get("httpMethod", "").upper()
        if not path and request_context:
            path = request_context.get("path", "")
    
    # Try pathParameters proxy (catch-all routes) - works for both API types
    if not path:
        path_params = event.get("pathParameters", {})
        if path_params:
            # Check for proxy parameter (used in catch-all routes like /{proxy+})
            proxy_path = path_params.get("proxy", "") or path_params.get("Proxy", "")
            if proxy_path:
                path = "/" + proxy_path if not proxy_path.startswith("/") else proxy_path
    
    # Final fallback: try to extract from the raw event structure
    if not path:
        for key in ["requestPath", "request_path", "route", "uri", "requestUri"]:
            if key in event:
                path = event[key]
                break
    
    # Normalize HTTP method
    if http_method:
        http_method = http_method.upper()
    
    print(f"DEBUG: Extracted - httpMethod='{http_method}', path='{path}', resource='{resource_path}'")
    print(f"DEBUG: API Type: {'HTTP API v2' if is_http_api_v2 else 'REST API v1'}")
    print(f"DEBUG: requestContext keys: {list(request_context.keys()) if request_context else 'None'}")
    
    return http_method, path, resource_path

def lambda_handler(event, context):
    """Main Lambda handler with routing logic"""
    try:
        # Extract request info (handles different integration types)
        http_method, path, resource_path = extract_request_info(event)
        
        # Handle CORS preflight
        if http_method == "OPTIONS":
            return handle_options()
        
        # If we still don't have httpMethod or path, try to work with what we have
        if not http_method or not path:
            # Last resort: check if this might be a direct Lambda invocation (for testing)
            # In that case, we can't route properly, but let's provide helpful error
            error_msg = {
                "error": "Cannot extract request information from event",
                "message": "Unable to determine HTTP method or path from the event. This might indicate:",
                "possibleCauses": [
                    "Lambda proxy integration is not enabled in API Gateway",
                    "Event is from a direct Lambda invocation (not through API Gateway)",
                    "API Gateway is using a non-standard integration type",
                    "Event structure is different than expected"
                ],
                "debug": {
                    "eventKeys": list(event.keys()),
                    "httpMethod": http_method or "NOT FOUND",
                    "path": path or "NOT FOUND",
                    "resource": resource_path or "NOT FOUND",
                    "hasRequestContext": "requestContext" in event,
                    "requestContextKeys": list(event.get("requestContext", {}).keys()) if event.get("requestContext") else [],
                    "hasPathParameters": "pathParameters" in event,
                    "pathParameters": event.get("pathParameters", {}),
                    "hasHeaders": "headers" in event,
                    "headerKeys": list(event.get("headers", {}).keys()) if event.get("headers") else []
                },
                "instructions": "Check CloudWatch logs for the full event structure above to diagnose the issue"
            }
            print(f"ERROR: {json.dumps(error_msg, indent=2, default=str)}")
            return get_cors_response(500, error_msg)
        
        # Normalize path to handle stage prefixes
        normalized_path = normalize_path(path)
        
        path_parameters = event.get("pathParameters") or {}
        query_string_parameters = event.get("queryStringParameters") or {}
        
        # Parse body
        body = {}
        if event.get("body"):
            try:
                body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
            except json.JSONDecodeError:
                pass
        
        # Use normalized path for routing
        route_path = normalized_path
        
        # Route requests
        # POST /api/orders - Create Order
        if http_method == "POST" and (route_path == "/api/orders" or route_path.endswith("/api/orders")):
            return create_order(body)
        
        # GET /api/orders - List Orders
        elif http_method == "GET" and (route_path == "/api/orders" or route_path.endswith("/api/orders")):
            return list_orders(query_string_parameters)
        
        # POST /api/orders/{orderId}/status - Update Order Status
        elif http_method == "POST" and ("/status" in route_path or route_path.endswith("/status")):
            order_id = path_parameters.get("orderId") or path_parameters.get("orderid")
            if not order_id:
                # Try to extract from path
                path_parts = route_path.split("/")
                if len(path_parts) >= 4 and path_parts[-1] == "status":
                    order_id = path_parts[-2]
            
            if not order_id:
                return get_cors_response(400, {"error": "Missing orderId in path"})
            
            return update_order_status(order_id, body)
        
        # GET /api/orders/{orderId} - View Order
        elif http_method == "GET" and ("/api/orders/" in route_path or route_path.startswith("/api/orders/")):
            order_id = path_parameters.get("orderId") or path_parameters.get("orderid")
            if not order_id:
                # Try to extract from path
                path_parts = route_path.split("/")
                # Path should be like: /api/orders/{orderId} or /prod/api/orders/{orderId}
                # Find the orderId part (after "orders")
                try:
                    orders_index = path_parts.index("orders")
                    if orders_index + 1 < len(path_parts):
                        order_id = path_parts[orders_index + 1]
                except ValueError:
                    # "orders" not in path, try last part
                    if len(path_parts) >= 2:
                        order_id = path_parts[-1]
            
            if not order_id:
                return get_cors_response(400, {"error": "Missing orderId in path"})
            
            return view_order(order_id)
        
        # PUT /api/orders/{orderId}/avatars - Update Order Avatars
        elif http_method == "PUT" and ("/avatars" in route_path or route_path.endswith("/avatars")):
            order_id = path_parameters.get("orderId") or path_parameters.get("orderid")
            if not order_id:
                # Try to extract from path
                path_parts = route_path.split("/")
                if len(path_parts) >= 4 and path_parts[-1] == "avatars":
                    order_id = path_parts[-2]
            
            if not order_id:
                return get_cors_response(400, {"error": "Missing orderId in path"})
            
            return update_order_avatars(order_id, body)
        
        # Unknown route
        else:
            # Return debug info in error response to help troubleshoot
            return get_cors_response(404, {
                "error": "Route not found",
                "message": f"No route handler for {http_method} {normalized_path}",
                "debug": {
                    "httpMethod": http_method,
                    "path": path,
                    "resource": resource_path,
                    "normalizedPath": normalized_path,
                    "routePath": route_path,
                    "pathParameters": path_parameters,
                    "queryParameters": query_string_parameters
                }
            })
    
    except Exception as e:
        print(f"Unhandled error in lambda_handler: {str(e)}")
        import traceback
        traceback.print_exc()
        return get_cors_response(500, {"error": "Internal server error"})


"""Lambda function: Update Order Status - POST /api/orders/{orderId}/status"""
import json
import os
import boto3
from decimal import Decimal
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))

# Table names
ORDERS_TABLE_NAME = os.environ.get('ORDERS_TABLE_NAME', 'Orders')

# Initialize tables
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)

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

def lambda_handler(event, context):
    """Update order status"""
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
        
        new_status = body.get("status")
        
        if not new_status:
            return get_cors_response(400, {"error": "Missing status"})
        
        if new_status not in ["active", "paid", "cancelled"]:
            return get_cors_response(400, {"error": "Invalid status. Must be 'active', 'paid', or 'cancelled'"})
        
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
        
        # Update the order using the primary key (id)
        updated_response = orders_table.update_item(
            Key=order_primary_key,
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW"
        )
        
        updated_order = updated_response.get("Attributes")
        
        # Convert Decimal objects to int/float for JSON serialization
        updated_order = convert_decimals(updated_order)
        
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
        import traceback
        traceback.print_exc()
        return get_cors_response(500, {"error": f"Failed to update order status: {str(e)}"})

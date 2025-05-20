import json
import os
import uuid
import boto3

# Initialize the Lambda client.
# AWS credentials will be handled by the Lambda execution role.
# Ensure the execution role has lambda:InvokeFunction permission for the target PRINT_LAMBDA_FUNCTION_NAME.
lambda_client = boto3.client('lambda')

def lambda_handler(event, context):
    print(f"Received event for batch overlay invocation: {json.dumps(event)}")

    # --- Configuration ---
    # Get from environment variables set in the Lambda configuration
    print_lambda_function_name = os.environ.get('PRINT_LAMBDA_FUNCTION_NAME')
    overlay_image_url = os.environ.get('OVERLAY_IMAGE_URL')

    if not print_lambda_function_name or not overlay_image_url:
        print("Error: Missing environment variables: PRINT_LAMBDA_FUNCTION_NAME or OVERLAY_IMAGE_URL")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*' # Adjust CORS as needed
            },
            'body': json.dumps({'error': 'Server configuration error: Missing required environment variables.'})
        }

    # --- Parse Request Body ---
    try:
        # API Gateway typically passes the body as a string
        if isinstance(event.get('body'), str):
            request_body = json.loads(event['body'])
        else:
            request_body = event.get('body', {}) # Fallback if body is already parsed (e.g. direct Lambda invoke)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in request body: {e}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': 'Invalid request body: Could not parse JSON.'})
        }

    avatars = request_body.get('avatars')

    if not isinstance(avatars, list) or not avatars:
        print("Error: Request body must contain a non-empty 'avatars' array.")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': "Request body must contain a non-empty 'avatars' array."})
        }

    initiated_count = 0
    failed_to_initiate_count = 0

    # --- Process Each Avatar ---
    for avatar in avatars:
        if not all(k in avatar for k in ('imageUrl', 'originalRequestId', 'filterId')):
            print(f"Warning: Skipping avatar due to missing details for async invocation: {avatar.get('filterId', 'Unknown filter')}")
            failed_to_initiate_count += 1
            continue

        # Generate a unique ID for this specific overlay job (can be passed to the print lambda)
        overlay_order_id = str(uuid.uuid4())

        # Payload for your existing image-overlay Lambda
        payload_for_print_lambda = {
            'imageUrl': avatar['imageUrl'],
            'overlayUrl': overlay_image_url,
            'orderId': overlay_order_id,       # This is the order ID for the overlay/print job
            'requestId': avatar['originalRequestId'] # This is the ID from the initial avatar generation
            # Add any other parameters your existing image-overlay Lambda expects
        }

        invoke_params = {
            'FunctionName': print_lambda_function_name,
            'InvocationType': 'Event',  # Crucial for asynchronous invocation
            'Payload': json.dumps(payload_for_print_lambda)
        }

        try:
            print(f"Attempting to invoke {print_lambda_function_name} for filter {avatar['filterId']} with overlay Order ID {overlay_order_id}")
            response = lambda_client.invoke(**invoke_params)

            # For 'Event' invocation, a successful request to AWS Lambda returns StatusCode 202.
            if response.get('StatusCode') == 202:
                print(f"Successfully initiated async overlay for {avatar['imageUrl']} (Overlay Order ID: {overlay_order_id})")
                initiated_count += 1
            else:
                # This case is less common for 'Event' type if the invocation request itself is malformed
                # before AWS even accepts it. More often, issues would be within the invoked Lambda.
                print(f"Failed to initiate async overlay for {avatar['imageUrl']}. AWS StatusCode: {response.get('StatusCode')}, Error: {response.get('FunctionError')}")
                failed_to_initiate_count += 1
        except Exception as e:
            print(f"Error initiating async overlay for {avatar['imageUrl']}: {str(e)}")
            failed_to_initiate_count += 1

    # --- Prepare Response ---
    response_message = f"Batch overlay processing initiated. Successful initiations: {initiated_count}. Failed initiations: {failed_to_initiate_count}."
    print(response_message)

    return {
        'statusCode': 200, # Or 202 "Accepted"
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*' # IMPORTANT: Configure CORS appropriately for your API Gateway
        },
        'body': json.dumps({
            'message': response_message,
            'initiatedCount': initiated_count,
            'failedToInitiateCount': failed_to_initiate_count
        })
    }

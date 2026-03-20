# Orders Microservices

This directory contains separate Lambda functions for each Orders API endpoint, following a microservices architecture.

## Structure

```
orders/
├── shared/
│   ├── __init__.py
│   └── utils.py          # Shared utilities (DynamoDB, CORS, helpers)
├── create-order/
│   └── lambda_function.py  # POST /api/orders
├── list-orders/
│   └── lambda_function.py  # GET /api/orders
├── get-order/
│   └── lambda_function.py  # GET /api/orders/{orderId}
├── update-order-status/
│   └── lambda_function.py  # POST /api/orders/{orderId}/status
└── update-order-avatars/
    └── lambda_function.py  # PUT /api/orders/{orderId}/avatars
```

## Lambda Functions

### 1. create-order
- **Endpoint**: `POST /api/orders`
- **Function**: Creates a new order
- **Deploy**: Deploy the `create-order` directory as a Lambda function

### 2. list-orders
- **Endpoint**: `GET /api/orders`
- **Function**: Lists orders for a date with optional status filter
- **Deploy**: Deploy the `list-orders` directory as a Lambda function

### 3. get-order
- **Endpoint**: `GET /api/orders/{orderId}`
- **Function**: Gets a single order with avatars and request details
- **Deploy**: Deploy the `get-order` directory as a Lambda function

### 4. update-order-status
- **Endpoint**: `POST /api/orders/{orderId}/status`
- **Function**: Updates order status
- **Deploy**: Deploy the `update-order-status` directory as a Lambda function

### 5. update-order-avatars
- **Endpoint**: `PUT /api/orders/{orderId}/avatars`
- **Function**: Updates order's avatar IDs
- **Deploy**: Deploy the `update-order-avatars` directory as a Lambda function

## Deployment

Each Lambda function is **completely independent** - just zip the single `lambda_function.py` file!

### Option 1: Simple Zip (Recommended)

**Windows (PowerShell):**
```powershell
# For each function
Compress-Archive -Path "create-order/lambda_function.py" -DestinationPath "create-order.zip" -Force
```

**Linux/Mac:**
```bash
# For each function
cd create-order
zip create-order.zip lambda_function.py
cd ..
```

### Option 2: Use Deployment Script

**Windows (PowerShell):**
```powershell
.\deploy.ps1
```

**Linux/Mac:**
```bash
chmod +x deploy.sh
./deploy.sh
```

The zip file structure is simple - just one file:

```
function.zip
└── lambda_function.py
```

**Windows (PowerShell):**
```powershell
# For each function (example: create-order)
$tempDir = New-TemporaryFile | ForEach-Object { Remove-Item $_; New-Item -ItemType Directory -Path $_ }
Copy-Item "create-order/lambda_function.py" -Destination "$tempDir/lambda_function.py"
Copy-Item -Path "shared" -Destination "$tempDir/shared" -Recurse
Compress-Archive -Path "$tempDir/*" -DestinationPath "create-order.zip" -Force
Remove-Item -Path $tempDir -Recurse -Force
```

**Linux/Mac:**
```bash
# For each function (example: create-order)
cd create-order
cp ../shared . -r
zip -r ../create-order.zip lambda_function.py shared/
cd ..
```

2. Upload to Lambda:
   - Go to Lambda Console
   - Create/Update function
   - Upload the zip file
   - Set handler: `lambda_function.lambda_handler`
   - Set runtime: Python 3.11

### Option 2: AWS SAM / Serverless Framework

Create a `template.yaml` or `serverless.yml` to deploy all functions at once.

### Option 3: AWS CLI

```bash
# For each function
aws lambda create-function \
  --function-name create-order \
  --runtime python3.11 \
  --role arn:aws:iam::ACCOUNT:role/lambda-execution-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip
```

## API Gateway Setup

For HTTP API v2, create routes:

- `POST /api/orders` → `create-order` Lambda
- `GET /api/orders` → `list-orders` Lambda
- `GET /api/orders/{orderId}` → `get-order` Lambda
- `POST /api/orders/{orderId}/status` → `update-order-status` Lambda
- `PUT /api/orders/{orderId}/avatars` → `update-order-avatars` Lambda

Each route should use **Lambda proxy integration**.

## Environment Variables

Set these for each Lambda function:

- `ORDERS_TABLE_NAME` (default: `Orders`)
- `AVATARS_TABLE_NAME` (default: `Avatars`)
- `REQUESTS_TABLE_NAME` (default: `Requests`)
- `ORDER_COUNTER_TABLE_NAME` (default: `OrderCounter`)
- `AWS_REGION` (default: `eu-central-1`)

## IAM Permissions

Each Lambda needs permissions for:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:BatchGetItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:REGION:ACCOUNT:table/Orders",
        "arn:aws:dynamodb:REGION:ACCOUNT:table/Orders/index/*",
        "arn:aws:dynamodb:REGION:ACCOUNT:table/Avatars",
        "arn:aws:dynamodb:REGION:ACCOUNT:table/Requests",
        "arn:aws:dynamodb:REGION:ACCOUNT:table/OrderCounter"
      ]
    }
  ]
}
```

## Benefits of Microservices Approach

✅ **Separation of Concerns**: Each function has a single responsibility  
✅ **Independent Deployment**: Deploy functions independently  
✅ **Better Scaling**: Scale each function based on its load  
✅ **Easier Testing**: Test each function in isolation  
✅ **Clearer Monitoring**: Monitor each endpoint separately  
✅ **Smaller Cold Starts**: Smaller functions = faster cold starts  

## Migration from Monolith

The original `lambda_function.py` (monolith approach) is kept for reference. You can delete it once all microservices are deployed and tested.


# Fix: Enable Lambda Proxy Integration

## Problem
You're getting empty `httpMethod` and `path` values, which means **Lambda Proxy Integration is not enabled** in API Gateway.

## Solution: Enable Lambda Proxy Integration

### Step 1: Go to API Gateway Console

1. Open AWS Console → API Gateway
2. Select your API (`db73fu70d6`)
3. Navigate to your resource (e.g., `/api/orders`)
4. Click on the **GET** method (or POST, PUT, etc.)

### Step 2: Check Integration Type

You should see:
- **Integration type**: `Lambda Function`
- **Use Lambda Proxy integration**: ✅ **CHECKED**

If "Use Lambda Proxy integration" is **NOT checked**, that's the problem!

### Step 3: Enable Proxy Integration

1. Click on the **Integration Request** section
2. Scroll down to find **"Use Lambda Proxy integration"**
3. **Check the box** ✅
4. Click **Save**
5. Click **OK** when prompted about permissions

### Step 4: Repeat for All Methods

Enable proxy integration for:
- ✅ `GET /api/orders`
- ✅ `POST /api/orders`
- ✅ `GET /api/orders/{orderId}`
- ✅ `POST /api/orders/{orderId}/status`
- ✅ `PUT /api/orders/{orderId}/avatars`
- ✅ `OPTIONS` methods (for CORS)

### Step 5: Redeploy API

1. Click **Actions** → **Deploy API**
2. Select your stage (or create one)
3. Click **Deploy**

## What Lambda Proxy Integration Does

When enabled, API Gateway passes the full request event to Lambda:
```json
{
  "httpMethod": "GET",
  "path": "/api/orders",
  "resource": "/api/orders",
  "headers": {...},
  "queryStringParameters": {...},
  "pathParameters": {...},
  "body": "..."
}
```

Without it, API Gateway uses a custom integration mapping and the event structure is different.

## Verify It's Working

After enabling proxy integration and redeploying:

1. Test your endpoint again
2. Check CloudWatch logs - you should see the full event structure
3. The Lambda should now receive `httpMethod` and `path` correctly

## Quick Test

```bash
curl https://db73fu70d6.execute-api.eu-central-1.amazonaws.com/api/orders
```

You should now get a proper response instead of the "Route not found" error.


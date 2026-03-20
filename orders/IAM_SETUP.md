# IAM Permissions Setup for Orders Lambda Functions

## Problem

You're getting `AccessDeniedException` because the Lambda execution role doesn't have DynamoDB permissions.

## Solution: Add IAM Policy to Lambda Execution Role

### Step 1: Find Your Lambda Execution Role

1. Go to AWS Lambda Console
2. Select your Lambda function (e.g., `create-order`)
3. Go to **Configuration** → **Permissions**
4. Note the **Execution role** name (e.g., `create-order-role-9upwkiua`)

### Step 2: Add DynamoDB Permissions

**Option A: Via AWS Console**

1. Go to **IAM Console** → **Roles**
2. Search for your execution role (e.g., `create-order-role-9upwkiua`)
3. Click on the role
4. Click **Add permissions** → **Create inline policy**
5. Click **JSON** tab
6. Paste the policy from `IAM_POLICY.json` (see below)
7. Click **Review policy**
8. Name it: `OrdersDynamoDBPolicy`
9. Click **Create policy**

**Option B: Via AWS CLI**

```bash
# Attach the policy to your role
aws iam put-role-policy \
  --role-name create-order-role-9upwkiua \
  --policy-name OrdersDynamoDBPolicy \
  --policy-document file://IAM_POLICY.json
```

### Step 3: Required Permissions

Each Lambda function needs these DynamoDB permissions:

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
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchGetItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:eu-central-1:598011222931:table/Orders",
        "arn:aws:dynamodb:eu-central-1:598011222931:table/Orders/index/*",
        "arn:aws:dynamodb:eu-central-1:598011222931:table/Avatars",
        "arn:aws:dynamodb:eu-central-1:598011222931:table/Requests",
        "arn:aws:dynamodb:eu-central-1:598011222931:table/OrderCounter"
      ]
    }
  ]
}
```

### Step 4: Apply to All Lambda Functions

You need to add this policy to **each Lambda function's execution role**:

- `create-order` - needs: `PutItem` (Orders, OrderCounter), `BatchGetItem` (Avatars)
- `list-orders` - needs: `Query` (Orders), `BatchGetItem` (Avatars)
- `get-order` - needs: `GetItem` (Orders, Requests), `BatchGetItem` (Avatars)
- `update-order-status` - needs: `GetItem`, `UpdateItem` (Orders)
- `update-order-avatars` - needs: `GetItem`, `UpdateItem` (Orders), `BatchGetItem` (Avatars)

**Easiest approach**: Use the policy above for all functions - it includes all necessary permissions.

### Step 5: Verify Permissions

After adding the policy, test your Lambda function again. The error should be resolved.

## Quick Fix Script (AWS CLI)

If you have AWS CLI configured, run this for each function:

```bash
# Replace ROLE_NAME with your actual role name
ROLE_NAME="create-order-role-9upwkiua"

aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name OrdersDynamoDBPolicy \
  --policy-document file://IAM_POLICY.json
```

## Troubleshooting

- **Still getting errors?** Wait a few seconds - IAM changes can take a moment to propagate
- **Wrong region?** Make sure the DynamoDB table ARNs match your region (eu-central-1)
- **Wrong account?** Verify the account ID (598011222931) matches your AWS account

## Alternative: Use AWS Managed Policy (Less Secure)

If you want a quick but less secure option, you can attach the AWS managed policy:

```
arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
```

**Warning**: This gives full DynamoDB access to all tables. The custom policy above is more secure (least privilege).


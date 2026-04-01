# LightX User Token Routing

This folder contains operational guidance to run LightX with per-user API keys.

## 1) Create DynamoDB table

Use AWS CLI:

```bash
aws dynamodb create-table ^
  --table-name LightxUserTokens ^
  --attribute-definitions AttributeName=userSub,AttributeType=S ^
  --key-schema AttributeName=userSub,KeyType=HASH ^
  --billing-mode PAY_PER_REQUEST
```

## 2) Seed tokens

Insert one item per Cognito user `sub`:

```bash
aws dynamodb put-item ^
  --table-name LightxUserTokens ^
  --item "{\"userSub\":{\"S\":\"03e438b2-6001-7079-75d2-876c1d7fbfc2\"},\"apiKey\":{\"S\":\"<LIGHTX_TOKEN_1>\"},\"label\":{\"S\":\"promoter-francisco\"},\"active\":{\"BOOL\":true},\"updatedAt\":{\"S\":\"2026-03-31T12:00:00Z\"}}"
```

Optional fallback key:

```bash
aws dynamodb put-item ^
  --table-name LightxUserTokens ^
  --item "{\"userSub\":{\"S\":\"default\"},\"apiKey\":{\"S\":\"<LIGHTX_DEFAULT_TOKEN>\"},\"label\":{\"S\":\"fallback-shared\"},\"active\":{\"BOOL\":true},\"updatedAt\":{\"S\":\"2026-03-31T12:00:00Z\"}}"
```

## 3) Lambda environment variables

Add to each LightX-calling Lambda:

- `LIGHTX_TOKENS_TABLE=LightxUserTokens`
- `REQUEST_TABLE_NAME=Requests`
- `AVATAR_TABLE_NAME=Avatars`

## 4) IAM permissions

Grant these permissions to each relevant Lambda role:

- `dynamodb:GetItem` on `LightxUserTokens`
- `dynamodb:GetItem` on `Requests`
- `dynamodb:GetItem` on `Avatars`

## 5) Verification

- Run two requests from different users.
- Confirm logs show different `userSub` resolving to different `label`.
- Confirm no full API key is logged.

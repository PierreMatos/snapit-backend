# Users Admin Microservices

Admin-only APIs for invite-only onboarding with Cognito.

## Endpoints

- `POST /api/admin/users` -> `create-user`
- `GET /api/admin/users` -> `list-users`

## Behavior

- `POST /api/admin/users`
  - Calls Cognito `AdminCreateUser` (invite email sent by Cognito)
  - Calls Cognito `AdminAddUserToGroup` (`admins`, `staff`, `capture`)
- `GET /api/admin/users`
  - Lists users with email, status, enabled flag, and groups

## Environment variables

Set in both Lambdas:

- `COGNITO_USER_POOL_ID` (required)
- `AWS_REGION` (default `eu-central-1`)

Optional in `create-user`:

- `DEFAULT_GROUP` (default `staff`)

## IAM permissions needed

- `cognito-idp:AdminCreateUser`
- `cognito-idp:AdminAddUserToGroup`
- `cognito-idp:ListUsers`
- `cognito-idp:AdminListGroupsForUser`

Scope to your user-pool ARN.

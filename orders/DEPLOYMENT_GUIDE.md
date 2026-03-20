# Deployment Guide - Fix "No module named 'shared'" Error

## The Problem

If you're getting `No module named 'shared'`, it means the `shared` folder is not included in your Lambda deployment package.

## Solution: Create Correct Zip File

### Step 1: Verify Your Current Zip Structure

**Windows (PowerShell):**
```powershell
# Check what's in your zip file
Expand-Archive -Path "create-order.zip" -DestinationPath "temp-check" -Force
Get-ChildItem -Path "temp-check" -Recurse
Remove-Item -Path "temp-check" -Recurse -Force
```

**Linux/Mac:**
```bash
unzip -l create-order.zip
```

The zip should contain:
```
lambda_function.py
shared/
  __init__.py
  utils.py
```

### Step 2: Create Correct Zip File

**Option A: Use the Deployment Script (Recommended)**

Run from the `orders` directory:

```powershell
# Windows
.\deploy.ps1
```

```bash
# Linux/Mac
chmod +x deploy.sh
./deploy.sh
```

This creates `create-order.zip` with the correct structure.

**Option B: Manual Creation (Windows PowerShell)**

```powershell
# Navigate to orders directory
cd orders

# Create temp directory
$tempDir = New-Item -ItemType Directory -Path "temp-package"

# Copy files
Copy-Item "create-order/lambda_function.py" -Destination "$tempDir/lambda_function.py"
Copy-Item -Path "shared" -Destination "$tempDir/shared" -Recurse

# Create zip
Compress-Archive -Path "$tempDir/*" -DestinationPath "create-order.zip" -Force

# Cleanup
Remove-Item -Path $tempDir -Recurse -Force

# Verify contents
Write-Host "Verifying zip contents:"
Expand-Archive -Path "create-order.zip" -DestinationPath "temp-check" -Force
Get-ChildItem -Path "temp-check" -Recurse | Select-Object FullName
Remove-Item -Path "temp-check" -Recurse -Force
```

**Option C: Manual Creation (Linux/Mac)**

```bash
# Navigate to orders directory
cd orders

# Create temp directory
mkdir temp-package

# Copy files
cp create-order/lambda_function.py temp-package/
cp -r shared temp-package/

# Create zip
cd temp-package
zip -r ../create-order.zip .
cd ..

# Cleanup
rm -rf temp-package

# Verify contents
unzip -l create-order.zip
```

### Step 3: Upload to Lambda

1. Go to AWS Lambda Console
2. Select your `create-order` function
3. Click "Upload from" → ".zip file"
4. Select `create-order.zip`
5. Click "Save"

### Step 4: Verify Handler

Make sure the handler is set to: `lambda_function.lambda_handler`

## Quick Test Script

Create a file `test-zip.ps1` to verify your zip structure:

```powershell
# test-zip.ps1
param([string]$zipFile = "create-order.zip")

Write-Host "Checking zip file: $zipFile" -ForegroundColor Yellow

if (-not (Test-Path $zipFile)) {
    Write-Host "ERROR: Zip file not found!" -ForegroundColor Red
    exit 1
}

# Extract to temp location
$tempDir = New-Item -ItemType Directory -Path "temp-zip-check"
Expand-Archive -Path $zipFile -DestinationPath $tempDir -Force

# Check structure
$hasLambda = Test-Path "$tempDir/lambda_function.py"
$hasShared = Test-Path "$tempDir/shared"
$hasUtils = Test-Path "$tempDir/shared/utils.py"

Write-Host ""
Write-Host "Zip Structure Check:" -ForegroundColor Cyan
Write-Host "  lambda_function.py: $(if ($hasLambda) { '✅' } else { '❌' })"
Write-Host "  shared/: $(if ($hasShared) { '✅' } else { '❌' })"
Write-Host "  shared/utils.py: $(if ($hasUtils) { '✅' } else { '❌' })"

if ($hasLambda -and $hasShared -and $hasUtils) {
    Write-Host ""
    Write-Host "✅ Zip structure is correct!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "❌ Zip structure is incorrect!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Contents:" -ForegroundColor Yellow
    Get-ChildItem -Path $tempDir -Recurse | Select-Object FullName
}

# Cleanup
Remove-Item -Path $tempDir -Recurse -Force
```

Run it:
```powershell
.\test-zip.ps1 create-order.zip
```

## Common Mistakes

1. **Zipping the wrong directory**: Don't zip the `create-order/` folder itself. Zip the contents (lambda_function.py + shared/)
2. **Missing shared folder**: Make sure `shared/` is copied into the zip
3. **Wrong zip structure**: The zip root should have `lambda_function.py` and `shared/` at the same level

## Still Having Issues?

If you're still getting the error after following these steps:

1. **Check CloudWatch Logs** - Look for import errors
2. **Verify Runtime** - Make sure it's Python 3.11 or 3.12 (not 3.14 which doesn't exist - might be a typo in your console)
3. **Test Locally** - Extract the zip and verify you can import:
   ```python
   from shared.utils import get_cors_response
   ```


# Deployment script for Orders microservices (PowerShell)
# Each function is independent - just zip the lambda_function.py file

$functions = @("create-order", "list-orders", "get-order", "update-order-status", "update-order-avatars")

foreach ($func in $functions) {
    Write-Host "Packaging $func..." -ForegroundColor Yellow
    
    # Create zip file with just lambda_function.py
    $zipPath = Join-Path $PSScriptRoot "${func}.zip"
    if (Test-Path $zipPath) {
        Remove-Item $zipPath
    }
    
    # Compress just the lambda_function.py file
    Compress-Archive -Path "$func/lambda_function.py" -DestinationPath $zipPath -Force
    
    Write-Host "✅ Created ${func}.zip" -ForegroundColor Green
}

Write-Host ""
Write-Host "Deployment packages created:" -ForegroundColor Green
foreach ($func in $functions) {
    Write-Host "  - ${func}.zip"
}
Write-Host ""
Write-Host "Upload these zip files to their respective Lambda functions." -ForegroundColor Cyan
Write-Host "Each zip contains only lambda_function.py - completely independent!" -ForegroundColor Green

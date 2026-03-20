#!/bin/bash

# Deployment script for Orders microservices
# Each function is independent - just zip the lambda_function.py file

set -e

FUNCTIONS=("create-order" "list-orders" "get-order" "update-order-status" "update-order-avatars")

for func in "${FUNCTIONS[@]}"; do
    echo "Packaging $func..."
    
    # Create zip file with just lambda_function.py
    cd "$func"
    zip -r "../${func}.zip" lambda_function.py > /dev/null
    cd ..
    
    echo "✅ Created ${func}.zip"
done

echo ""
echo "Deployment packages created:"
for func in "${FUNCTIONS[@]}"; do
    echo "  - ${func}.zip"
done
echo ""
echo "Upload these zip files to their respective Lambda functions."
echo "Each zip contains only lambda_function.py - completely independent!"

import https from 'https';
import sharp from 'sharp';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import http from 'http';
import qrcode from 'qrcode';
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";


const s3 = new S3Client({ region: 'eu-central-1' });
const dynamoDBClient = new DynamoDBClient({ region: 'eu-central-1' });
const docClient = DynamoDBDocumentClient.from(dynamoDBClient);
const avatarsTableName = 'Avatars'; // Define Avatars table name

const LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools";
const LIGHTX_HOST = "api.lightxeditor.com";

export const handler = async (event) => {
  let orderIdForFailure = null;

  try {
    const body = typeof event.body === 'string' ? JSON.parse(event.body) : event;

    const originalImageUrl = body.imageUrl; // Will be avatarUrl
    const overlayUrl = body.overlayUrl;
    const orderId = body.orderId;
    const requestId = body.requestId; // Added requestId
    orderIdForFailure = orderId || null;

    if (!originalImageUrl || !overlayUrl || !orderId || !requestId) {
      throw new Error("Missing imageUrl, overlayUrl, orderId, or requestId");
    }

    // Check if orderId already exists in Avatars table (as 'id')
    const getItemParams = {
      TableName: avatarsTableName,
      Key: { id: orderId },
    };
    console.log(`Checking for existing processed image for orderId (id): ${orderId}`);
    const { Item } = await docClient.send(new GetCommand(getItemParams));

    if (Item && Item.output_url) {
      // Ensure request linkage fields exist even on already-processed rows.
      await docClient.send(new UpdateCommand({
        TableName: avatarsTableName,
        Key: { id: orderId },
        UpdateExpression: "set request_id = :reqId, requestId = :reqId",
        ExpressionAttributeValues: {
          ":reqId": requestId
        },
        ReturnValues: "NONE"
      }));

      console.log(`Order ID ${orderId} has already been processed. Returning existing URL: ${Item.output_url}`);
      return {
        statusCode: 200,
        body: JSON.stringify({
          finalImageUrl: Item.output_url, // Return existing URL
        }),
        headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*" // Adjust CORS as needed
        }
      };
    }
    console.log(`No existing processed image found for orderId ${orderId}, proceeding with generation.`);

    // Step 1: Resize with LightX (expand-photo).
    // If LightX resize fails, continue using the original URL instead of aborting.
    let resizedUrl = originalImageUrl;
    try {
      resizedUrl = await expandWithLightX(originalImageUrl);
    } catch (expandError) {
      console.warn(`expandWithLightX failed for orderId ${orderId}. Falling back to original image URL.`, expandError);
    }

    // Step 2: Fetch avatar + overlay images
    const [avatarBuffer, overlayBuffer] = await Promise.all([
      fetchImage(resizedUrl),
      fetchImage(overlayUrl)
    ]);

    // Step 3a: Generate QR Code
    const qrCodeUrl = `https://www.snapitrabbit.com/avatars/${requestId}`;
    const qrCodeBuffer = await qrcode.toBuffer(qrCodeUrl, {
      errorCorrectionLevel: 'H', // High error correction
      type: 'png',
      margin: 1, // Minimal margin
      width: 200 // Initial width, will be resized based on the main image
    });

    // Step 3b: Resize overlay to avatar dimensions before compositing.
    const avatarMetadata = await sharp(avatarBuffer).metadata();
    const resizedOverlayBuffer = await sharp(overlayBuffer)
      .resize({
        width: avatarMetadata.width,
        height: avatarMetadata.height,
        fit: 'fill'
      })
      .toBuffer();

    // Composite overlay onto avatar first
    const avatarWithOverlayBuffer = await sharp(avatarBuffer)
      .composite([{ input: resizedOverlayBuffer, top: 0, left: 0 }])
      .toBuffer();

    // Step 3c: Composite QR code onto the avatar+overlay image
    const avatarWithOverlayMetadata = await sharp(avatarWithOverlayBuffer).metadata();
    const qrCodeSize = Math.floor(avatarWithOverlayMetadata.width * 0.15); // 15% of avatar+overlay width

    const qrCodeResizedBuffer = await sharp(qrCodeBuffer)
      .resize(qrCodeSize)
      .toBuffer();

    // Position QR code at bottom right of the avatar+overlay image (adjust padding as needed)
    const qrTop = avatarWithOverlayMetadata.height - qrCodeSize - Math.floor(avatarWithOverlayMetadata.height * 0.02); // 5% padding from bottom
    const qrLeft = avatarWithOverlayMetadata.width - qrCodeSize - Math.floor(avatarWithOverlayMetadata.width * 0.05);   // 5% padding from right

    const finalImageBuffer = await sharp(avatarWithOverlayBuffer)
      .composite([{ input: qrCodeResizedBuffer, top: qrTop, left: qrLeft }])
      .jpeg()
      .toBuffer();

    // Step 4: Upload to S3
    const bucketName = 'snapitbucket';
    const key = `prints/${orderId}.jpg`; // Updated S3 key
    const printFilename = `snapit_print_${orderId}.jpg`; // Desired filename for download

    await s3.send(new PutObjectCommand({
      Bucket: bucketName,
      Key: key,
      Body: finalImageBuffer,
      ContentType: 'image/jpeg',
      ContentDisposition: `attachment; filename="${printFilename}"`
    }));

    const s3Url = `https://${bucketName}.s3.eu-central-1.amazonaws.com/${key}`;

    // Store S3 URL in DynamoDB
    const updateItemParams = {
      TableName: avatarsTableName,
      Key: { id: orderId }, // orderId from input corresponds to 'id' in Avatars table
      UpdateExpression: "set output_url = :url, request_id = :reqId, requestId = :reqId", // store both snake_case and camelCase
      ExpressionAttributeValues: {
        ":url": s3Url,
        ":reqId": requestId,
      },
      ReturnValues: "UPDATED_NEW",
    };
    await docClient.send(new UpdateCommand(updateItemParams));

    return {
      statusCode: 200,
      body: JSON.stringify({
        finalImageUrl: s3Url // Updated response key
      }),
      headers: { // Ensure headers are also on the final success response
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*" // Adjust CORS as needed
      }
    };

  } catch (error) {
    console.error("Error:", error);
    if (orderIdForFailure) {
      await markOverlayFailure(orderIdForFailure, error.message);
    }
    return {
      statusCode: 500,
      body: JSON.stringify({
        message: 'Failed to process and upload image',
        error: error.message
      }),
      headers: { // Ensure headers are also on the error response
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*" // Adjust CORS as needed
      }
    };
  }
};

async function markOverlayFailure(orderId, errorMessage) {
  try {
    await docClient.send(new UpdateCommand({
      TableName: avatarsTableName,
      Key: { id: orderId },
      UpdateExpression: "set overlay_status = :status, overlay_error = :error",
      ExpressionAttributeValues: {
        ":status": "FAILED",
        ":error": String(errorMessage || "Unknown overlay error")
      },
      ReturnValues: "NONE"
    }));
    console.log(`Marked overlay failure for orderId ${orderId}`);
  } catch (updateError) {
    console.error(`Failed to mark overlay failure for orderId ${orderId}:`, updateError);
  }
}

// Resize image using LightX expand-photo
async function expandWithLightX(imageUrl) {
  const expandPayload = JSON.stringify({
    imageUrl,
    leftPadding: -12,
    rightPadding: -12,
    topPadding: 238,
    bottomPadding: 238
  });

  const expandResponse = await httpPost(LIGHTX_HOST, '/external/api/v1/expand-photo', expandPayload);
  const orderId = expandResponse.body.orderId;

  // Poll for result (max 5 tries)
  for (let attempt = 0; attempt < 5; attempt++) {
    await sleep(5000); // 15s delay
    const statusPayload = JSON.stringify({ "orderId": orderId });
    const statusResponse = await httpPost(LIGHTX_HOST, '/external/api/v1/order-status', statusPayload);
    const outputUrl = statusResponse.body?.output;
    if (outputUrl) return outputUrl;
  }

  throw new Error("Timed out waiting for LightX to return the resized image.");
}

// Make POST request to LightX
function httpPost(host, path, payload) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: host,
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': LIGHTX_API_KEY,
        'Content-Length': Buffer.byteLength(payload),
      }
    }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const response = JSON.parse(Buffer.concat(chunks).toString());
        resolve(response);
      });
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

// Helper to fetch image from URL
const fetchImage = (url) => {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    }).on('error', reject);
  });
};

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

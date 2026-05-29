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

const VARIANT_CONFIG = {
  default: { outputField: "output_url", keySuffix: "", filenamePrefix: "snapit_print_" },
  big: { outputField: "output_url_big", keySuffix: "_big", filenamePrefix: "snapit_big_print_" },
  noqr: { outputField: "output_url_noqr", keySuffix: "_noqr", filenamePrefix: "snapit_print_noqr_" },
};

function getVariantConfig(variant) {
  return VARIANT_CONFIG[variant] || VARIANT_CONFIG.default;
}

function getExistingOutputUrl(item, variant) {
  const config = getVariantConfig(variant);
  return item?.[config.outputField] || null;
}

export const handler = async (event) => {
  let orderIdForFailure = null;

  try {
    const body = typeof event.body === 'string' ? JSON.parse(event.body) : event;

    const originalImageUrl = body.imageUrl; // Will be avatarUrl
    const DEFAULT_OVERLAY_URL =
      process.env.DEFAULT_OVERLAY_URL ||
      "https://snapitbucket.s3.eu-central-1.amazonaws.com/assets/moldura%2Bcom%2Btransparencia.png";
    const overlayUrl =
      body.overlayUrl ??
      body["image-overlay"] ??
      DEFAULT_OVERLAY_URL;
    const overlaySource = body.overlayUrl
      ? "overlayUrl"
      : body["image-overlay"]
        ? "image-overlay"
        : "default";
    const orderId = body.orderId;
    const requestId = body.requestId; // Added requestId
    const includeQrCode = body.includeQrCode !== false && body.skipQrCode !== true;
    let effectiveVariant = String(body.printVariant || "default").toLowerCase();
    if (!includeQrCode && effectiveVariant === "default") {
      effectiveVariant = "noqr";
    }
    const variantConfig = getVariantConfig(effectiveVariant);
    orderIdForFailure = orderId || null;

    console.log(`Using overlay from: ${overlaySource}, includeQrCode: ${includeQrCode}, variant: ${effectiveVariant}`);

    if (!originalImageUrl || !orderId || !requestId) {
      throw new Error("Missing imageUrl, orderId, or requestId");
    }

    // Check if orderId already exists in Avatars table (as 'id')
    const getItemParams = {
      TableName: avatarsTableName,
      Key: { id: orderId },
    };
    console.log(`Checking for existing processed image for orderId (id): ${orderId}`);
    const { Item } = await docClient.send(new GetCommand(getItemParams));

    const existingOutputUrl = getExistingOutputUrl(Item, effectiveVariant);
    if (existingOutputUrl) {
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

      console.log(`Order ID ${orderId} has already been processed for variant ${effectiveVariant}. Returning existing URL: ${existingOutputUrl}`);
      return {
        statusCode: 200,
        body: JSON.stringify({
          finalImageUrl: existingOutputUrl, // Return existing URL
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
      resizedUrl = await expandWithLightX(originalImageUrl, body);
    } catch (expandError) {
      console.warn(`expandWithLightX failed for orderId ${orderId}. Falling back to original image URL.`, expandError);
    }

    // Step 2: Fetch avatar + overlay images
    const [avatarBuffer, overlayBuffer] = await Promise.all([
      fetchImage(resizedUrl),
      fetchImage(overlayUrl)
    ]);

    // Step 3: Composite overlay onto avatar; optionally add QR (default: yes, kiosk unchanged).
    const avatarMetadata = await sharp(avatarBuffer).metadata();
    const resizedOverlayBuffer = await sharp(overlayBuffer)
      .resize({
        width: avatarMetadata.width,
        height: avatarMetadata.height,
        fit: 'fill'
      })
      .toBuffer();

    const avatarWithOverlayBuffer = await sharp(avatarBuffer)
      .composite([{ input: resizedOverlayBuffer, top: 0, left: 0 }])
      .toBuffer();

    let finalImageBuffer;
    if (includeQrCode) {
      const qrCodeUrl = `https://www.snapitrabbit.com/avatars/${requestId}`;
      const qrCodeBuffer = await qrcode.toBuffer(qrCodeUrl, {
        errorCorrectionLevel: 'H',
        type: 'png',
        margin: 1,
        width: 200
      });

      const avatarWithOverlayMetadata = await sharp(avatarWithOverlayBuffer).metadata();
      const qrCodeSize = Math.floor(avatarWithOverlayMetadata.width * 0.15);
      const qrCodeResizedBuffer = await sharp(qrCodeBuffer)
        .resize(qrCodeSize)
        .toBuffer();
      const qrTop = avatarWithOverlayMetadata.height - qrCodeSize - Math.floor(avatarWithOverlayMetadata.height * 0.02);
      const qrLeft = avatarWithOverlayMetadata.width - qrCodeSize - Math.floor(avatarWithOverlayMetadata.width * 0.05);

      finalImageBuffer = await sharp(avatarWithOverlayBuffer)
        .composite([{ input: qrCodeResizedBuffer, top: qrTop, left: qrLeft }])
        .jpeg()
        .toBuffer();
    } else {
      console.log(`Skipping QR code for orderId ${orderId}`);
      finalImageBuffer = await sharp(avatarWithOverlayBuffer)
        .jpeg()
        .toBuffer();
    }

    // Step 4: Upload to S3
    const bucketName = 'snapitbucket';
    const key = `prints/${orderId}${variantConfig.keySuffix}.jpg`;
    const printFilename = `${variantConfig.filenamePrefix}${orderId}.jpg`;

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
      Key: { id: orderId },
      UpdateExpression: `set ${variantConfig.outputField} = :url, request_id = :reqId, requestId = :reqId`,
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
async function expandWithLightX(imageUrl, body = {}) {
  const expandProfile = String(body.expandProfile || "default").toLowerCase();
  const defaultPaddings =
    expandProfile === "big"
      ? { leftPadding: 0, rightPadding: 0, topPadding: 128, bottomPadding: 128 }
      : { leftPadding: -12, rightPadding: -12, topPadding: 238, bottomPadding: 238 };

  const expandPayload = JSON.stringify({
    imageUrl,
    leftPadding: body.leftPadding ?? defaultPaddings.leftPadding,
    rightPadding: body.rightPadding ?? defaultPaddings.rightPadding,
    topPadding: body.topPadding ?? defaultPaddings.topPadding,
    bottomPadding: body.bottomPadding ?? defaultPaddings.bottomPadding
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

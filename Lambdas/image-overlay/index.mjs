import https from 'https';
import sharp from 'sharp';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import http from 'http';


const s3 = new S3Client({ region: 'eu-central-1' });

const LIGHTX_API_KEY = "9243575a15d641da829c5acac13cf1a2_85db21be6e604aa19ed83b94e3ce3798_andoraitools";
const LIGHTX_HOST = "api.lightxeditor.com";

export const handler = async (event) => {
  try {
    const body = typeof event.body === 'string' ? JSON.parse(event.body) : event;

    const originalImageUrl = body.imageUrl;
    const overlayUrl = body.overlayUrl;
    const orderId = body.orderId

    if (!originalImageUrl || !overlayUrl) {
      throw new Error("Missing imageUrl or overlayUrl");
    }

    // Step 1: Resize with LightX (expand-photo)
    const resizedUrl = await expandWithLightX(originalImageUrl);

    // Step 2: Fetch avatar + overlay images
    const [avatarBuffer, overlayBuffer] = await Promise.all([
      fetchImage(resizedUrl),
      fetchImage(overlayUrl)
    ]);

    // Step 3: Composite overlay
    const finalImageBuffer = await sharp(avatarBuffer)
      .composite([{ input: overlayBuffer, top: 0, left: 0 }])
      .jpeg()
      .toBuffer();

    // Step 4: Upload to S3
    const bucketName = 'snapitbucket';
    const key = `outputs/final_${orderId}.jpg`;

    await s3.send(new PutObjectCommand({
      Bucket: bucketName,
      Key: key,
      Body: finalImageBuffer,
      ContentType: 'image/jpeg',
    }));

    const s3Url = `https://${bucketName}.s3.eu-central-1.amazonaws.com/${key}`;

    return {
      statusCode: 200,
      body: JSON.stringify({
        orderId: orderId,
        image_url: s3Url
      }),
    };

  } catch (error) {
    console.error("Error:", error);
    return {
      statusCode: 500,
      body: JSON.stringify({
        message: 'Failed to process and upload image',
        error: error.message
      }),
    };
  }
};

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

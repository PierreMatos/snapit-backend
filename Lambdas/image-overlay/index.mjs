import https from 'https';
import sharp from 'sharp';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';

const s3 = new S3Client({ region: 'eu-central-1' });

export const handler = async (event) => {
  try {
    const body = typeof event.body === 'string' ? JSON.parse(event.body) : event;

    const avatarUrl = body.imageUrl;
    const overlayUrl = body.overlayUrl;
    const orderId = body.orderId || 'unknown';

    const bucketName = 'snapitbucket';
    const folder = 'outputs';
    const key = `${folder}/final_${orderId}.jpg`;


    
      if (!avatarUrl || !overlayUrl) {
      throw new Error("Missing avatarUrl or overlayUrl");
    }
    
    // Fetch both images
    const [avatarBuffer, overlayBuffer] = await Promise.all([
      fetchImage(avatarUrl),
      fetchImage(overlayUrl)
    ]);

    // Composite overlay and resize
    const finalImageBuffer = await sharp(avatarBuffer)
      .composite([{ input: overlayBuffer, top: 0, left: 0 }])
      .resize(1000, 1500)
      .jpeg()
      .toBuffer();

    // Upload to S3
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
    console.error('Error:', error);
    return {
      statusCode: 500,
      body: JSON.stringify({ message: 'Failed to process and upload image', error: error.message }),
    };
  }
};

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

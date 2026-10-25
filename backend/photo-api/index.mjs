// Lambda Node.js 24.x 入口：只读 Query，没有写入、扫描或文件转发。
import { DynamoDBClient, QueryCommand } from '@aws-sdk/client-dynamodb';
import { createHandler } from './core.mjs';

const client = new DynamoDBClient({});
const tableName = process.env.PHOTO_TABLE;
const albumId = process.env.PHOTO_ALBUM || 'main';

function fromDynamo(item) {
  const strings = ['id', 'previewKey', 'originalKey', 'filename', 'sha256'];
  return {
    ...Object.fromEntries(strings.map(key => [key, item[key]?.S])),
    sizeBytes: Number(item.sizeBytes?.N),
    title: Object.fromEntries(['ja', 'zh', 'en'].map(lang => [lang, item.title?.M?.[lang]?.S]))
  };
}

export const handler = createHandler({
  albumId,
  async queryPage({ partition, after, limit }) {
    if (!tableName) throw new Error('PHOTO_TABLE_NOT_CONFIGURED');
    const result = await client.send(new QueryCommand({
      TableName: tableName,
      KeyConditionExpression: '#pk = :album AND begins_with(#sk, :photo)',
      ExpressionAttributeNames: { '#pk': 'PK', '#sk': 'SK', '#id': 'id', '#preview': 'previewKey', '#original': 'originalKey',
        '#file': 'filename', '#bytes': 'sizeBytes', '#hash': 'sha256', '#title': 'title' },
      ExpressionAttributeValues: { ':album': { S: partition }, ':photo': { S: 'PHOTO#' } },
      ProjectionExpression: '#id, #preview, #original, #file, #bytes, #hash, #title',
      Limit: limit,
      ExclusiveStartKey: after ? { PK: { S: after.PK }, SK: { S: after.SK } } : undefined
    }));
    return {
      items: (result.Items || []).map(fromDynamo),
      lastKey: result.LastEvaluatedKey ? { PK: result.LastEvaluatedKey.PK.S, SK: result.LastEvaluatedKey.SK.S } : null
    };
  }
});

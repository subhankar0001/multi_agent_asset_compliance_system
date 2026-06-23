# Disaster Recovery & Business Continuity Plan

This runbook outlines the Recovery Time Objective (RTO) and Recovery Point Objective (RPO) targets, as well as the backup and failover procedures for the Asset Compliance AI system.

## 1. Objectives

| Metric | Target | Description |
|---|---|---|
| **RTO** | 4 Hours | Time from declared disaster to fully restored API availability in a secondary region. |
| **RPO** | 1 Hour | Maximum acceptable data loss threshold (documents/vectors ingested within the last hour). |

## 2. Component Backup Strategies

### S3 (Asset Documents & Images)
- **Primary Region:** `us-east-1`
- **Versioning:** Enabled by default. Deleted or overwritten objects are retained as non-current versions for 90 days.
- **Replication (Optional/Future):** Cross-Region Replication (CRR) to `us-west-2` can be enabled on the bucket for strict geographic redundancy.

### DynamoDB (Audit Idempotency)
- **Point-in-Time Recovery (PITR):** Enabled. The `AuditRunsTable` is continuously backed up to allow restoration to any second in the preceding 35 days.
- **Procedure:** In the AWS Console, navigate to DynamoDB -> Backups -> Restore to point-in-time. Choose the target restoration time.

### Pinecone (Vector Store)
- **Pinecone Backups:** Serverless Pinecone indices are automatically backed up.
- **Export Strategy:** Since Pinecone does not provide a direct snapshot download, we recommend scheduling an AWS EventBridge job to trigger a daily script that uses `index.fetch()` or the Pinecone export API to backup vectors to an S3 bucket in Parquet format.
- **Restoration:** If the index is destroyed, vectors are re-upserted from the daily S3 Parquet export. Alternatively, if original source documents exist in S3, a full re-ingestion can be performed (which takes significantly longer).

## 3. Multi-Region Failover Strategy

The Asset Compliance AI microservice is fully serverless. In the event of a total region failure (e.g., `us-east-1` goes down):

1. **Deploy Stack in Secondary Region:**
   ```bash
   export AWS_DEFAULT_REGION=us-west-2
   sam deploy --stack-name asset-compliance-dr --resolve-s3
   ```
2. **SSM Parameter Store Replication:** Ensure all API keys (Pinecone, LLM providers, etc.) are pre-provisioned in the secondary region's Parameter Store.
3. **Traffic Routing:** Update the Django orchestrator's environment variables to point the Lambda Function URLs (Ingest, Audit, Chat) to the newly deployed `us-west-2` ARNs.
4. **Data Consistency:** The new region will have a fresh DynamoDB table. Idempotency checks for historical audits will be lost, meaning in-flight audits may be re-run, but no data corruption will occur. Pinecone is a global service, so as long as the Pinecone region remains available, the vector index does not need to be restored.

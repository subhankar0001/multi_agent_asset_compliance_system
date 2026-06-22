# ruff: noqa: N803, N818
"""
Local offline mock clients to emulate AWS S3, AWS DynamoDB, and Pinecone.

Allows full local development and testing without any AWS or Pinecone credentials.
Uses a SQLite backend for DynamoDB and Pinecone emulations, and the local filesystem
under `.local_storage/s3/` for S3 emulation.
"""

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

# ── S3 Mock Client ────────────────────────────────────────────────────────────


class LocalS3Client:
    """Offline emulation of the boto3 S3 client using the local filesystem."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def put_object(self, Bucket: str, Key: str, Body: Any) -> dict[str, Any]:
        """Write object bytes to a local file."""
        file_path = self.storage_dir / Bucket / Key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(Body, bytes):
            data = Body
        elif hasattr(Body, "read"):
            data = Body.read()
        else:
            data = str(Body).encode("utf-8")
        file_path.write_bytes(data)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        """Read object bytes from a local file. Raises NoSuchKey ClientError if missing."""
        file_path = self.storage_dir / Bucket / Key
        if not file_path.is_file():
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "NoSuchKey",
                        "Message": f"The specified key '{Key}' does not exist in bucket '{Bucket}'.",
                    }
                },
                operation_name="GetObject",
            )
        data = file_path.read_bytes()
        return {"Body": io.BytesIO(data), "ResponseMetadata": {"HTTPStatusCode": 200}}

    def generate_presigned_url(
        self, ClientMethod: str, Params: dict[str, Any], ExpiresIn: int = 3600
    ) -> str:
        """Return a local file URI representing the presigned URL."""
        bucket = str(Params.get("Bucket", ""))
        key = str(Params.get("Key", ""))
        file_path = (self.storage_dir / bucket / key).resolve()
        return file_path.as_uri()


# ── DynamoDB Mock Client ──────────────────────────────────────────────────────


class ConditionalCheckFailedException(Exception):
    """Exception raised when a DynamoDB put_item condition check fails."""

    pass


class LocalDynamoDBExceptions:
    """Wrapper class to emulate boto3's client exceptions namespace."""

    ConditionalCheckFailedException = ConditionalCheckFailedException


class LocalDynamoDBClient:
    """Offline emulation of the boto3 DynamoDB client using a SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.exceptions = LocalDynamoDBExceptions
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database structure for audit run tracking."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_runs (
                    run_id TEXT PRIMARY KEY,
                    asset_id TEXT,
                    status TEXT,
                    verdict TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    expires_at INTEGER,
                    error_message TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_runs_asset_id ON audit_runs(asset_id)"
            )

    def put_item(
        self, TableName: str, Item: dict[str, Any], ConditionExpression: str | None = None
    ) -> dict[str, Any]:
        """Insert or replace an audit run item, checking for unique run_id if requested."""
        run_id = Item["run_id"]["S"]
        asset_id = Item["asset_id"]["S"]
        status = Item["status"]["S"]
        created_at = Item["created_at"]["S"]
        updated_at = Item["updated_at"]["S"]
        expires_at = int(Item["expires_at"]["N"])

        with sqlite3.connect(self.db_path) as conn:
            if ConditionExpression and "attribute_not_exists" in ConditionExpression:
                cursor = conn.execute("SELECT 1 FROM audit_runs WHERE run_id = ?", (run_id,))
                if cursor.fetchone():
                    raise ConditionalCheckFailedException(
                        f"ConditionalCheckFailed: Item with run_id '{run_id}' already exists."
                    )

            conn.execute(
                """
                INSERT OR REPLACE INTO audit_runs (run_id, asset_id, status, created_at, updated_at, expires_at, verdict, error_message)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (run_id, asset_id, status, created_at, updated_at, expires_at),
            )
        return {}

    def get_item(
        self, TableName: str, Key: dict[str, Any], ConsistentRead: bool = False
    ) -> dict[str, Any]:
        """Fetch an audit run item by run_id."""
        run_id = Key["run_id"]["S"]
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM audit_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()

        if not row:
            return {}

        item: dict[str, Any] = {
            "run_id": {"S": row["run_id"]},
            "asset_id": {"S": row["asset_id"]},
            "status": {"S": row["status"]},
            "created_at": {"S": row["created_at"]},
            "updated_at": {"S": row["updated_at"]},
            "expires_at": {"N": str(row["expires_at"])},
        }
        if row["verdict"] is not None:
            item["verdict"] = {"S": row["verdict"]}
        if row["error_message"] is not None:
            item["error_message"] = {"S": row["error_message"]}

        return {"Item": item}

    def update_item(
        self,
        TableName: str,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update fields on an existing audit run item."""
        run_id = Key["run_id"]["S"]

        status: str | None = None
        verdict: str | None = None
        error_message: str | None = None
        updated_at: str | None = None

        if ExpressionAttributeValues:
            if ":s" in ExpressionAttributeValues:
                status = ExpressionAttributeValues[":s"]["S"]
            if ":v" in ExpressionAttributeValues:
                verdict = ExpressionAttributeValues[":v"]["S"]
            if ":e" in ExpressionAttributeValues:
                error_message = ExpressionAttributeValues[":e"]["S"]
            if ":u" in ExpressionAttributeValues:
                updated_at = ExpressionAttributeValues[":u"]["S"]

        updates = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if verdict is not None:
            updates.append("verdict = ?")
            params.append(verdict)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if updated_at is not None:
            updates.append("updated_at = ?")
            params.append(updated_at)

        if not updates:
            return {}

        params.append(run_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE audit_runs SET {', '.join(updates)} WHERE run_id = ?",  # noqa: S608
                params,
            )
        return {}

    def query(
        self,
        TableName: str,
        IndexName: str | None = None,
        KeyConditionExpression: str | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        ProjectionExpression: str | None = None,
        ExpressionAttributeNames: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Query audit runs by asset_id using the emulated AssetIdIndex GSI."""
        asset_id = ""
        if ExpressionAttributeValues and ":aid" in ExpressionAttributeValues:
            asset_id = ExpressionAttributeValues[":aid"]["S"]

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM audit_runs WHERE asset_id = ?", (asset_id,))
            rows = cursor.fetchall()

        items = []
        for row in rows:
            item: dict[str, Any] = {
                "run_id": {"S": row["run_id"]},
                "asset_id": {"S": row["asset_id"]},
                "status": {"S": row["status"]},
                "created_at": {"S": row["created_at"]},
                "updated_at": {"S": row["updated_at"]},
                "expires_at": {"N": str(row["expires_at"])},
            }
            if row["verdict"] is not None:
                item["verdict"] = {"S": row["verdict"]}
            if row["error_message"] is not None:
                item["error_message"] = {"S": row["error_message"]}
            items.append(item)

        return {"Items": items}


# ── Pinecone Mock Client ──────────────────────────────────────────────────────


class NamespaceStats:
    """Simulates a namespace statistics object returned by describe_index_stats."""

    def __init__(self, vector_count: int) -> None:
        self.vector_count = vector_count


class IndexStats:
    """Simulates the index statistics returned by describe_index_stats."""

    def __init__(self, namespaces: dict[str, NamespaceStats]) -> None:
        self.namespaces = namespaces


class PineconeMatch:
    """Simulates a single query match returned by the Pinecone index query."""

    def __init__(self, id: str, score: float, metadata: dict[str, Any] | None = None) -> None:
        self.id = id
        self.score = score
        self.metadata = metadata


class QueryResponse:
    """Simulates the query response containing a list of matches."""

    def __init__(self, matches: list[PineconeMatch]) -> None:
        self.matches = matches


class LocalPineconeIndex:
    """Offline emulation of the Pinecone Index client using Qdrant client."""

    def __init__(self, db_path: Path, embedding_dimensions: int) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_dimensions = embedding_dimensions
        self.client = QdrantClient(path=str(self.db_path))

    def upsert(self, vectors: list[dict[str, Any]], namespace: str) -> dict[str, Any]:
        """Upsert a list of vectors with their metadata into the Qdrant collection."""
        if not self.client.collection_exists(collection_name=namespace):
            self.client.create_collection(
                collection_name=namespace,
                vectors_config=VectorParams(
                    size=self.embedding_dimensions, distance=Distance.COSINE
                ),
            )

        points = []
        for vec in vectors:
            vec_id = vec["id"]
            values = vec["values"]
            metadata = vec.get("metadata", {})

            # Convert custom string ID to valid Qdrant UUID
            hashed_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, vec_id))
            payload = {"_original_id": vec_id, **metadata}

            points.append(
                PointStruct(
                    id=hashed_id,
                    vector=values,
                    payload=payload,
                )
            )

        self.client.upsert(collection_name=namespace, points=points)
        return {"upserted_count": len(vectors)}

    def delete(
        self,
        ids: list[str] | None = None,
        delete_all: bool | None = None,
        namespace: str | None = None,
        filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete vectors by ID, namespace, or metadata filters."""
        if not namespace or not self.client.collection_exists(collection_name=namespace):
            return {}

        if delete_all:
            self.client.delete_collection(collection_name=namespace)
        elif ids:
            hashed_ids: list[Any] = [str(uuid.uuid5(uuid.NAMESPACE_DNS, val)) for val in ids]
            self.client.delete(
                collection_name=namespace,
                points_selector=PointIdsList(points=hashed_ids),
            )
        elif filter:
            qdrant_filter = self._translate_filter(filter)
            if qdrant_filter:
                self.client.delete(
                    collection_name=namespace,
                    points_selector=FilterSelector(filter=qdrant_filter),
                )
        return {}

    def query(
        self,
        vector: list[float],
        top_k: int,
        namespace: str,
        include_metadata: bool = False,
        filter: dict[str, Any] | None = None,
    ) -> QueryResponse:
        """Query vectors within a namespace, applying filters and retrieving from Qdrant."""
        if not self.client.collection_exists(collection_name=namespace):
            return QueryResponse(matches=[])

        qdrant_filter = self._translate_filter(filter)
        search_results = self.client.query_points(
            collection_name=namespace,
            query=vector,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=True,
        )

        matches = []
        for hit in search_results.points:
            payload = hit.payload or {}
            original_id = payload.get("_original_id")
            original_id_str = str(original_id) if original_id is not None else str(hit.id)

            metadata = {}
            if include_metadata:
                metadata = {k: v for k, v in payload.items() if k != "_original_id"}

            matches.append(
                PineconeMatch(
                    id=original_id_str,
                    score=float(hit.score),
                    metadata=metadata,
                )
            )
        return QueryResponse(matches=matches)

    def describe_index_stats(self) -> IndexStats:
        """Return counts of vectors grouped by namespace (collection)."""
        collections_resp = self.client.get_collections()
        namespaces = {}
        for col in collections_resp.collections:
            col_info = self.client.get_collection(collection_name=col.name)
            namespaces[col.name] = NamespaceStats(vector_count=col_info.points_count or 0)
        return IndexStats(namespaces=namespaces)

    def _translate_filter(self, pinecone_filter: dict[str, Any] | None) -> Filter | None:
        """Translate a Pinecone filter dict into a Qdrant Filter object."""
        if not pinecone_filter:
            return None

        must_conditions: list[Any] = []
        for key, cond in pinecone_filter.items():
            if isinstance(cond, dict) and "$eq" in cond:
                val = cond["$eq"]
            else:
                val = cond

            must_conditions.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=val),
                )
            )
        return Filter(must=must_conditions)

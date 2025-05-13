import chromadb
import uuid
from chromadb.utils import embedding_functions
from chromadb.config import Settings
from typing import Any, Optional, Dict, List, Literal


# helper functions
def get_metadata_format(collection_name: Literal["emojis", "personality", "users", "examples"]):
    if collection_name == "emojis":
        return {"name": "", "sentiment": ""}
    elif collection_name == "personality":
        return {"type": "", "attribute": ""}
    elif collection_name == "users":
        return {"user_id": 0, "created_at": 0}
    elif collection_name == "examples":
        return {"type": ""}


def generate_unique_id() -> int:
    # Generate a UUID, use only the lowest 50 bits
    return uuid.uuid4().int & ((1 << 50) - 1)


class RagDatabase:
    def __init__(self, db_path: str, embedding_model: Optional[str] = "all-MiniLM-L6-v2"):
        self.db_path = db_path
        self.client = chromadb.PersistentClient(db_path, settings=Settings(anonymized_telemetry=False))
        if embedding_model:
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )
        else:
            self.embedding_function = None
        self.collection_configuration = {
            "hnsw": {
                "space": "cosine",
            },
        }
        self.collections = [c.name for c in self.client.list_collections()]
        # print(
        #    self.client.get_collection("emojis", embedding_function=self.embedding_function).get(include=["documents"])
        # )

    def change_embedding_function(self, collection_name: str, new_embedding_func: str):
        documents, metadatas, ids = self.delete_collection(collection_name)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=new_embedding_func
        )
        #  print("reinserting:", documents)
        self.create_collection(collection_name)
        if documents:
            self.insert_data(collection_name, documents, metadatas, ids=ids)

    def delete_collection(self, collection_name: str):
        # dump collection first
        collection = self.client.get_collection(name=collection_name, embedding_function=self.embedding_function)
        result = collection.get(include=["documents", "metadatas"])

        documents = result["documents"]  # List[str]
        metadatas = result["metadatas"]  # List[dict]
        ids = result["ids"]

        self.client.delete_collection(collection_name)
        return documents, metadatas, ids

    def create_collection(self, collection_name: str):
        self.client.create_collection(
            name=collection_name,
            configuration=self.collection_configuration,
            embedding_function=self.embedding_function,
        )
        self.collections.append(collection_name)

    def insert_data(
        self,
        collection_name: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
    ):
        if ids is None:
            ids = [f"{generate_unique_id()}" for _ in range(len(documents))]
        collection = self.client.get_collection(collection_name, embedding_function=self.embedding_function)
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

    def delete_data(self, collection_name: str, where: Dict[str, Any]):
        collection = self.client.get_collection(collection_name, embedding_function=self.embedding_function)
        collection.delete(where=where)

    def get_data(
        self,
        query: str,
        collection_name: str,
        top_k: int = 10,
        min_similarity: float = 0.5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, str]] = None,
    ) -> Dict[str, List]:
        collection = self.client.get_collection(name=collection_name, embedding_function=self.embedding_function)
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
            where=where,
            where_document=where_document,
        )
        metadatas = results["metadatas"][0]
        documents = results["documents"][0]
        distances = results["distances"][0]
        # import json

        # print("rag response:")
        # print(json.dumps({doc: dist for doc, dist in zip(documents, distances)}, indent=4))
        idxs = [i for i in range(len(distances)) if distances[i] > min_similarity]

        return {
            "documents": [documents[i] for i in range(len(distances)) if i in idxs],
            "metadatas": [metadatas[i] for i in range(len(metadatas)) if i in idxs],
        }

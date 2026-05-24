import os
from typing import List
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import FlashrankRerank
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2", encode_kwargs = {"normalize_embeddings": True})
vector_store = Chroma(embedding_function=embeddings, persist_directory="./chroma_db")
all_document: List[Document] = []

def process_document(file_path: str, tenant_id: int) -> str:
    """load pdf, chunk it and save to chromadb"""
    global all_document
    if file_path.endswith(".pdf"):
        loader = PyPDFLoader(file_path)
    else:
        return "Unsupported file type"
    docs = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    chunks = text_splitter.split_documents(docs)

    source_filename = os.path.basename(file_path)
    for chunk in chunks:
        chunk.metadata["tenant_id"] = tenant_id
        chunk.metadata["source_file"] = source_filename

    vector_store.add_documents(documents=chunks)
    all_document.extend(chunks)
    return f"Processed {len(chunks)} chunks from '{source_filename}' for tenant {tenant_id}."

def retrieve_context(query: str, tenant_id: int, k:int = 3) -> str:
    """search the db based on query"""
    docs = vector_store.similarity_search(query, k=k*2, filter={"tenant_id": tenant_id})

    tenant_docs = [doc for doc in all_document if doc.metadata.get("tenant_id") == tenant_id]
    if tenant_docs:
        bm25_retriever = BM25Retriever.from_documents(tenant_docs)
        bm25_retriever.k = k*2
        bm25_docs = bm25_retriever.invoke(query)
    else:
        bm25_docs = []

    seen_contents = set()
    merged_docs = []
    for doc in docs + bm25_docs:
        fingerprint = doc.page_content[:100]
        if fingerprint not in seen_contents:
            seen_contents.add(fingerprint)
            merged_docs.append(doc)
    if not merged_docs:
        return "No relevant information found in the business knowledge base."

    try:
        compressor = FlashrankRerank(top_n = k)
        temp_retriever = BM25Retriever.from_documents(merged_docs)
        temp_retriever.k = len(merged_docs)
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=temp_retriever
        )
        final_docs = compression_retriever.invoke(query)
    except Exception:
        final_docs = merged_docs[:k]

    formatted_chunks = []
    for i, doc in enumerate(final_docs, 1):
        source = doc.metadata.get("source_file", "uploaded document")
        page = doc.metadata.get("page", "?")
        formatted_chunks.append(f"[Chunk {i} | Source: {source} | Page: {page}]\n{doc.page_content}")
    return "\n\n---\n\n".join(formatted_chunks)
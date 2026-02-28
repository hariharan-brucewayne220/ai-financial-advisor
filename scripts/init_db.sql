-- AI Financial Advisor Database Schema
-- Includes pgvector extension for semantic search and HNSW indexing

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- ADVISORS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS advisors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_advisors_email ON advisors(email);

-- ============================================================================
-- CLIENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    advisor_id UUID NOT NULL REFERENCES advisors(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    risk_profile VARCHAR(50) NOT NULL DEFAULT 'moderate', -- low, moderate, high, aggressive
    portfolio_value DECIMAL(20, 2),
    custom_metadata JSONB DEFAULT '{}',  -- custom fields, notes, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_clients_advisor_id ON clients(advisor_id);
CREATE INDEX idx_clients_email ON clients(email);

-- ============================================================================
-- DOCUMENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL, -- pdf, csv, xlsx, txt
    s3_key VARCHAR(1024) NOT NULL,  -- path in S3
    file_size_bytes BIGINT,
    status VARCHAR(50) DEFAULT 'pending', -- pending, processing, indexed, failed
    error_message TEXT,
    pii_detected BOOLEAN DEFAULT FALSE,
    pii_entities JSONB DEFAULT '[]',  -- [{type: 'PERSON', value: 'John Doe', start: 10, end: 19}, ...]
    chunk_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_documents_client_id ON documents(client_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_created_at ON documents(created_at DESC);

-- ============================================================================
-- DOCUMENT_CHUNKS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_length INTEGER,
    embedding VECTOR(1536),  -- text-embedding-3-small
    bm25_tokens TEXT[],      -- tokenized for BM25 search
    chunk_metadata JSONB DEFAULT '{}',  -- page numbers, section titles, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX idx_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);  -- HNSW for faster vector search
CREATE INDEX idx_document_chunks_bm25_tokens ON document_chunks USING gin (bm25_tokens);

-- ============================================================================
-- CONVERSATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    title VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_conversations_client_id ON conversations(client_id);

-- ============================================================================
-- MESSAGES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- user, assistant
    content TEXT NOT NULL,
    retrieved_chunk_ids UUID[] DEFAULT '{}',  -- which chunks were used for retrieval
    faithfulness_score NUMERIC(5, 4),  -- 0.0000 - 1.0000, NLI entailment score
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX idx_messages_created_at ON messages(created_at DESC);

-- ============================================================================
-- REPORTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    report_type VARCHAR(100) NOT NULL, -- portfolio_summary, risk_assessment, client_email
    title VARCHAR(255),
    content TEXT,  -- markdown content
    content_html TEXT,  -- rendered HTML for display
    status VARCHAR(50) DEFAULT 'draft', -- draft, final, archived
    generation_metadata JSONB DEFAULT '{}',  -- agent steps, iteration count, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finalized_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX idx_reports_client_id ON reports(client_id);
CREATE INDEX idx_reports_status ON reports(status);
CREATE INDEX idx_reports_created_at ON reports(created_at DESC);

-- ============================================================================
-- AUDIT_LOGS TABLE
-- ============================================================================
-- Append-only audit trail for compliance (never delete from this table)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    advisor_id UUID NOT NULL REFERENCES advisors(id) ON DELETE RESTRICT,
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    action VARCHAR(100) NOT NULL, -- query_answered, report_generated, document_uploaded
    prompt_text TEXT,
    response_text TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms INTEGER,
    model_used VARCHAR(100), -- gpt-4o, text-embedding-3-small, etc.
    doc_ids_retrieved UUID[] DEFAULT '{}',  -- which documents were used
    retrieval_method VARCHAR(50), -- hybrid, dense, bm25
    faithfulness_score NUMERIC(5, 4),
    compression_ratio NUMERIC(5, 4),  -- (original_tokens - compressed_tokens) / original_tokens
    cost_usd NUMERIC(12, 6),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_logs_advisor_id ON audit_logs(advisor_id);
CREATE INDEX idx_audit_logs_client_id ON audit_logs(client_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Advisor token usage aggregation
CREATE OR REPLACE VIEW advisor_token_usage AS
SELECT
    advisor_id,
    DATE_TRUNC('day', created_at) as day,
    SUM(input_tokens) as input_tokens,
    SUM(output_tokens) as output_tokens,
    SUM(total_tokens) as total_tokens,
    SUM(cost_usd) as cost_usd,
    COUNT(*) as request_count,
    AVG(latency_ms) as avg_latency_ms,
    MAX(latency_ms) as max_latency_ms
FROM audit_logs
GROUP BY advisor_id, DATE_TRUNC('day', created_at)
ORDER BY day DESC;

-- Document indexing progress per client
CREATE OR REPLACE VIEW document_status_summary AS
SELECT
    client_id,
    COUNT(*) as total_documents,
    SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) as indexed_count,
    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing_count,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
    SUM(CASE WHEN pii_detected THEN 1 ELSE 0 END) as with_pii_count,
    SUM(chunk_count) as total_chunks
FROM documents
GROUP BY client_id;

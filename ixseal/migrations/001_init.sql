-- IXseal 초기 스키마

CREATE TABLE templates (
    id             uuid PRIMARY KEY,
    name           text NOT NULL,
    description    text NOT NULL DEFAULT '',
    default_title  text NOT NULL DEFAULT '',
    default_expiry text NOT NULL,
    default_policy text NOT NULL,
    sections       jsonb NOT NULL,              -- 비밀 값 없음 (평문)
    sort_order     int NOT NULL DEFAULT 0,
    used_count     int NOT NULL DEFAULT 0,
    updated_by     text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    archived_at    timestamptz
);

CREATE TABLE secrets (
    id               uuid PRIMARY KEY,
    token_hash       bytea NOT NULL UNIQUE,     -- SHA-256(링크 토큰)
    title            text NOT NULL,             -- 고객 안내 화면에 노출
    customer_name    text NOT NULL,
    ticket_ref       text NOT NULL DEFAULT '',
    owner_name       text NOT NULL,             -- 담당 엔지니어 (자유 입력)
    template_id      uuid REFERENCES templates(id) ON DELETE SET NULL,
    template_name    text NOT NULL DEFAULT '',
    recipient_emails text[] NOT NULL DEFAULT '{}',  -- 알림 확장용 (v1 미사용)
    policy           text NOT NULL CHECK (policy IN ('unlimited', 'until_confirmed', 'one_time')),
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'consumed', 'purged')),
    purge_reason     text CHECK (purge_reason IN ('expired', 'one_time', 'customer_confirmed', 'revoked')),
    payload          bytea,                     -- AES-GCM(DEK, 내용 JSON). 폐기 시 NULL
    dek_wrapped      bytea,                     -- AES-GCM(KEK, DEK). 폐기 시 NULL
    kek_id           smallint,
    section_count    int NOT NULL DEFAULT 0,
    field_count      int NOT NULL DEFAULT 0,
    file_count       int NOT NULL DEFAULT 0,
    created_ip       inet,
    created_at       timestamptz NOT NULL DEFAULT now(),
    expires_at       timestamptz NOT NULL,
    view_count       int NOT NULL DEFAULT 0,
    first_viewed_at  timestamptz,
    last_viewed_at   timestamptz,
    consumed_at      timestamptz,
    purged_at        timestamptz
);
CREATE INDEX secrets_created_idx ON secrets (created_at DESC);
CREATE INDEX secrets_live_idx ON secrets (expires_at) WHERE status <> 'purged';

CREATE TABLE secret_files (                     -- 폐기 시 행 삭제
    id         uuid PRIMARY KEY,
    secret_id  uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    position   int NOT NULL,
    size_bytes int NOT NULL,
    blob       bytea NOT NULL                   -- AES-GCM(DEK, 파일명 || 내용)
);
CREATE INDEX secret_files_secret_idx ON secret_files (secret_id);

CREATE TABLE reveal_sessions (                  -- [보기] 후 파일 받기·폐기에 쓰는 짧은 세션
    id_hash    bytea PRIMARY KEY,
    secret_id  uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL
);
CREATE INDEX reveal_sessions_exp_idx ON reveal_sessions (expires_at);

CREATE TABLE access_logs (
    id          bigserial PRIMARY KEY,
    secret_id   uuid REFERENCES secrets(id) ON DELETE CASCADE,
    template_id uuid,
    event       text NOT NULL,
    actor       text NOT NULL,                  -- customer | admin:<담당자> | system
    detail      text NOT NULL DEFAULT '',
    ip          inet,
    user_agent  text,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX access_logs_secret_idx ON access_logs (secret_id, at DESC);
CREATE INDEX access_logs_at_idx ON access_logs (at);

# Durable publication receipts

Publication is separate from local generation success. After local persistence,
`finalize_generation_with_media_sync` adds `meta["publication"]` with `status` and
`last_error`, reports `PUBLICATION=<status>` on stderr, and preserves the final
stdout line `FILENAME=... PROMPT=... SEED=...`. Upload failure does not change the
successful generation exit path or remove local artifacts.

## Intent and states

- Neither `MEDIA_API_URL` nor `MEDIA_API_TOKEN_FILE` present: `disabled`; no receipt
  is required. Presence of either variable, even empty, expresses publication intent.
- Intent with missing, unreadable, invalid UTF-8 or empty token file, or missing
  URL/token-file setting or invalid API base URL: `config_error`. The generation payload and assets are
  persisted before returning; attempts remain zero until a network attempt.
  API base URLs require HTTPS; HTTP is accepted for `localhost`, `127.0.0.1` and
  `[::1]` development integrations. Userinfo, query strings, fragments, invalid
  schemes/ports and whitespace/control characters are rejected before HTTP.
- Usable configuration: a pending receipt is persisted before the first network
  operation. Successful upload IDs are saved individually.
- `completed`: every asset uploaded and generation run accepted.
- `pending`: transient/network failure or unexpected finalization error.
- `failed`: permanent HTTP validation/auth/not-found error (400/401/403/404/422).
- `conflict`: HTTP 409 or incompatible metadata reused with the same run key.

An unavailable `media_client` import reports `config_error` explicitly without
failing local generation. Import or filesystem failures cannot guarantee a durable
receipt; unexpected finalization diagnostics explicitly tell callers to inspect
receipt persistence before retrying.

## Payload and recovery

Receipts retain schema version 1 with an additive optional `generation` object.
It stores the complete generation publication payload, recursively sanitized:
credential-bearing keys are redacted; explicit authorization values, standalone
bearer credentials, identifiable JWTs, signed URLs, URL userinfo and labeled secret
assignments in strings are removed. Ordinary prose containing “bearer” or “token”,
tokenizer settings and token counts are preserved. Ordinary prompts, parameters,
provider metadata, lineage references, timestamps and costs remain available.
Known token-count fields are preserved. Secret-bearing prompt text is redacted,
not exempted from sanitization. Do not put unlabeled arbitrary secrets in metadata.

`sync_if_enabled` loads an existing receipt by run key instead of recreating it.
It preserves upload IDs, timestamps, attempts and idempotency keys. Completed,
conflict and failed receipts are no-ops on ordinary reentry. Incompatible assets
or generation payloads raise `ReceiptConflictError` and leave the original receipt
unchanged; the finalizer reports that conflict separately.

`media_sync.py retry --workspace <workspace>` retries `pending` and `config_error`
receipts, using stored generation payloads first. Fix configuration and retry; no
provider generation is needed. Older receipts without a generation payload retain
the existing log/assets reconstruction fallback. A retry attempt that does not
complete is included in the command's sanitized errors (nonzero CLI exit), not
reported as successful publication. Completed/conflict/failed remain excluded from
bulk retry; explicitly diagnosed failed receipts can still use `sync_receipt`.

No worker, new provider, generation executor, automatic backoff or uncertain
provider-request recovery is included. Concurrent writers to one receipt are not
serialized; callers must serialize the same run key. Asset contents are not hashed
by this layer, so do not mutate a local asset in place between attempts.

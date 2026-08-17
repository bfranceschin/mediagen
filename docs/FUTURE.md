# Future features

Ideas that are real xAI/Imagine capabilities but are **not** in the current
mediagen CLI. Do not implement from this file without an explicit plan and
approval.

## Reference-to-video (`grok-imagine-video-1.5`)

**What it is:** one or more still images *influence* a generated clip (subject,
style, product) without becoming frame 0.

That is different from image-to-video, which mediagen already models:

| Mode | Role of `--inputs` |
|------|--------------------|
| Image-to-video (shipped / planned for Grok) | The photo **is** the first frame. |
| Reference-to-video (this doc) | The photos **guide** the clip; the model invents the opening frame. |

xAI also allows preset voices on this path (`reference_audios` / `voice_id`,
max 3). Resolution is capped at 720p.

**Why it is not in the first Grok cut:** mediagen treats video `--inputs` as
`start_frame` (and `--end-image` as `end_frame`) for logs, receipts, and
Hostkit Media lineage. Reusing `--inputs` for “references” would change that
contract. A later design needs a new flag (e.g. `--refs`) and a new Media
input role — it is not a drop-in on the existing i2v path.

**When to reopen:** someone actually wants “keep this face/product, invent the
shot” rather than “animate this still.”

## Explicitly not planned

These Imagine APIs exist, but mediagen will not grow them unless the input
model changes:

- **Video edit** — rewrite an existing clip from a text prompt.
- **Video extend** — continue a clip from its last frame.

Both require a still-valid Imagine result URL (`vidgen.x.ai/...`), not an
arbitrary local `videos/raw/*.mp4`. That does not fit the local-file /
`FILENAME=` contract.

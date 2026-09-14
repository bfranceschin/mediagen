# mediagen image upscale — proposta v1

> **Status:** proposta. Não implementar até aprovação explícita.
> **For Hermes:** Use subagent-driven-development only after Bernardo aprovar o recorte v1.

**Goal:** Adicionar um modo **opt-in** de upscale de imagem na mediagen, só via fal.ai, sem ligar isso automaticamente após generate/edit.

**Architecture:** Novo `--model seedvr` (alias `--model upscale`). Mesmo CLI, mesmo `FILENAME=` / logs / receipts. Upload local → `fal-ai/seedvr/upscale/image` → PNG no workspace. GPT Image e Grok Imagine **não** entram: não têm endpoint de super-resolução.

**Tech Stack:** Python existente (`scripts/mediagen.py` + `fal_client.subscribe`), testes em `tests/test_unit.py`, docs `SKILL.md` / `README.md`. Repo canônico: `/home/bfranceschin/projects/mediagen`.

---

## 1. O que é upscale (e o que não é)

**Upscale / super-resolução:** a imagem de entrada é o objeto. O modelo aumenta largura×altura e tenta reconstruir detalhe **sem mudar a cena**. Analogia: ampliar uma foto no laboratório, não pedir outra foto.

**Edit de gerador (flux2/nano2/gpt/grok):** o modelo **redesenha**. Prompt tipo “deixe em 4K” costuma mudar cara, texto, composição. Analogia: pedir para um pintor copiar o quadro maior — ele inventa pinceladas.

Queremos o primeiro. Por isso **não** reaproveitar `--model nano2 --inputs foto.png --prompt "upscale"`.

**Nunca auto-upscale.** Generate continua barato. Upscale só quando o usuário pedir. A skill já documenta o custo-armadilha do tool nativo do Hermes.

---

## 2. GPT Image 2 — não faz upscale

Superfície oficial: **generate** e **edit**. Não existe endpoint / parâmetro `upscale`.[9][10]

O caminho Codex da mediagen (`gptimage2`) ainda mapeia para três tamanhos fixos: `1024×1024`, `1536×1024`, `1024×1536`. Edit com a foto + “aumente a resolução” é **redraw**, não SR.

A API paga do `gpt-image-2` aceita milhares de resoluções, mas continua sendo generate/edit, cobrado em tokens de imagem.[9]

**Decisão:** fora do v1. Não fingir upscale via `gptimage2` edit.

---

## 3. Grok Imagine (`grokimage2`) — não faz upscale

Superfície oficial: generate + edit. Resolução só `1k` ou `2k`. Sem fator 2×/4×, sem upscaler.[11][12]

Edit em `2k` redesenha. A mediagen já mapeia lado longo ≥1536 → `2k` no generate/edit — isso **não** é upscale de um arquivo existente.

**Decisão:** fora do v1. Workaround já existe: gerar/editar em 2k. Documentar na skill que “upscale Grok” = mentira; usar `seedvr` no PNG local.

---

## 4. Fal.ai — escolha do modelo

Custo aproximado para **2× de 1280×720** (~3,7 MP de saída):

| Modelo no fal | Endpoint | Custo ~2× 720p | Fator | Controles | Nota |
|---|---|---|---|---|---|
| **SeedVR2 (recomendado v1)** | `fal-ai/seedvr/upscale/image` | **~$0,004** ($0,001/MP) | 1–10× ou alvo 720p–2160p | seed, noise, png/jpg/webp | Barato, comercial, schema simples.[1] |
| Topaz Precision (Standard V2) | `topaz/upscale/image/precision` | ~$0,012 ($0,08 / 24 MP) | 1–4× | face enhance, sharpen… | Fiel ao pixel; catálogo Topaz é grande.[5][6][7] |
| Recraft Crisp | `fal-ai/recraft/upscale/crisp` | $0,004 **fixo** | sem fator | quase nenhum | Barato, mas PNG-in e sem 2×/4× explícito.[8] |
| Crystal (retrato) | `clarityai/crystal-upscaler` | ~$0,059 ($0,016/MP) | 1–200× | creativity | Especialista em cara, não generalista.[3] |
| Clarity (Hermes nativo hoje) | `fal-ai/clarity-upscaler` | ~$0,11 ($0,03/MP) | default 2 | prompt, denoise, resemblance | É o que o `image_generate` nativo usa (`UPSCALER_MODEL`).[4] |
| Flux Vision | `fal-ai/flux-vision-upscaler` | **~$0,37** ($0,10/MP) | 1–4× | creativity, VLM caption | O que a skill mediagen ainda cita. 10–100× mais caro que SeedVR.[2] |

Ranking do próprio fal (ago/2026): Topaz generative / precision / Recraft no topo; SeedVR2 Seamless tem o **menor $/MP** e o único modo “target resolution”.[5]

**Por que SeedVR2 no v1, não Flux Vision nem Clarity:**

1. Mesmo job (aumentar um PNG local) por ~1% do preço do Flux Vision.
2. Schema curto: `image_url` + `upscale_factor` ou `target_resolution`. Encaixa no CLI atual.
3. Fator até 10× e alvos 1080p/1440p/2160p — o caso Telegram → print.
4. Evita copiar a armadilha de $0,10/MP que a skill já alerta.
5. YAGNI: um endpoint. Topaz/Crystal/Flux Vision ficam em `docs/FUTURE.md`.

**Não** usar Flux Vision só porque o Hermes nativo “já usava”. O nativo **já mudou** para Clarity; a skill mediagen está desatualizada.

---

## 5. Contrato CLI (v1)

```bash
PYTHON=~/.hermes/hermes-agent/venv/bin/python
SCRIPT=scripts/mediagen.py   # no repo; na skill: ~/.hermes/skills/media/mediagen/scripts/mediagen.py

$PYTHON $SCRIPT \
  --model seedvr \
  --inputs /path/to/image.png \
  [--upscale-factor 2] \
  [--resolution 1080p|1440p|2160p] \
  [--seed 42]
```

`--model upscale` é **alias** de `seedvr`.

Regras:

- `--inputs` obrigatório, **exatamente 1** arquivo.
- `--prompt` **opcional** neste modelo. Se omitido: `PROMPT=upscale` no contrato stdout (não quebrar `FILENAME=… PROMPT=… SEED=…`).
- Default: `upscale_mode=factor`, `upscale_factor=2`, `output_format=png`.
- Se `--resolution` for um de `1080p|1440p|2160p`: `upscale_mode=target` (720p rejeitado — não faz sentido “upscalear para menor”).
- `--upscale-factor` fora do default **e** `--resolution` alvo → `ERROR=…` (os dois modos são mutuamente exclusivos).
- Rejeitar: `--width/--height` (não-default), `--steps`, `--quality`, `--enable-web-search`, `--end-image`, `--camera-fixed`, `--no-audio`, `--duration`, `--aspect-ratio`.
- Seed opcional, como flux2.

Stdout sucesso:

```
FILENAME=20260914_142000_seedvr_upscale.png PROMPT=upscale SEED=42
```

Arquivo: `images/raw/<YYYYMMDD>_<HHMMSS>_seedvr_upscale.png`  
Log JSON: mesmo stem.  
Endpoint gravado: `fal-ai/seedvr/upscale/image`.  
Timeout: 300s (4× 4K pode passar de 120s).  
Safety checker: SeedVR não expõe o campo; não inventar.

Resposta Telegram (skill):

```
✅ Image upscaled
File: …
Model: seedvr
Factor: 2  (ou Target: 2160p)
Seed: …
MEDIA:~/.hermes/workspace/mediagen/images/raw/<file>
```

**Não** encadear upscale depois de flux2/nano2.

---

## 6. Media / Hostkit

Novo `operation: "upscale"`. Input role: `upscale_source` (não reciclar `edit_source` — lineage diferente).

Se a API Media rejeitar operação/role novos: fallback documentado `operation=edit` + `role=edit_source` **só** se o contrato live for fechado. Verificar no código Media / testes de schema **antes** de inventar role. Pendência de implementação, não de produto.

---

## 7. Arquivos

Repo: `/home/bfranceschin/projects/mediagen`

- Modify: `scripts/mediagen.py` (constantes, argparse, `validate_args`, `build_seedvr_args`, dispatch, filename, media payload)
- Modify: `tests/test_unit.py` (payload + validação; zero chamada fal)
- Modify: `tests/test_mediagen_media_sync.py` (role `upscale_source`)
- Modify: `SKILL.md`, `README.md`
- Modify: `docs/FUTURE.md` (Topaz / Crystal / Flux Vision / GPT-Grok “falso upscale”)
- Create: `references/seedvr-upscale.md` (schema, preço, falhas)

Depois do merge: copiar para `~/.hermes/skills/media/mediagen/` (default) e `~/.hermes/profiles/coder/skills/media/mediagen/` — hoje as duas cópias da skill estão iguais e **não** são o git working tree.

---

## 8. Implementação (depois do ok)

Ordem TDD no repo. Python dos testes: o que o README/pytest do repo já usa.

### Task 1 — constantes e `build_seedvr_args`

**Teste (red):** `tests/test_unit.py` classe `TestBuildSeedvrArgs`

- factor default 2, `output_format=png`, sem seed se None
- seed presente
- `upscale_mode=target` + `target_resolution=2160p` quando resolution setada
- não incluir `prompt` no payload fal

**Code:**

```python
UPSCALE_MODELS = {"seedvr", "upscale"}
SEEDVR_ENDPOINT = "fal-ai/seedvr/upscale/image"
SEEDVR_TARGET_RESOLUTIONS = {"1080p", "1440p", "2160p"}

def build_seedvr_args(args) -> dict:
    payload = {
        "image_url": args.image_urls[0],
        "output_format": "png",
    }
    if getattr(args, "resolution", "720p") in SEEDVR_TARGET_RESOLUTIONS:
        payload["upscale_mode"] = "target"
        payload["target_resolution"] = args.resolution
    else:
        payload["upscale_mode"] = "factor"
        payload["upscale_factor"] = getattr(args, "upscale_factor", 2)
    if args.seed is not None:
        payload["seed"] = args.seed
    return payload
```

### Task 2 — `validate_args` para upscale

- exatamente 1 input
- factor 1–10
- resolução só default 720p **ou** alvo SeedVR
- conflito factor≠2 + resolution alvo
- flags de outro modo → ERROR=
- `--prompt` pode faltar

`--prompt` deixa de ser `required=True` no argparse; `validate_args` exige prompt para todos **exceto** `UPSCALE_MODELS`.

### Task 3 — dispatch / filename / stdout

- `normalize_model`: `upscale` → `seedvr` para filename/log
- stem `*_seedvr_upscale.png`
- `PROMPT=upscale` se vazio
- upload via `upload_file(path)` (já existe; **não** `upload(file_handle)`)
- parse `result["image"]["url"]` (não `images[]`)

### Task 4 — Media sync

`mode == "upscale"` → `operation=upscale`, input `role=upscale_source`. Teste no `test_mediagen_media_sync.py`.

### Task 5 — docs

SKILL: novo bloco Image Upscale; tabela de modelos; pitfall “não auto-upscale”; corrigir a linha que ainda diz que o nativo usa Flux Vision (hoje é Clarity). README + `references/seedvr-upscale.md`. FUTURE: outros upscalers fal.

### Task 6 — verificação

```bash
cd /home/bfranceschin/projects/mediagen
# suite unitária existente; esperado: pass, incluindo os novos
python -m pytest tests/test_unit.py tests/test_mediagen_media_sync.py -q
```

Smoke real (só com ok do Bernardo, gasta ~$0,004):

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model seedvr \
  --inputs ~/.hermes/workspace/mediagen/images/raw/<algum.png>
```

Não commit/push neste plano até o ok.

---

## 9. Fora de escopo (v1)

- Auto-upscale pós-generate
- GPT / Grok como upscaler
- Topaz / Crystal / Flux Vision / Recraft no CLI
- Upscale de vídeo
- `--creativity` / `noise_scale` (default do SeedVR 0.1 basta)
- Mudar `image_gen.provider` do Hermes

---

## 10. Decisões para o Bernardo

1. **Default SeedVR2?** (recomendado) vs Clarity (paridade com nativo) vs Topaz Precision (fiel, ~3× SeedVR) vs Flux Vision (caro, não).
2. Alias `--model upscale` além de `seedvr`? (recomendado: sim)
3. `--resolution 1080p|1440p|2160p` como modo target? (recomendado: sim)
4. Media role novo `upscale_source` vs reusar `edit_source`?

---

## Sources

- [1] https://fal.ai/models/fal-ai/seedvr/upscale/image/llms.txt
- [2] https://fal.ai/models/fal-ai/flux-vision-upscaler/llms.txt
- [3] https://fal.ai/models/clarityai/crystal-upscaler/llms.txt
- [4] https://fal.ai/models/fal-ai/clarity-upscaler/api
- [5] https://fal.ai/learn/tools/image-to-image-upscalers
- [6] https://fal.ai/docs/model-api-reference/image-generation-api/topaz-upscale
- [7] https://fal.ai/topaz
- [8] https://fal.ai/models/fal-ai/recraft/upscale/crisp/llms.txt
- [9] https://developers.openai.com/api/docs/guides/image-generation
- [10] https://developers.openai.com/api/docs/models/gpt-image-2
- [11] https://docs.x.ai/developers/model-capabilities/imagine
- [12] https://docs.x.ai/developers/model-capabilities/images/generation.md

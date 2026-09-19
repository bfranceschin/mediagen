# mediagen edit — manter aspect ratio — proposta v1

> **Status:** aprovado e implementado (v1).
> **For Hermes:** Já no código; não reabrir o recorte sem pedido novo.

**Goal:** Em **edit de imagem**, se ninguém pediu outro formato, o mediagen manda o tamanho/proporção da foto de entrada — não o default 1280×720.

**Architecture:** `--width`/`--height` passam a `None` quando omitidos. Generate continua 1280×720. Edit lê o primeiro `--inputs`. Os `build_*_args` atuais não mudam de contrato: recebem `args.width`/`args.height` já resolvidos. A skill ensina o agente a passar flags só quando o usuário pedir outro formato. O CLI **não** interpreta o texto do prompt.

**Tech Stack:** Python existente (`scripts/mediagen.py`), testes em `tests/test_unit.py` (zero chamada de API). Repo: `/home/bfranceschin/projects/mediagen`. Depois do merge, copiar skill para as duas cópias Hermes.

---

## 1. O que deu errado (caso real)

**Aspect ratio** = largura ÷ altura. Analogia: o formato da moldura, não o tamanho da impressão.

1. Bernardo mandou uma pintura **1024×1280** (retrato **4:5**).
2. Pediu um edit de cor (tirar o filtro amarelado). Não pediu paisagem, 16:9, nem recorte.
3. mediagen chamou `grokimage2` com o default do CLI: `--width 1280 --height 720` → API `aspect_ratio=16:9`.
4. Saiu `med_90kN9bPgFRWRxFGoqIwIp` em **1280×720**. A composição mudou porque a moldura mudou.

Falha: o CLI tratou “não falei de tamanho” como “quero 16:9”.
Impacto: todo edit sem flags vira widescreen, mesmo se a fonte for retrato.
Solução: omitir flags no edit = herdar a fonte.

---

## 2. Recorte v1 (e o que fica de fora)

**Dentro:**

- Modelos de imagem: `flux2`, `nano2`, `gptimage2`, `grokimage2`.
- Só modo **edit** (`--inputs` presente).
- Herdar o **primeiro** arquivo de `--inputs` (o `edit_source` posição 0).
- Pedido explícito de outro formato = flags `--width` **e** `--height` juntos.
- Skill: se o usuário pedir 16:9 / paisagem / quadrado / 9:16 / etc., o agente **passa as flags**. O script não lê português no prompt.

**Fora (YAGNI):**

- Generate (sem `--inputs`) continua 1280×720.
- Upscale (`seedvr`) já trabalha na imagem de entrada; não herdar WxH.
- Vídeo / image-to-video (`seedance2`, `grokvideo`) — default 16:9 é bug parecido, mas não é este pedido.
- NLP do prompt (“deixa widescreen”) dentro do Python.
- Escolher entre vários `--inputs` de razões diferentes: sempre o primeiro.

---

## 3. O que cada backend consegue de verdade

Herança **não** é pixel-perfect. O script manda o WxH da fonte; cada API arredonda.

| Modelo | O que o script manda hoje | Com herança 1024×1280 (4:5) | Limite |
|--------|---------------------------|-----------------------------|--------|
| flux2 | `image_size: {w,h}` | `{1024, 1280}` | fal pode ajustar uns pixels (já acontece em 1280×720 → 1280×736) |
| nano2 | `aspect_ratio` via mdc | `4:5` | razões raras podem arredondar no fal |
| grokimage2 | nearest da lista fechada | **3:4** (vizinho; 4:5 não existe) | lista: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 19.5:9… |
| gptimage2 | 3 caixas | **portrait** `1024×1536` | só landscape / square / portrait |

No caso do Grok da pintura: 3:4 ainda é retrato. Muito melhor que 16:9. Documentar isso na skill — não vender 4:5 exato no Grok.

`resolution` 1k/2k do Grok continua a regra atual: lado longo ≥1536 → 2k. Fonte 1024×1280 → **1k**.

---

## 4. Contrato CLI

Defaults de argparse:

```text
--width   default None   (hoje 1280)
--height  default None   (hoje 720)
```

Resolução **depois** de `validate_args`, **antes** de `build_*_args`:

| Situação | Resultado |
|----------|-----------|
| Generate, ambos omitidos | 1280×720 |
| Edit, ambos omitidos | WxH do primeiro `--inputs` |
| `--width` e `--height` os dois presentes | usar esses valores (pedido explícito, inclusive 1280×720 numa fonte 4:5) |
| Só um dos dois | `ERROR=--width and --height must be set together.` |
| Edit, arquivo ilegível / sem dimensões | `ERROR=Could not read image size from <path>` (fail-closed; **não** cair em 16:9) |

Vídeo e upscale: qualquer `--width`/`--height` presente (não-None) continua `ERROR=… not supported`. Fica **mais limpo** do que comparar com 1280×720 — hoje `--width 1280 --height 720` no vídeo passa porque coincide com o default.

Generate com `--width 1024 --height 1280` não muda.

---

## 5. Onde entra no código

Uma função pura, testável, sem API:

```python
DEFAULT_IMAGE_WIDTH = 1280
DEFAULT_IMAGE_HEIGHT = 720

def read_image_size(path: str) -> tuple[int, int]:
    """Return (width, height). Raise ValueError if unsupported/unreadable."""

def resolve_image_output_size(args) -> tuple[int, int]:
    """Fill generate default or inherit first edit input. Never call APIs."""
```

`read_image_size`: **stdlib só** (PNG IHDR, JPEG SOF, GIF, WebP VP8/VP8L/VP8X). Sem Pillow no runtime — o script hoje não depende de PIL. Testes gravam fixtures minúsculas.

Chamar em `run_image` (não upscale), depois de `validate_args`, **antes** de `run_image_fal` / `run_image_codex` / `run_image_xai`:

```python
args.width, args.height = resolve_image_output_size(args)
```

Assim logs (`width`/`height` no JSON), `build_flux2_args`, `width_height_to_grok_aspect` e `width_height_to_gpt_aspect` continuam iguais.

Não parsear o prompt.

---

## 6. Skill / agente (o “explicitamente pedido”)

O CLI não adivinha “deixa em 16:9” no texto. Quem lê o pedido é o Hermes.

Na `SKILL.md` / `README.md` / pitfalls:

- Edit **sem** `--width`/`--height`: herda a fonte.
- Se o usuário pedir outro formato (16:9, 9:16, quadrado, paisagem, retrato 9:16, “igual Instagram feed”, etc.): passar `--width` e `--height` (ou o par que o modelo mapeia).
- Não omitir flags e esperar que o prompt sozinho mude a moldura.
- Grok/GPT **arredondam**. Flux chega mais perto do pixel.

Depois do merge no git: copiar para

- `~/.hermes/skills/media/mediagen/`
- `~/.hermes/profiles/coder/skills/media/mediagen/`

(as cópias da skill **não** são o working tree).

---

## 7. Arquivos

- Modify: `scripts/mediagen.py` (`DEFAULT_IMAGE_*`, `read_image_size`, `resolve_image_output_size`, argparse, `validate_args` / `_validate_upscale_args`, `run_image`)
- Modify: `tests/test_unit.py`
- Modify: `SKILL.md`, `README.md`
- Modify: `references/grok-imagine-xai.md`, `references/gptimage2-codex.md` (uma linha cada)
- Create: este plano (já)

Zero mudança no Hostkit Media / lineage / receipts. O PNG sai na proporção certa; o sync continua igual.

---

## 8. Implementação (depois do ok) — TDD fatiado

Python dos testes: o que o repo já usa (`pytest tests/test_unit.py`). Sem chamada fal/xAI/Codex.

### Task 1 — `read_image_size`

**Teste (red):** PNG 1024×1280 (ou fixture 4×5 gerada no teste) e JPEG 1280×720.

```python
def test_png_portrait():
    path = _tiny_png(tmp_path, 1024, 1280)
    assert mediagen.read_image_size(str(path)) == (1024, 1280)

def test_missing_file_raises():
    with pytest.raises(ValueError):
        mediagen.read_image_size("/no/such.png")
```

**Green:** parser stdlib. Sem Pillow.

### Task 2 — `resolve_image_output_size`

**Teste (red):**

- generate, width=height=None → (1280, 720)
- edit, None+None, input 1024×1280 → (1024, 1280)
- edit, width=1280 height=720 explícito, input 1024×1280 → (1280, 720)
- só width ou só height → `SystemExit` com a mensagem juntos
- input ilegível → `SystemExit` (não 1280×720)

**Green:** função pura + `sys.exit` no mesmo estilo de `validate_args`.

### Task 3 — argparse + validate vídeo/upscale

**Teste (red):** `validate_args` de upscale/vídeo falha se `width`/`height` não-None; passa se ambos None.

Ajustar `_make_args` que hoje copiam default 1280×720: generate/image keep 1280×720 explícito nos testes de *payload*; upscale/vídeo usam `None`.

**Green:** `default=None`; checks `is not None` em vez de `!= 1280`.

### Task 4 — `run_image` aplica resolve antes do build

**Teste (red):** mock de `run_image_xai`/`build_grokimage2_args` **ou** teste de `resolve` + um teste de grok:

`width_height_to_grok_aspect(1024, 1280) == "3:4"` (pode ir na Task 1 se já existir o mapper).

`run_image` seta `args.width/height` antes do dispatch. Não duplicar a lógica em fal/codex/xai.

### Task 5 — docs

SKILL, README, duas references. Pitfall: “edit sem flags herda; 1280×720 default só no generate”.

### Task 6 — commit no repo mediagen + copiar skill

Não deploy Hostkit. mediagen não tem image pin Contabo.

---

## 9. Verificação

```bash
cd /home/bfranceschin/projects/mediagen
# comando de teste que o README/pytest do repo já usa
pytest tests/test_unit.py -q
```

Esperado: suite atual verde + novos casos. Zero teste de integração paga.

Sanidade local (depois do green, se Bernardo quiser): **não** re-rodar o edit da pintura neste plano — isso é opt-in e custa crédito Grok.

---

## 10. Decisões para não reabrir

| Tema | Decisão |
|------|---------|
| Como o usuário “pede” outro formato | Só flags CLI; skill manda o agente preenchê-las |
| Qual input | O primeiro `--inputs` |
| Default generate | Continua 1280×720 |
| Grok 4:5 | Nearest 3:4; documentar |
| Fail-closed | Não herdar → não silenciar em 16:9 |
| Pillow | Não no runtime |
| i2v | Fora do v1 |

---

Plano completo. Pronto para executar com subagent-driven-development depois do ok — um subagente por task, review de spec e de qualidade. Sigo só com o sinal verde.

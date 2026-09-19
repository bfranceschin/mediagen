# mediagen i2v — manter aspect ratio — recorte v1

> **Status:** aprovado (Bernardo: “Faça o novo recorte”). Implementar neste commit.

**Goal:** Em **image-to-video**, se ninguém passou `--aspect-ratio`, usar a proporção do frame inicial — não o default 16:9.

**Iguais ao edit de imagem:** flags omitidas = herdar; flags explícitas = pedido. CLI não lê o prompt.

**Fora:** text-to-video continua 16:9; não usar `auto` do Seedance (significado incerto); sem prova paga de vídeo neste recorte.

**Snap:** 4:5 → **3:4** (Grok e Seedance; nenhum tem 4:5).

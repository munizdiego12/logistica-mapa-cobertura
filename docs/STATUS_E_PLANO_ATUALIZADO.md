# Status e Plano Atualizado — Plataforma de Roteirização

Base: `MEMORIA_PROJETO_roteirizacao.md` (31/08/2026) comparado com o repositório GitHub (último commit `21c28ad`, 01/09/2026).

## O que já está feito

| Etapa | Situação | Evidência |
|---|---|---|
| 1. Autenticação | **Feita** | `auth.py`, tabela `operadores`, `/api/auth/register` (com código de convite), `/login`, `/me`, `Login.jsx` conectado ao `App.jsx`. Bug do "Network Error" corrigido no commit `862ee49` (`frontend/src/config.js` unifica a URL do backend). |
| 2. CEP/raio sem fallback sintético | **Feita** | Commit `21c28ad`: BrasilAPI v2 + ViaCEP, CEPs com erro sinalizados em vez de substituídos. |
| **2b. Base nacional de CEP via CNEFE** | **Feita** (concluída) | 27 UFs, ~24,6 mil prefixos, ~4 MB no Neon (`cep_prefixos`); `ibge_municipios` (5.571); cobertura por prefixo com Total/Parcial, legenda, fonte e XLSX com aba "Cobertura e fonte", validada no site (Av. Paulista 4.057 prefixos, Av. Atlântica 463, Florianópolis 76). Faixas manuais e fallback removidos (fase 4). Ver seção Etapa 2b. **Pendências:** importar o XLSX na transportadora antes do primeiro uso real; confirmar o termo de uso do CNEFE. |
| Extras | Feitos | Paleta da tela de login; `geocache.db` removido do git. |
| 0. Banco permanente (Neon) — parte concluída | **Feita** (parcial) | Banco migrado para o Neon; operador recadastrado; login em produção funcionando (backend no Render com `psycopg2` corrigido, commit `a3ab502`). **Pendentes:** backup automático e Alembic (ver Etapa 0). |
| 0b. `requirements.txt` em UTF-8 | **Feita** (parcial) | Regravado em UTF-8 e `sqlalchemy>=2.0,<2.1` fixado no commit `a3ab502`. Falta remover `correcoes_etapa1_auth.patch` da raiz. |

## O que falta

| Etapa | Prioridade | Situação no código |
|---|---|---|
| **0. Banco permanente — restante** | Alta | Neon já concluído. Faltam o **backup automático (GitHub Actions)** — Etapa 3 do CHECKLIST — e o **Alembic** — Etapa 4 do CHECKLIST. Ver seção abaixo. |
| 0b. Remover `correcoes_etapa1_auth.patch` | Baixa | O `requirements.txt` já foi regravado em UTF-8. Resta tirar o `.patch` da raiz. |
| 3. Cadastro de motoristas e veículos | Alta | Não existe. `main.py` ainda usa frota gerada ("Motorista 01"). Falta tabela, CRUD, 2 tipos de veículo com custo fixo (R$130 / R$260). Cada tipo de veículo ganha o campo opcional "peso de referência (kg)" (pode ficar em branco; não é limite, é só um guia para o motor). |
| 4. Lojas, hub no mapa, capacidade e janelas | Alta | Não existe. Hub ainda é texto livre. A capacidade por loja (peso e volume) passa a ser opcional. |
| 5. Origem dos pedidos (Sheets/BigQuery) | Alta | Só CSV/XLSX. Conectores pendentes do schema do BigQuery. |
| 6. Seleção de pedidos por loja/data (checkbox) | Alta | Não existe. |
| **Peso dos pedidos (NOVO)** | Alta | Decisão tomada; pesquisa na internet encerrada (rendeu pouco); subetapa 2 (tabela `item_pesos` via Alembic, rotas protegidas, tela "Pesos dos itens", fila "sem peso" e script de carga) **pronta no código, falta aplicar no Neon e fazer a carga**; próximo passo é pedir os pesos ao Atacadão/operação e conferir à mão os mais vendidos; falta o peso por pedido/rota/veículo (apenas informativo, nunca bloqueia). Ver seção abaixo. |
| 7. VRP com OR-Tools | Crítica | `ortools` não está no `requirements.txt`. `routing.py` tem um VRPTW próprio e `main.py` faz agrupamento simples. Falta setor cardeal e regra de rotação. O peso de referência do veículo (opcional) é só um guia para equilibrar rotas e dividir viagens, nunca uma restrição; o motor não deixa de montar uma rota por causa do peso. |
| 8. Controle de duplicidade (`pedidos_roteirizados_hoje`) | Alta | Não existe. |
| 9. Matriz de despacho com sugestão e alternativas | Média | Não existe. |
| 10. Relatórios de janela e limite de km | Média | Não existe. |
| 11. Histórico | Média | Não existe. |
| 12. Romaneio com novas colunas | Baixa | Não feito. |
| Layout (mapa grande, painel retrátil de pedidos) | A decidir | Em aberto. |
| Proteger as rotas de negócio com o token | Média | O frontend já envia o token, mas os endpoints (`/upload`, `/otimizar`, `/cobertura-ceps`) provavelmente ainda estão abertos. Conferir. |

## Etapa 0 — Banco de dados permanente

**Situação:** a parte do Neon está **concluída** (passos 1 a 5 abaixo). **Pendentes:** backup automático com GitHub Actions (passo 6, Etapa 3 do CHECKLIST) e Alembic (passo 7, Etapa 4 do CHECKLIST).

**Problema:** o Postgres gratuito do Render expira (cerca de 30 dias) e depois é apagado.

**Recomendação: Neon (neon.tech).**
- Postgres gratuito sem prazo de expiração (0,5 GB por projeto).
- Suspende por inatividade e volta em ~1 s, sem perder dados.
- Compatível com o `DATABASE_URL` e o SQLAlchemy atuais.

Alternativas:
- **Supabase:** gratuito, mas pausa o projeto após 1 semana sem uso.
- **Render pago:** a partir de ~US$ 6/mês, simples mas pago.
- **Ideal em produção:** o time de TI da empresa hospedar o banco.

**Passos:**
1. ✅ Criar conta e projeto no Neon (região São Paulo, se disponível) e copiar a connection string.
2. ✅ No Render, trocar `DATABASE_URL` pela string do Neon. Usar `?sslmode=require`.
3. ✅ Redeploy. O `create_all` e o `CREATE TABLE IF NOT EXISTS` recriam `operadores`, `geocode_cache` e `geocache`.
4. ✅ Recadastrar o operador (Diego) via `/api/auth/register` com o código de convite.
5. ✅ Repovoar a base de CEPs rodando `scripts/carregar_municipios.py` e `scripts/carregar_cnefe.py` (Etapa 2b) apontando para o novo banco. O cache também volta a crescer com o uso.
6. ⏳ **Pendente.** Agendar um backup periódico automático (`pg_dump` via GitHub Actions) para o banco nunca mais virar um ponto único de falha.
7. ✅ **Alembic configurado (09/10/2026)** em `backend/alembic.ini` e `backend/migrations/` (asyncpg; `DATABASE_URL` só pela variável de ambiente; revisão `0001` vazia e `0002` de `item_pesos`). As tabelas antigas (`operadores`, `geocode_cache`, `cep_prefixos`, `ibge_municipios`) continuam criadas pelo `init_db` e pelos scripts; falta a migration inicial delas (Etapa 4 do CHECKLIST). Tabela nova só entra por migration, nunca por `create_all`.

**Validar:** ✅ `/api/auth/login` funciona em produção. ⏳ Ainda a confirmar: o cache persiste após reiniciar o Render, e o banco continua lá depois de 30 dias.

## Etapa 2b — Base nacional de CEP via CNEFE — **concluída**

**Resultado:** a cobertura por raio usa só a tabela `cep_prefixos` (CNEFE 2022 do IBGE: um registro por prefixo de CEP de 5 dígitos, com o ponto central pela mediana dos endereços, `n_enderecos`, dispersão, localidade e município). Carga nacional feita no Neon: **27 UFs, ~24,6 mil prefixos, ~4 MB** (cerca de 1% do limite de 0,5 GB). Validada no site: Av. Paulista com 4.057 prefixos, Av. Atlântica com 463 e Florianópolis com 76. A tabela de faixas manuais e o fallback foram removidos do app (fase 4).

**Fonte escolhida:** CNEFE 2022 do IBGE (gratuito, oficial). Descartados: CEP Aberto (parado desde 2022, exige cadastro, ODbL) e OpenStreetMap (CEP esparso, base grande).

**Decisões do Diego:**
- Tabela por **prefixo de 5 dígitos** (suficiente: no DF 86% dos prefixos têm dispersão até 2 km; no AC rural a mediana é 17 km, o que aparece como "Parcial").
- **Exportação:** coluna "Cobertura" (Total/Parcial) por último na aba principal, parciais mantidos; legenda de uma linha e a atribuição "Fonte: IBGE, CNEFE 2022" na aba extra "Cobertura e fonte". A legenda diz também que a distância (Raio X km) é em linha reta entre o hub e o centro do prefixo, não por estrada.
- Bairro em Title Case com da/de/do em minúsculas (o CNEFE não traz acento); "e outros" quando a localidade representa menos de 50% do prefixo. Prazo de 1 dia até 12 km.

**Fases (todas concluídas):**
1. **Faixas manuais unificadas, sem DROP** (76 faixas, validadas em produção). *Substituídas pelo CNEFE e removidas na fase 4.*
2. **Carga do CNEFE por prefixo**, uma UF por vez (`scripts/carregar_cnefe.py`): leitura e agregação por partes (SP real: 22,95 milhões de endereços, pico de 571 MB), descarta prefixos com CEP fora da faixa da UF (erro de digitação no CNEFE), uma UF só substitui um prefixo de outra com mais endereços, apaga o download de cada UF, para se a tabela passar de 100 MB e reconecta (até 3 tentativas) se o Neon derrubar a conexão (ocorrência no SP, corrigida).
3. **Municípios do IBGE e código IBGE real** (`ibge_municipios`, 5.571; `scripts/carregar_municipios.py`) e **troca da consulta** para `cep_prefixos` (filtro por caixa lat/lon, Total/Parcial pela dispersão, erro 503 explícito em vez de aviso falso, mensagens de tela sem termos técnicos). *BrasilAPI v2 sob demanda para CEPs ausentes e centroides de município como último recurso não foram feitos: com a base nacional completa não são necessários para a cobertura por raio; ficam como melhoria futura, sem bloquear nada.*
4. **Aposentar as faixas manuais** (feito): `ceps_reais`, `backend/faixas_cep.py`, `scripts/carregar_faixas.py`, `scripts/data/faixas_cep.csv` e seus testes saíram do repositório (continuam no histórico do git); o endpoint não consulta mais faixas manuais nem tem fallback por UF, porque as 27 UFs têm prefixos (região sem prefixos mostra o aviso de região sem cobertura). **A tabela `ceps_reais` continua no Neon, sem uso:** pode ser apagada quando quiser (`DROP TABLE ceps_reais;`); não foi mexido no banco.

**Investigação dos prefixos de fronteira descartados (07/10/2026):** três prefixos com CEP fora da faixa da UF e muitos endereços foram analisados nos arquivos do IBGE (concentração das coordenadas, ruas, localidades, o que o resto do município usa e o que a UF dona da faixa tem naquele prefixo):
- **PB 59225** (Nova Floresta, 106 endereços): legítimo. Um único loteamento (Novo Horizonte), a 0,8 km do cluster do mesmo prefixo em Jaçanã/RN (5.028 endereços), com pontos encostados (distância mínima 0 km): área contígua na divisa, atendida com o CEP de Jaçanã. Descartar não muda nada: o prefixo já existe pelo RN e incluir os 106 endereços deslocaria o ponto central em cerca de 0,02 km.
- **MA 68527** (São Pedro da Água Branca, 373 endereços): inconsistente, não é CEP legítimo da cidade. As mesmas localidades e ruas têm 2.874 e 962 outros endereços com o CEP do MA (65920), e o prefixo é o de Abel Figueiredo/PA, cujo cluster está a 14,7 km. Provável erro de atribuição no Censo.
- **BA 49117** (Brumado, 33 endereços): erro de digitação. Uma rua só; o SE não tem nenhum endereço com esse prefixo; Brumado fica no interior da Bahia, e a mesma localidade usa 46117 (1.725 endereços).
- **Conclusão:** a regra de descarte por faixa da UF foi mantida; nenhuma carga adicional necessária.

**Validar (feito):** a consulta por raio devolve CEPs de qualquer UF; recarregar não apaga dados; tamanho no Neon dentro do previsto.

## Peso dos pedidos — decisão e estudo de viabilidade

**Decisões do Diego (08/10/2026):** (1) a subetapa 2 só começa depois do **backup automático (Etapa 3 do CHECKLIST)** e do **Alembic com rotas protegidas (Etapa 4)**, porque a tabela de pesos terá dados conferidos à mão e uma tela de edição que precisa de login e de migration; (2) pedido com item sem peso mostra o peso como mínimo ("≥ X kg, faltam N itens"; ver a decisão de produto abaixo); (3) **qualquer operador logado pode editar a tabela** e o sistema registra quem alterou e quando; (4) a **janela de entrega** é outro assunto e fica em aberto.

**Decisão de produto (08/10/2026): o peso dos pedidos é apenas informativo.** O sistema mostra o peso de cada pedido e o total como **"≈ X kg (estimado)"**, ou **"≥ X kg, faltam N itens"** quando houver itens sem peso, e **NUNCA bloqueia nem avisa em vermelho por capacidade de veículo**. Quem decide o que o motorista leva é o operador. Ajustes por etapa:
- **Motoristas e veículos:** cada tipo de veículo ganha o campo opcional **"peso de referência (kg)"**, que pode ficar em branco ("sem referência"). Não é limite: é só um guia para o motor.
- **Lojas:** a capacidade por loja (peso e volume) deixa de ser obrigatória e passa a ser **opcional**.
- **Roteirização (OR-Tools):** o motor usa o peso de referência do veículo, quando existir, **apenas como guia** para equilibrar as rotas e dividir viagens (sugestão, nunca restrição rígida). Sem referência, agrupa só por proximidade e setor. O operador pode mudar qualquer agrupamento, o sistema nunca recusa e **o motor não deixa de montar uma rota por causa do peso**.
- **Telas:** mostrar o peso de cada pedido, o total das rotas selecionadas e o total por veículo, **sempre com o selo "estimado"** e o aviso de itens sem peso.
- **Removidos do plano:** o aviso de 90% da capacidade e qualquer trava por peso.

**Pesquisa na internet encerrada (decisão do Diego, 08/10/2026):** rendeu pouco (**4 pesos de confiança média, 36 de baixa, 26 não achados e 34 não pesquisados**). O limite de buscas **não será aumentado** e os 34 **não serão continuados**. Próximo passo: **pedir os pesos à fonte real** (cadastro de itens do Atacadão, a operação ou pesagem) e **conferir à mão os SKUs mais vendidos**; os 4 pesos de confiança média e a revisão manual dos 36 de confiança baixa entram só como complemento.

**Decisão original:** não depender da API do Atacadão (ela não devolve peso). Vamos manter uma **tabela `item_pesos` no Neon**, com carga inicial extraída do nome do produto e **conferência manual dos itens mais vendidos**. Pedidos com itens sem peso aparecem como **"peso incompleto"** (o peso mostrado é um piso).

**Subetapas:**
1. **Estudo de viabilidade e CSV inicial — feita.** `scripts/estudo_peso.py` (só lê arquivos locais: sem rede, sem banco) lê `data/peso/skus.csv` e `data/peso/itens_pedidos.csv`, extrai o peso do nome (kg, g, mg, ml, L; `2x500g`, `12 x 1L`, `500g x 2` como multiplicador; ml/L = kg com densidade 1; contagens, dimensões e capacidades como saco de lixo e copo nunca viram peso) e gera `data/peso/item_pesos_inicial.csv` (`id_sku`, `reference_code`, `nome`, `peso_kg_sugerido`, `fonte`, `confianca`, `unidades_vendidas`), ordenado por unidades vendidas para revisão de cima para baixo. **`data/peso/` está no `.gitignore` (o repositório é público): nenhum dado de pedido vai para o git**, e o script recusa gravar o CSV dentro do repositório fora de pasta ignorada. Opção `--excel` gera o CSV com `;` e vírgula decimal (o Excel em português lê `1.5` como data).
2. **Tabela `item_pesos`, tela de manutenção e fila "sem peso" — pronta no código (09/10/2026), falta aplicar no Neon.** Alembic (revisões `0001` e `0002`, asyncpg), tabela `item_pesos` (`id_sku`, `reference_code`, `nome`, `peso_kg`, `fonte`, `confianca`, `atualizado_em`, `atualizado_por`, mais `unidades_vendidas` para ordenar a fila, com checagem de peso entre 0 e 1.000 kg e de confiança alta/media/baixa); rotas protegidas por login (`/api/item-pesos`: resumo, fila sem peso, lista com busca, `PUT` para editar e `POST skus-vistos`); qualquer operador logado edita e fica registrado **quem alterou e quando**; tela "Pesos dos itens" no cabeçalho; `scripts/carregar_item_pesos.py` (resumo antes de gravar, grava só com `--gravar` e confirmação digitada, aceita `;`/`,` e vírgula decimal, ignora peso em branco, não sobrescreve o que um operador editou, reconecta se o Neon derrubar a conexão). Os pedidos ainda não trazem SKU: a fila recebe SKUs novos por `POST /api/item-pesos/skus-vistos`, a ser chamado quando os pedidos tiverem itens (Etapas 7 e 15). Passos para aplicar no Neon: ver o CHECKLIST (Etapa 7b).
3. **Peso por pedido, rota e veículo — pendente** (apenas informativo: "≈ X kg (estimado)" ou "≥ X kg, faltam N itens", com o total das rotas selecionadas e o total por veículo; nunca bloqueia nem avisa por capacidade; a Etapa 7, OR-Tools, só usa o peso de referência do veículo como guia).

**Resultado do estudo (amostra de 6.675 SKUs, 32.422 itens, 2.164 pedidos, 13 lojas, 152.753 unidades; soma de `quantity_sku` por SKU = `unidades` em 100% dos casos):**
- **Cobertura por unidades vendidas: 93,6%** (confiança alta 92,1%; baixa 1,5%); por SKU 89,8% (alta 86,2%; baixa 3,6%); 681 SKUs (10,2%) sem medida no nome.
- **Pedidos completos: 39,1%** (847 de 2.164; só com confiança alta, 32,9%), porque basta 1 item sem peso entre os ~12 do pedido; os incompletos têm mediana de 2 itens sem peso em 17.
- **Quanto a conferência manual ajuda** (SKUs sem peso mais vendidos): 248 SKUs → 80% dos pedidos completos; 426 → 90%; 567 → 95%; 681 → 100%. Os 100 primeiros da lista cobrem 76% das unidades sem peso.
- **Categorias de risco entre os sem peso:** contagens "un" (572 SKUs, 92,7% das unidades sem peso, em geral combinadas com as outras), rolos (97 SKUs, 24,5%), folhas (81 SKUs, 22,1%), só dimensões (129 SKUs, 23,0%), capacidade em ml/L (54 SKUs, 6,6%), ovos (22 SKUs, 4,7%), kit/leve-pague (47 SKUs, 3,0%).
- **Peso estimado dos pedidos completos (kg):** P10 9,6 | mediana 34,3 | P90 124,9 | máximo 1.520.
- **Limites:** densidade 1 para ml/L (erro pequeno); peso líquido, não bruto; os SKUs de confiança baixa (3,6%: multiplicador, contagem, kit) pedem conferência; pedidos incompletos mostram só um piso.

**Pesquisa de pesos na internet (08/10/2026):** para os 100 SKUs mais vendidos sem peso extraível ou com confiança baixa (8.327 unidades, 5,5% do total vendido), 10 agentes pesquisaram na internet o peso do produto embalado, exigindo link e trecho da fonte e proibindo valores de memória; o resultado está em `data/peso/item_pesos_pesquisa.csv` (fora do git; nada foi gravado no banco). 40 dos 100 SKUs mais vendidos sem peso ou com confiança baixa ficaram com peso sugerido (**4 de confiança média**, conferidos em página aberta ou título claro, e **36 de confiança baixa**, em sua maioria só de resumo de busca ou de conta sobre pesos unitários); **26 foram pesquisados sem achar** e **34 ficaram com a pesquisa incompleta**, porque o limite de 200 buscas da sessão acabou. Os 40 pesos cobrem 37,8% das unidades desses 100 SKUs. Lições: a busca genérica cai em páginas do Tenda, Drogasil, Drogaraia, Panvel e Magalu, que não trazem peso ou dão 403; com filtro de domínios (Amazon, Mercado Livre, Carrefour, Telhanorte, Leroy Merlin, Pão de Açúcar...) o resultado da busca traz a ficha técnica, mas as páginas da Amazon, do Mercado Livre e do Carrefour abrem sem a ficha ou dão 403; Telhanorte e Pão de Açúcar abrem com a linha de peso. O WebFetch devolve um resumo, não o texto literal, então os "trechos" precisam de conferência. Nenhum EAN foi confirmado (códigos internos de loja não são EAN). **Pesquisa encerrada por decisão do Diego (08/10/2026):** rendeu pouco (4 médios, 36 baixos, 26 não achados, 34 não pesquisados); o limite de buscas não será aumentado e os 34 não serão continuados. Próximo passo: pedir os pesos ao Atacadão/operação (cadastro ou pesagem) e conferir à mão os mais vendidos, com os 4 de confiança média e a revisão manual dos 36 de baixa como complemento.

**Perguntas:**
- ✅ Quem mantém a tabela `item_pesos`: qualquer operador logado, com registro de quem alterou e quando.
- ➡️ Janela de entrega: outro assunto, fica em aberto (não aparece nos dois CSVs do estudo).
- ❓ Existe outra fonte de peso? As colunas `weight` (BigQuery) e "Peso Entrega" (Sheets) do plano original trazem o peso do pedido ou do item?
- ❓ Peso líquido (o do rótulo, como no estudo) ou bruto (com embalagem)?
- ❓ A tabela do BigQuery é atualizada todo dia? Isso define se SKUs novos entram na fila "sem peso" diariamente.

## Ordem sugerida a partir de agora

1. Etapa 0 restante (backup automático e Alembic) e 0b (remover o `.patch`).
2. Proteger rotas de negócio com o token.
3. Etapas 3 e 4 (motoristas, lojas): base de dados para tudo o resto.
4. Etapas 6 e 5 (seleção de pedidos, depois conectores quando o schema do BigQuery chegar).
5. Peso dos pedidos (subetapas 2 e 3), **depois** do backup e do Alembic com rotas protegidas (itens 1 e 2): o peso é só informativo (o solver só usa a referência do veículo como guia).
6. Etapa 7 (OR-Tools), com 8 (duplicidade).
7. Etapas 9, 10, 11 e 12.
8. Decidir o layout.

## Pendências externas
- Schema do BigQuery e queries pré-salvas.
- Credenciais de BigQuery e Google Sheets.
- Confirmar o termo de uso/atribuição do CNEFE com o IBGE antes de redistribuir tabelas a clientes (a página do IBGE não abriu na checagem).

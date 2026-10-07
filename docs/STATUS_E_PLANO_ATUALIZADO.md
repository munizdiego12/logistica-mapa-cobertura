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
| 3. Cadastro de motoristas e veículos | Alta | Não existe. `main.py` ainda usa frota gerada ("Motorista 01"). Falta tabela, CRUD, 2 tipos de veículo com custo fixo (R$130 / R$260). |
| 4. Lojas, hub no mapa, capacidade e janelas | Alta | Não existe. Hub ainda é texto livre. |
| 5. Origem dos pedidos (Sheets/BigQuery) | Alta | Só CSV/XLSX. Conectores pendentes do schema do BigQuery. |
| 6. Seleção de pedidos por loja/data (checkbox) | Alta | Não existe. |
| 7. VRP com OR-Tools | Crítica | `ortools` não está no `requirements.txt`. `routing.py` tem um VRPTW próprio e `main.py` faz agrupamento simples. Falta setor cardeal e regra de rotação. |
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
7. ⏳ **Pendente.** Antes de criar as tabelas das próximas etapas (motoristas, lojas, histórico), adotar **Alembic** para migrations, assim mudanças de schema não dependem só de `create_all`.

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

## Ordem sugerida a partir de agora

1. Etapa 0 restante (backup automático e Alembic) e 0b (remover o `.patch`).
2. Proteger rotas de negócio com o token.
3. Etapas 3 e 4 (motoristas, lojas): base de dados para tudo o resto.
4. Etapas 6 e 5 (seleção de pedidos, depois conectores quando o schema do BigQuery chegar).
5. Etapa 7 (OR-Tools), com 8 (duplicidade).
6. Etapas 9, 10, 11 e 12.
7. Decidir o layout.

## Pendências externas
- Schema do BigQuery e queries pré-salvas.
- Credenciais de BigQuery e Google Sheets.
- Confirmar o termo de uso/atribuição do CNEFE com o IBGE antes de redistribuir tabelas a clientes (a página do IBGE não abriu na checagem).

# Status e Plano Atualizado — Plataforma de Roteirização

Base: `MEMORIA_PROJETO_roteirizacao.md` (31/08/2026) comparado com o repositório GitHub (último commit `21c28ad`, 01/09/2026).

## O que já está feito

| Etapa | Situação | Evidência |
|---|---|---|
| 1. Autenticação | **Feita** | `auth.py`, tabela `operadores`, `/api/auth/register` (com código de convite), `/login`, `/me`, `Login.jsx` conectado ao `App.jsx`. Bug do "Network Error" corrigido no commit `862ee49` (`frontend/src/config.js` unifica a URL do backend). |
| 2. CEP/raio sem fallback sintético | **Feita** | Commit `21c28ad`: BrasilAPI v2 + ViaCEP, CEPs com erro sinalizados em vez de substituídos. |
| Extras | Feitos | Paleta da tela de login; `geocache.db` removido do git. |
| 0. Banco permanente (Neon) — parte concluída | **Feita** (parcial) | Banco migrado para o Neon; operador recadastrado; login em produção funcionando (backend no Render com `psycopg2` corrigido, commit `a3ab502`). **Pendentes:** backup automático e Alembic (ver Etapa 0). |
| 0b. `requirements.txt` em UTF-8 | **Feita** (parcial) | Regravado em UTF-8 e `sqlalchemy>=2.0,<2.1` fixado no commit `a3ab502`. Falta remover `correcoes_etapa1_auth.patch` da raiz. |
| 2b, fase 1: faixas de CEP unificadas | **Feita** | `scripts/data/faixas_cep.csv` (76 faixas) + `scripts/carregar_faixas.py` (upsert, sem DROP) + `backend/faixas_cep.py` (schema, validador) + `ceps_reais` criada no `init_db`. Scripts antigos removidos. **Validada em produção** (ver Etapa 2b). |
| 2b, fase 2 (parcial): CNEFE por prefixo de CEP | **Feita** (parcial) | `scripts/carregar_cnefe.py` + `backend/cnefe.py` (tabela `cep_prefixos`, upsert). AC gravado no Neon (45 prefixos). DF medido em SQLite local (755 prefixos). |
| 2b, passos 1 e 2: `localidade`, municípios do IBGE e código IBGE | **Feitos no código** | `localidade`/`localidade_pct` em `cep_prefixos`; tabela `ibge_municipios` (5.571) com `scripts/carregar_municipios.py`; coluna `ibge` em `ceps_reais`; código IBGE fixo removido de `main.py` e `database.py`. **Falta gravar no Neon** (comando na seção Etapa 2b). |

## O que falta

| Etapa | Prioridade | Situação no código |
|---|---|---|
| **0. Banco permanente — restante** | Alta | Neon já concluído. Faltam o **backup automático (GitHub Actions)** — Etapa 3 do CHECKLIST — e o **Alembic** — Etapa 4 do CHECKLIST. Ver seção abaixo. |
| 0b. Remover `correcoes_etapa1_auth.patch` | Baixa | O `requirements.txt` já foi regravado em UTF-8. Resta tirar o `.patch` da raiz. |
| **2b. Base nacional de CEP via CNEFE (NOVO)** | Alta | Hoje `ceps_reais` só tem faixas manuais de capitais e regiões metropolitanas. Ver seção abaixo. **Fase 1 concluída e validada em produção**; fase 2 em andamento (AC no Neon; falta gravar DF, municípios e `ibge`/`localidade`); **passo 3 (troca da consulta) com plano apresentado, aguardando confirmação do Diego**; fase 4 pendente. |
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
5. ✅ Repovoar o cache de CEPs e as faixas rodando `scripts/carregar_faixas.py` (Etapa 2b, fase 1) apontando para o novo banco. O cache também volta a crescer com o uso.
6. ⏳ **Pendente.** Agendar um backup periódico automático (`pg_dump` via GitHub Actions) para o banco nunca mais virar um ponto único de falha.
7. ⏳ **Pendente.** Antes de criar as tabelas das próximas etapas (motoristas, lojas, histórico), adotar **Alembic** para migrations, assim mudanças de schema não dependem só de `create_all`.

**Validar:** ✅ `/api/auth/login` funciona em produção. ⏳ Ainda a confirmar: o cache persiste após reiniciar o Render, e o banco continua lá depois de 30 dias.

## Etapa 2b — Base nacional de CEP via CNEFE

**Problema:** os dois scripts de carga de faixas faziam `DROP TABLE ceps_reais` (um apagava o outro) e juntos só cobriam capitais e regiões metropolitanas, com 1 ponto por faixa grande.

**Fonte escolhida:** CNEFE 2022 do IBGE (gratuito, oficial, ~931 mil CEPs com endereços georreferenciados). Descartados: CEP Aberto (parado desde 2022, exige cadastro, ODbL) e OpenStreetMap (CEP esparso, base grande). BrasilAPI v2 fica só como complemento sob demanda.

**Decisões do Diego:**
- Começar pela tabela por **prefixo de 5 dígitos** (~24,6 mil linhas, ~3–6 MB no Neon). Evoluir para CEP completo (~120–150 MB) só se a precisão não bastar.
- **Toda exportação que use dados do CNEFE deve trazer a atribuição "Fonte: IBGE, CNEFE 2022".**
- **Exportação com coluna "Cobertura" (Total/Parcial):** os prefixos parciais são **mantidos** na exportação, não removidos. A exportação também ganha **uma linha de legenda** explicando Total e Parcial e a linha de atribuição "Fonte: IBGE, CNEFE 2022". Valem a partir da troca da consulta (passo 3), quando a exportação passar a usar `cep_prefixos`: hoje ela usa `ceps_reais` (faixas manuais, sem dispersão), onde não existe "parcial" nem dado do CNEFE.

**Fases:**
1. **Unificar as faixas manuais, sem DROP.** Um CSV (`scripts/data/faixas_cep.csv`), um carregador com upsert (`scripts/carregar_faixas.py`), `UNIQUE (cep_inicial, cep_final)`, validador (formato, limites do Brasil, sobreposição) e remoção dos scripts antigos. — **concluída** (a sobreposição do Rio de Janeiro foi corrigida: Centro passou a `20000000–20499999`; o carregador não apaga faixas antigas de um banco já populado, então um banco que já tenha a faixa velha precisa dela removida à mão). **Validada em produção:** Neon com as 76 faixas carregadas; cobertura testada na Av. Paulista (24 CEPs) e na Av. Atlântica (6 CEPs); Florianópolis, que não tem faixas, devolveu o aviso correto de CEPs sem cobertura em vez de um resultado inventado
2. **Carga do CNEFE por prefixo de 5 dígitos.** Script offline que lê cada UF (download total ~3,7 GB, não vai para o banco), calcula a mediana dos pontos por prefixo e grava com upsert. — **em andamento.**
   - **Feito:** `scripts/carregar_cnefe.py` + `backend/cnefe.py` (tabela `cep_prefixos`, upsert por prefixo, `fonte` = "IBGE, CNEFE 2022"). AC gravado no Neon (45 prefixos, idênticos à lista oficial de CEPs do IBGE). DF medido em SQLite local: 755 prefixos, também idênticos à lista oficial.
   - **Medição da dispersão (raio com 90% dos pontos):** DF mediana 0,46 km, p90 3,3 km, máx. 90 km (86% dos prefixos até 2 km); AC mediana 17 km (19 de 45 prefixos acima de 30 km). Com raio de 30 km, "parcial" fica em ~9% dos prefixos tanto em Brasília (hub no Plano Piloto) quanto em Rio Branco; com 10 km, o AC chega a 31%. Hub no interior de estado rural não foi medido.
   - **Passos 1 e 2 (07/10/2026):** (a) `localidade` (DSC_LOCALIDADE mais frequente do prefixo) e `localidade_pct` (% dos endereços que ela representa), para o Bairro da exportação: no DF 621 de 755 prefixos têm 80% ou mais numa só localidade; no AC só 2 de 45, então lá o bairro é aproximado. (b) Tabela `ibge_municipios` (5.571 municípios: código, nome, UF) em `scripts/data/municipios_ibge.csv`, carregada por `scripts/carregar_municipios.py`; dá nome ao `cod_municipio` do CNEFE. (c) Código IBGE fixo corrigido: removidos o dicionário `ESTADOS_IBGE_BRASIL` e os valores 3550308/2304400 de `main.py` e `database.py`; a loja busca o código por UF + nome em `ibge_municipios`, as faixas de `ceps_reais` ganharam a coluna `ibge` (76 casadas com municípios reais) e, se não houver código, a célula da exportação fica vazia em vez de um valor inventado.
   - **Falta:** gravar no Neon os municípios, as faixas (agora com `ibge`), o AC (agora com `localidade`) e o DF; medir o tamanho no Neon; processar as demais UFs (depois do passo 3).
   - **Como gravar no Neon** (PowerShell, na raiz do projeto; a string do banco só na sessão, nunca em arquivo ou no chat):
     ```
     $env:DATABASE_URL = "<string do Neon>"
     python scripts/carregar_municipios.py
     python scripts/carregar_faixas.py
     python scripts/carregar_cnefe.py --uf AC
     python scripts/carregar_cnefe.py --uf DF
     Remove-Item Env:DATABASE_URL
     ```
3. **Troca da consulta para `cep_prefixos`** — plano apresentado ao Diego, **aguardando confirmação**. A tela de cobertura ainda lê `ceps_reais`. A troca inclui: filtro por caixa lat/lon antes da distância; marcação Total/Parcial pela dispersão; regra por UF (se a UF do hub tem prefixos usa `cep_prefixos`, senão cai em `ceps_reais`, senão mostra o aviso de hoje); coluna `precisao`; exportação com coluna "Cobertura", legenda de uma linha e atribuição "Fonte: IBGE, CNEFE 2022"; BrasilAPI v2 sob demanda para CEPs ausentes e centroides de município do IBGE como último recurso (essas duas últimas, fase posterior).
4. **Aposentar as faixas manuais** nas regiões que o CNEFE já cobrir.

**Validar:** a consulta por raio devolve CEPs de qualquer UF (não só capitais); recarregar não apaga dados; tamanho no Neon dentro do previsto.

## Ordem sugerida a partir de agora

1. Etapa 0 restante (backup automático e Alembic) e 0b (remover o `.patch`).
2. Etapa 2b (base nacional de CEP). A fase 1 já está carregada e validada no Neon. Em seguida: gravar municípios, `ibge`, AC e DF no Neon; confirmar o passo 3 (troca da consulta); só então carregar o resto do Brasil.
3. Proteger rotas de negócio com o token.
4. Etapas 3 e 4 (motoristas, lojas): base de dados para tudo o resto.
5. Etapas 6 e 5 (seleção de pedidos, depois conectores quando o schema do BigQuery chegar).
6. Etapa 7 (OR-Tools), com 8 (duplicidade).
7. Etapas 9, 10, 11 e 12.
8. Decidir o layout.

## Pendências externas
- Schema do BigQuery e queries pré-salvas.
- Credenciais de BigQuery e Google Sheets.
- Confirmar o termo de uso/atribuição do CNEFE com o IBGE antes de redistribuir tabelas a clientes (a página do IBGE não abriu na checagem).

# Status e Plano Atualizado — Plataforma de Roteirização

Base: `MEMORIA_PROJETO_roteirizacao.md` (31/08/2026) comparado com o repositório GitHub (último commit `21c28ad`, 01/09/2026).

## O que já está feito

| Etapa | Situação | Evidência |
|---|---|---|
| 1. Autenticação | **Feita** | `auth.py`, tabela `operadores`, `/api/auth/register` (com código de convite), `/login`, `/me`, `Login.jsx` conectado ao `App.jsx`. Bug do "Network Error" corrigido no commit `862ee49` (`frontend/src/config.js` unifica a URL do backend). |
| 2. CEP/raio sem fallback sintético | **Feita** | Commit `21c28ad`: BrasilAPI v2 + ViaCEP, CEPs com erro sinalizados em vez de substituídos. |
| Extras | Feitos | Paleta da tela de login; `geocache.db` removido do git. |
| 2b, fase 1: faixas de CEP unificadas | **Feita** | `scripts/data/faixas_cep.csv` (76 faixas) + `scripts/carregar_faixas.py` (upsert, sem DROP) + `backend/faixas_cep.py` (schema, validador) + `ceps_reais` criada no `init_db`. Scripts antigos removidos. |

## O que falta

| Etapa | Prioridade | Situação no código |
|---|---|---|
| **0. Banco permanente (NOVO)** | **Urgente** | Banco do Render expirou. Ver seção abaixo. |
| 0b. `requirements.txt` voltou a UTF-16 | **Urgente** | O arquivo no GitHub está de novo em UTF-16 (o bug 1 da memória). Regravar em UTF-8. Também remover `correcoes_etapa1_auth.patch` da raiz. |
| **2b. Base nacional de CEP via CNEFE (NOVO)** | Alta | Hoje `ceps_reais` só tem faixas manuais de capitais e regiões metropolitanas. Ver seção abaixo. **Fase 1 concluída**; fases 2 a 4 pendentes. |
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
1. Criar conta e projeto no Neon (região São Paulo, se disponível) e copiar a connection string.
2. No Render, trocar `DATABASE_URL` pela string do Neon. Usar `?sslmode=require`.
3. Redeploy. O `create_all` e o `CREATE TABLE IF NOT EXISTS` recriam `operadores`, `geocode_cache` e `geocache`.
4. Recadastrar o operador (Diego) via `/api/auth/register` com o código de convite.
5. Repovoar o cache de CEPs e as faixas rodando `scripts/carregar_faixas.py` (Etapa 2b, fase 1) apontando para o novo banco. O cache também volta a crescer com o uso.
6. Agendar um backup periódico (`pg_dump`) para o banco nunca mais virar um ponto único de falha.
7. Antes de criar as tabelas das próximas etapas (motoristas, lojas, histórico), adotar **Alembic** para migrations, assim mudanças de schema não dependem só de `create_all`.

**Validar:** `/api/auth/login` funciona, o cache persiste após reiniciar o Render, e o banco continua lá depois de 30 dias.

## Etapa 2b — Base nacional de CEP via CNEFE

**Problema:** os dois scripts de carga de faixas faziam `DROP TABLE ceps_reais` (um apagava o outro) e juntos só cobriam capitais e regiões metropolitanas, com 1 ponto por faixa grande.

**Fonte escolhida:** CNEFE 2022 do IBGE (gratuito, oficial, ~931 mil CEPs com endereços georreferenciados). Descartados: CEP Aberto (parado desde 2022, exige cadastro, ODbL) e OpenStreetMap (CEP esparso, base grande). BrasilAPI v2 fica só como complemento sob demanda.

**Decisões do Diego:**
- Começar pela tabela por **prefixo de 5 dígitos** (~24,6 mil linhas, ~3–6 MB no Neon). Evoluir para CEP completo (~120–150 MB) só se a precisão não bastar.
- **Toda exportação que use dados do CNEFE deve trazer a atribuição "Fonte: IBGE, CNEFE 2022".**

**Fases:**
1. **Unificar as faixas manuais, sem DROP.** Um CSV (`scripts/data/faixas_cep.csv`), um carregador com upsert (`scripts/carregar_faixas.py`), `UNIQUE (cep_inicial, cep_final)`, validador (formato, limites do Brasil, sobreposição) e remoção dos scripts antigos. — **concluída** (a sobreposição do Rio de Janeiro foi corrigida: Centro passou a `20000000–20499999`; o carregador não apaga faixas antigas de um banco já populado, então um banco que já tenha a faixa velha precisa dela removida à mão)
2. **Carga do CNEFE por prefixo de 5 dígitos.** Script offline que lê cada UF (download total ~3,7 GB, não vai para o banco), calcula a mediana dos pontos por prefixo e grava com upsert. Testar primeiro com o AC e medir com `pg_total_relation_size`. Inclui a atribuição nas exportações.
3. **Complementos e consulta.** Consulta com filtro por caixa antes da distância, coluna `precisao` (`cep`, `faixa`, `cidade`, `brasilapi`), cobertura "parcial", tabela de centroides do IBGE (corrige o `ibge` fixo em 3550308 de `database.py`) e BrasilAPI v2 sob demanda para CEPs ausentes.
4. **Aposentar as faixas manuais** nas regiões que o CNEFE já cobrir.

**Validar:** a consulta por raio devolve CEPs de qualquer UF (não só capitais); recarregar não apaga dados; tamanho no Neon dentro do previsto.

## Ordem sugerida a partir de agora

1. Etapa 0 (banco) e 0b (requirements UTF-8).
2. Etapa 2b (base nacional de CEP). A fase 1 só precisa do banco novo para ser carregada.
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

# Status e Plano Atualizado — Plataforma de Roteirização

Base: `MEMORIA_PROJETO_roteirizacao.md` (31/08/2026) comparado com o repositório GitHub (último commit `21c28ad`, 01/09/2026).

## O que já está feito

| Etapa | Situação | Evidência |
|---|---|---|
| 1. Autenticação | **Feita** | `auth.py`, tabela `operadores`, `/api/auth/register` (com código de convite), `/login`, `/me`, `Login.jsx` conectado ao `App.jsx`. Bug do "Network Error" corrigido no commit `862ee49` (`frontend/src/config.js` unifica a URL do backend). |
| 2. CEP/raio sem fallback sintético | **Feita** | Commit `21c28ad`: BrasilAPI v2 + ViaCEP, CEPs com erro sinalizados em vez de substituídos. |
| Extras | Feitos | Paleta da tela de login; `geocache.db` removido do git. |

## O que falta

| Etapa | Prioridade | Situação no código |
|---|---|---|
| **0. Banco permanente (NOVO)** | **Urgente** | Banco do Render expirou. Ver seção abaixo. |
| 0b. `requirements.txt` voltou a UTF-16 | **Urgente** | O arquivo no GitHub está de novo em UTF-16 (o bug 1 da memória). Regravar em UTF-8. Também remover `correcoes_etapa1_auth.patch` da raiz. |
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
5. Repovoar o cache de CEPs e as faixas rodando `scripts/carga_todas_capitais_faixas.py` e `scripts/atualizar_faixas_oficiais.py` apontando para o novo banco. O cache também volta a crescer com o uso.
6. Agendar um backup periódico (`pg_dump`) para o banco nunca mais virar um ponto único de falha.
7. Antes de criar as tabelas das próximas etapas (motoristas, lojas, histórico), adotar **Alembic** para migrations, assim mudanças de schema não dependem só de `create_all`.

**Validar:** `/api/auth/login` funciona, o cache persiste após reiniciar o Render, e o banco continua lá depois de 30 dias.

## Ordem sugerida a partir de agora

1. Etapa 0 (banco) e 0b (requirements UTF-8).
2. Proteger rotas de negócio com o token.
3. Etapas 3 e 4 (motoristas, lojas): base de dados para tudo o resto.
4. Etapas 6 e 5 (seleção de pedidos, depois conectores quando o schema do BigQuery chegar).
5. Etapa 7 (OR-Tools), com 8 (duplicidade).
6. Etapas 9, 10, 11 e 12.
7. Decidir o layout.

## Pendências externas (inalteradas)
- Schema do BigQuery e queries pré-salvas.
- Credenciais de BigQuery e Google Sheets.

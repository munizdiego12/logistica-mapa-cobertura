# Migrations do banco (Alembic)

O esquema do banco (Neon, PostgreSQL 18) é controlado pelo **Alembic**, em `backend/alembic.ini` e `backend/migrations/`. Regra do projeto: **tabela nova ou mudança de tabela só por migration**, nunca por `create_all` nem à mão no banco.

Revisões atuais:

| Revisão | O que faz |
|---|---|
| `0001` | Ponto de partida, não altera o banco. |
| `0002` | Cria `item_pesos` (pesos dos itens, com quem alterou e quando). |
| `0003` | Descreve as tabelas antigas (`operadores`, `geocode_cache`, `cep_prefixos`, `ibge_municipios`) em SQL idempotente (`CREATE ... IF NOT EXISTS`): num banco novo cria tudo; no Neon, onde já existem com dados, **não faz nada** (não apaga, não recria, não altera dados). O `downgrade` não apaga nada de propósito. |
| `0004` | Cria `tipos_veiculo` (já com "Carro de passeio" R$ 130 e "Fiorino/Utilitário" R$ 260, `ON CONFLICT DO NOTHING`: não desfaz o que um operador editou) e `motoristas` (desativa em vez de apagar). Idempotente; o `downgrade` não apaga nada. |
| `0005` | Acrescenta `motoristas.valor_rota` (valor próprio por rota do motorista, opcional) com `CHECK (valor_rota IS NULL OR valor_rota >= 0)`, via `ADD COLUMN IF NOT EXISTS` (idempotente). Não altera dados; o `downgrade` não apaga nada. |
| `0006` | Cria `rotas_realizadas` (rotas confirmadas: `execucao_id`, `numero_rota`, `motorista_id`, `data` no dia de Brasília, `loja_hub`, `turno`, `qtd_pedidos`, `distancia_km`, `status` `confirmada`/`cancelada`, `criado_em`, `criado_por`), com chave única `execucao_id` + `numero_rota` (confirmar de novo não duplica). Idempotente; o `downgrade` não apaga nada. |
| `0007` | Cria `lojas` (nome já com a filial, `uf` e `endereco` opcionais, `lat`/`lng` com CHECK do Brasil, `ativo`, capacidades opcionais, janelas manhã/tarde/noite, `atualizado_em`/`atualizado_por`), com índice único no nome (sem diferença de maiúsculas e espaços) e sem coluna filial. Idempotente; o `downgrade` não apaga nada. |

Não existe tabela `geocache`: esse nome aparece em notas antigas por causa do arquivo de teste `geocache.db`. O cache de geocodificação é a tabela `geocode_cache`.

## Regras de segurança

- **Rode sempre de dentro de `backend/`**: `cd backend`.
- A string do banco vem **só** da variável de ambiente `DATABASE_URL`, definida na sessão do terminal. Nunca em arquivo, em comando visível (`--url`) ou em conversa. Use a string **direta** do Neon (sem `-pooler`).
- O Alembic usa **asyncpg**, porque o `psycopg2` pode estar bloqueado pelo Windows (política de Controle de Aplicativo). Não tente contornar o bloqueio.
- Antes de aplicar no Neon, **veja o SQL** com `--sql` (não conecta no banco) e confira que não há `DROP`, `TRUNCATE` nem `DELETE`.

## Comandos

```
cd backend

# Ver o SQL que seria aplicado (não conecta no banco; a string pode ser qualquer uma de mentira)
python -m alembic upgrade head --sql

# Em que versão o banco está
python -m alembic current

# Histórico de revisões
python -m alembic history
```

### Aplicar no Neon

```
# PowerShell
cd backend
$env:DATABASE_URL = "<string direta do Neon>"
python -m alembic current
python -m alembic upgrade head
python -m alembic current          # deve mostrar o head (hoje 0007)
Remove-Item Env:DATABASE_URL
cd ..
```

```
# Bash
cd backend
export DATABASE_URL='<string direta do Neon>'
python -m alembic current && python -m alembic upgrade head && python -m alembic current
unset DATABASE_URL
```

Faça um backup antes (o workflow "Backup do Neon" roda todo domingo; ver `docs/BACKUP.md`) e confira depois que as contagens das tabelas não mudaram.

### Marcar o banco de produção como já migrado (`stamp`)

O `stamp` só grava a versão na tabela `alembic_version`, **sem executar SQL de tabela**. Como a `0003` é idempotente, em geral nem é preciso. Use quando o banco já tem o resultado de uma revisão e você quer evitar rodá-la:

```
python -m alembic stamp 0001      # banco ainda sem versão: "ponto de partida"; depois `upgrade head` aplica 0002 e 0003
python -m alembic stamp 0002      # só se item_pesos já tiver sido criada à mão; depois `upgrade head` aplica a 0003
```

Caminho recomendado para o Neon: `current` → (`stamp 0001` se `current` não mostrar nada) → `upgrade head --sql` para revisar → `upgrade head` → `current`.

## Criar uma migration nova

1. Em `backend/`, gere o arquivo: `python -m alembic revision -m "descricao curta"` (cria `migrations/versions/<id>_descricao_curta.py`). **Não use `--autogenerate`**: o projeto escreve as migrations à mão (`target_metadata = None`).
2. Preencha `upgrade()` e `downgrade()` com `op.create_table`, `op.add_column`, `op.execute(...)` etc. Prefira SQL idempotente (`IF NOT EXISTS`) quando mexer em tabela que já existe em produção, e nunca apague dados sem decisão explícita.
3. Confira o SQL: `python -m alembic upgrade head --sql`.
4. Rode os testes (`python -m pytest -q`) e ajuste os testes que listam as revisões (`backend/tests/test_item_pesos.py`, `test_alembic_tem_uma_cabeca_e_a_ordem_certa`).
5. Aplique no Neon como acima, só depois de revisar.
6. Uma revisão já publicada **nunca é editada**: mudanças vão em revisão nova.

Se o app passar a usar uma coluna nova numa tabela antiga, crie a revisão correspondente; o teste `test_colunas_da_migracao_iguais_ao_esquema_do_app` avisa quando o esquema do app e o da `0003` divergem.

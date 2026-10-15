# Checklist do Projeto — Roteirização

Marque `[x]` conforme for concluindo. Um prompt por vez. Depois de cada um: revise com `git log -3 --stat`, depois `!git push`, espere o deploy no Render e teste no site.

## Regras de ouro
- Tudo gratuito (Neon, Render, Vercel, GitHub, OR-Tools, IBGE).
- Nunca cole senha ou string de banco no chat. Use só `$env:DATABASE_URL = "..."` no terminal.
- Nas etapas grandes, use o modo plano (Shift+Tab) e leia o plano antes de aprovar.
- Ao fim de cada etapa, o Claude Code atualiza `docs/STATUS_E_PLANO_ATUALIZADO.md`.

---

## ✅ Já feito
- [x] Etapa 0 — Banco permanente (Neon)
- [x] Etapa 1 — Login e operadores
- [x] Etapa 2 — CEP/raio sem CEPs inventados
- [x] Etapa 2b, fase 1 — 76 faixas de CEP unificadas (10 estados), testado em produção
- [x] Etapa 2b, fase 2 — Acre: CNEFE por prefixo de CEP gravado no Neon (45 prefixos)
- [x] Etapa 2b, passos 1 e 2 — `localidade` (bairro), tabela de municípios do IBGE e código IBGE fixo corrigido
- [x] Etapa 2b — municípios, faixas com `ibge`, AC e DF gravados no Neon (`cep_prefixos` 800 linhas, `ibge_municipios` 5.571)
- [x] **Etapa 2b concluída** — CEPs do Brasil inteiro (IBGE/CNEFE): 27 UFs, ~24,6 mil prefixos, ~4 MB no Neon; cobertura por prefixo com Total/Parcial validada no site; faixas manuais e fallback removidos
- [x] Limpezas: requirements em UTF-8, senhas fora do código, código morto removido, CLAUDE.md
- [x] Mapa com tema único escuro (azul-marinho), sem seletor Escuro/Claro (15/10/2026): O **mapa tem um único tema, escuro (azul-marinho)**, sem seletor Escuro/Claro (decisão de 15/10/2026: o tema Claro foi testado e ficou ruim, então foi removido, com a escolha guardada no navegador, a paleta e o filtro do Claro e o ajuste de cores de rota por tema). Esri em cinza escuro (base e rótulos), sem chave de API e com a atribuição; o tom azul-marinho vem de um filtro de CSS só nos blocos do mapa; as rotas usam as cores que vêm do servidor, que já contrastam com o fundo; o estilo fica em `frontend/src/services/estiloMapa.js`.

---

## ✅ Etapa 2b — CEPs do Brasil inteiro (IBGE/CNEFE) — concluída

- [x] **Registrar a fase 1 como validada**
```
Atualize docs/STATUS_E_PLANO_ATUALIZADO.md marcando a fase 1 da Etapa 2b como validada em produção: Neon com 76 faixas carregadas, cobertura testada na Av. Paulista (24 CEPs) e na Av. Atlântica (6 CEPs), e Florianópolis (sem faixas) retornando o aviso correto. Faça commit sem push.
```

- [x] **Fase 2 — teste com o Acre** (leia o resultado antes de gravar no Neon)
```
Execute a fase 2, só com o Acre: script offline que baixa o CNEFE do AC, calcula a mediana por prefixo de 5 dígitos (com n_enderecos e dispersão) e grava com upsert no banco apontado pela variável DATABASE_URL, sem gravar a string em arquivo. Rode primeiro em um SQLite local e me mostre o resultado. Só grave no Neon depois que eu confirmar.
```
  Depois de confirmar: no PowerShell, defina `$env:DATABASE_URL`, rode o comando que o Claude Code indicar e confira o tamanho no Neon.
  - [x] Conferir o tamanho de `cep_prefixos` no Neon (`pg_total_relation_size`): ~4 MB com as 27 UFs.

- [x] **Fase 2b, passos 1 e 2 — `localidade`, municípios do IBGE, código IBGE** (feito no código; testes passando)
- [x] **Gravar no Neon: municípios, faixas (agora com `ibge`), AC (agora com `localidade`) e DF.** No PowerShell, na raiz do projeto (a string do banco só na sessão, nunca em arquivo ou no chat):
```
$env:DATABASE_URL = "<string do Neon>"
python scripts/carregar_municipios.py
python scripts/carregar_faixas.py
python scripts/carregar_cnefe.py --uf AC
python scripts/carregar_cnefe.py --uf DF
Remove-Item Env:DATABASE_URL
```
  Rode isto **antes** do `git push`: assim o app já encontra os códigos IBGE ao subir.
- [x] **Passo 3 — trocar a consulta de `ceps_reais` para `cep_prefixos`** (implementado, commit local; decisões: só prefixos com centro dentro do raio, Total/Parcial pela dispersão, faixas manuais = Parcial enquanto a UF não tiver prefixos, coluna "Cobertura" por último no XLSX, legenda e fonte na aba "Cobertura e fonte", bairro em Title Case, prazo de 1 dia até 12 km)
- [x] **Conferir o passo 3 no Neon e fazer o push.** Conferência feita (somente leitura, só SELECT): DF 671 (639 Total, 32 Parcial), Av. Paulista 24, Av. Atlântica 6, Florianópolis 0, Rio Branco 22. Push feito em `960ef8c`. Comando usado:
```
$env:DATABASE_URL = "<string do Neon>"
python scripts/conferir_cobertura.py
Remove-Item Env:DATABASE_URL
```
- [x] **Validar o passo 3 no site:** Av. Paulista (24, todas "Parcial", sem fonte), Praça dos Três Poderes (682: 649 Total, 33 Parcial, com fonte), Florianópolis com aviso, XLSX com a coluna "Cobertura" por último e a aba "Cobertura e fonte".
- [ ] **Testar a importação do XLSX na transportadora** — antes do primeiro uso real (o sistema ainda está em produção sem uso real).
- [x] **Investigar os 3 prefixos de fronteira descartados** (PB 59225 legítimo mas sem efeito prático; MA 68527 inconsistente; BA 49117 erro de digitação): regra de descarte mantida, sem carga adicional. Detalhes no STATUS.
- [x] **Legenda do XLSX** diz que a distância (Raio X km) é em linha reta entre o hub e o centro do prefixo, não por estrada.
- [x] **Mensagens de tela sem termos técnicos** (aviso de região sem cobertura em linguagem do operador; sem nome de tabela, script, arquivo, API ou serviço nas mensagens da cobertura).

- [x] **Preparar a carga do Brasil inteiro** (script pronto e testado com SP, a maior UF: 22,95 milhões de endereços, pico de memória de 571 MB, 201 s; apaga o download de cada UF; para sozinho se a tabela passar de 100 MB)
- [x] **Repetir o SP no Neon** (a 1ª tentativa falhou ao gravar: conexão ociosa derrubada pelo Neon; já corrigido, a conexão agora só abre para gravar e reconecta até 3 vezes). Mesmo procedimento, só com o SP (o arquivo baixado foi guardado):
```
$env:DATABASE_URL = "<string do Neon>"
python scripts/carregar_cnefe.py --uf SP
Remove-Item Env:DATABASE_URL
```
- [x] **Rodar a carga do Brasil inteiro no Neon, uma UF por vez** (concluída: 27 UFs) *(as UFs menores já foram gravadas na 1ª execução; confira com `scripts/conferir_cobertura.py`, que lista as UFs com prefixos no banco)* (as maiores são SP ~1 GB, MG, BA e RJ; estimativa de ~4 MB no banco). No PowerShell, na raiz do projeto (a string do banco só na sessão, nunca em arquivo ou no chat):
```
$env:DATABASE_URL = "<string do Neon>"
python scripts/carregar_cnefe.py --todas --pular AC DF
Remove-Item Env:DATABASE_URL
```
  AC e DF já estão no Neon e são pulados. Se interromper, repita o comando acrescentando as UFs já feitas em `--pular`. Depois: me mande a saída (ou o resumo final) e conferimos o tamanho no Neon.
- [x] **Fase 2 — Brasil inteiro (prompt original, substituído pelos dois itens acima)**
```
O Acre foi validado. Rode o Brasil inteiro, uma UF de cada vez, medindo o tamanho da tabela no banco ao final de cada UF. Pare e me avise se passar de 100 MB no total. Faça commit sem push.
```

- [x] **Fase 3 — completar com a BrasilAPI e usar o IBGE por município como último recurso** *(código IBGE fixo corrigido e tabela de municípios feitos; BrasilAPI sob demanda e centroides de município **não foram necessários** com a base nacional completa: ficam como melhoria futura)*
```
Execute a fase 3 do plano da Etapa 2b: completar CEPs ausentes com a BrasilAPI v2 sob demanda, gravando no cache com precisao='brasilapi', e usar os centroides de município do IBGE como último recurso. Corrija também o código IBGE fixo (3550308) em database.py. Sem push.
```
  *(O código IBGE fixo já foi corrigido nos passos 1 e 2; a tabela de municípios do IBGE também já existe.)*

- [x] **Fase 4 — limpeza e atribuição** *(concluída: faixas manuais, `ceps_reais` no app, `faixas_cep.py`, `carregar_faixas.py` e o CSV removidos; atribuição "Fonte: IBGE, CNEFE 2022" na aba "Cobertura e fonte" e na tela. A tabela `ceps_reais` segue no Neon, sem uso, e pode ser apagada quando quiser.)*
```
Execute a fase 4: remova as faixas manuais que o CNEFE já cobre, e coloque "Fonte: IBGE, CNEFE 2022" nas exportações. Atualize o STATUS. Sem push.
```
  *(A atribuição "Fonte: IBGE, CNEFE 2022" nas exportações entra junto com o passo 3, porque só a consulta nova usa dados do CNEFE.)*
- [ ] Conferir o termo de uso do CNEFE no site do IBGE, antes de entregar tabelas a clientes.

---

## ✅ Etapa 3 — Backup automático (GitHub Actions)
*(Concluída e validada em 13/10/2026. Passo a passo, restauração e troca da senha: `docs/BACKUP.md`.)*
- [x] Workflow `.github/workflows/backup.yml` (commit `4497471`): roda todo domingo 06:00 UTC e manualmente; `pg_dump` 18 com `--format=custom --no-owner --no-privileges`; confere tamanho (mínimo 100 KB) e as tabelas `operadores` e `cep_prefixos`; criptografa com `gpg` (AES256), apaga o dump em claro e guarda só `backup-neon-AAAAMMDD.dump.gpg` por 30 dias.
- [x] Secrets `DATABASE_URL` (string direta do Neon) e `BACKUP_PASSPHRASE` criados no GitHub.
- [x] **Validado no GitHub:** a execução #1 rodou; o artifact `.gpg` foi baixado e descriptografado com a senha do backup; o resultado é um dump PostgreSQL válido (~774 KB, cabeçalho `PGDMP`).
- [ ] **Não testado ainda:** a restauração completa em um banco novo (`pg_restore` numa branch do Neon, conforme `docs/BACKUP.md`). Recomendado fazer uma vez; backup que nunca foi restaurado não é garantia.
- [ ] Lembrar: o GitHub desativa workflows agendados após 60 dias sem atividade no repositório; conferir a aba Actions de tempos em tempos.

---

## ✅ Etapa 4 — Migrations e rotas protegidas
*(Concluída e validada em produção em 13/10/2026. Comandos: `docs/MIGRATIONS.md`.)*
- [x] **Parte 1 — Alembic nas tabelas antigas:** revisão `0003_tabelas_antigas` com `CREATE ... IF NOT EXISTS` para `operadores`, `geocode_cache`, `cep_prefixos` e `ibge_municipios` (sem `DROP`, `TRUNCATE` nem `DELETE`; no Neon não altera nada). `docs/MIGRATIONS.md` explica criar migration, aplicar, `--sql`, `current`/`stamp` e aplicar no Neon pela variável `DATABASE_URL`. Não existe tabela `geocache` (era o arquivo de teste `geocache.db`).
- [x] **Parte 2 — Rotas protegidas por login (JWT):** `/api/upload`, `/api/otimizar`, `/api/otimizar/status/{id}`, `/api/cobertura-ceps`, `/api/exportar-tabela-frete-xlsx`, `/api/modelo-xlsx` e `/api/modais`; `/api/item-pesos/*` e `/api/auth/me` já eram protegidas. Abertas só `/api/auth/login` e `/api/auth/register` (que continua exigindo o código de convite). Não existe rota de saúde; `/docs`, `/redoc` e `/openapi.json` (automáticas do FastAPI) continuam abertas.
- [x] **Frontend:** o modelo XLSX agora baixa com o token (antes era `window.open`, sem token); qualquer resposta 401 limpa a sessão e volta ao login com o aviso "Sua sessão expirou. Entre novamente.". `npm test` (6 testes do tratamento do 401, com o `node --test` do Node) e `npm run build` passam.
- [x] **Testes:** `test_rotas_protegidas.py` (para cada rota: sem token 401, token inválido 401, token válido passa; token vencido, operador inativo e inexistente; login e cadastro abertos; toda rota `/api` exige login) e `test_migracao_tabelas_antigas.py` (idempotente, nada apagado, igual ao esquema do app). Suíte do backend: 228 passam.
- [x] **`0003` aplicada no Neon:** `alembic current` = `0003` (a `0002`, que cria `item_pesos`, veio junto).
- [x] **Validado no site:** `/api/modelo-xlsx` sem login devolve 401 (rotas de negócio protegidas) e a tela "Pesos dos itens" carrega.
- [ ] Conferir quando houver oportunidade (não foi citado na validação): o fluxo completo logado (cobertura, upload, roteirização, baixar o modelo e exportar o XLSX) e, com a sessão vencida, o retorno ao login com o aviso.

Prompt original (para referência):
```
1) Configure Alembic no backend com migration inicial refletindo os models atuais (operadores, ceps_reais etc.), sem apagar dados existentes. Documente os comandos.
2) Proteja com o token JWT (get_current_operador) todos os endpoints de negócio: /api/upload, /api/otimizar, /api/otimizar/status, /api/cobertura-ceps, /api/exportar-tabela-frete-xlsx e /api/modelo-xlsx. Deixe abertos só login e register. Confirme que o frontend já envia o token e trate 401 deslogando o usuário.
3) Escreva testes para isso e rode-os.
```

## ✅ Etapa 5 — Motoristas e veículos
*(**Concluída e validada (15/10/2026).** Migrations aplicadas no Neon em 15/10/2026 (`alembic current` = `0006`, o que inclui a `0004` e a `0005`) e uso validado no site: seleção de motoristas na roteirização e rotas confirmadas funcionando. Tabelas `tipos_veiculo` (nome, `custo_rota`, `peso_referencia_kg` opcional, ativo, quem alterou e quando; já nasce com "Carro de passeio" R$ 130 e "Fiorino/Utilitário" R$ 260) e `motoristas` (nome, tipo de veículo, ativo, quem alterou e quando), criadas pela revisão `0004` (idempotente, sem `DROP`/`TRUNCATE`/`DELETE`; `alembic upgrade head --sql` conferido, **não aplicada**). Rotas protegidas por login: `GET/PUT /api/tipos-veiculo` e `GET/POST/PUT /api/motoristas` (qualquer operador logado edita; motorista **não é apagado**, é desativado com `ativo = false`). Tela "Motoristas e veículos" (botão no cabeçalho): listar, criar, editar, ativar/desativar motoristas e editar o custo e o peso de referência de cada tipo. **Valor da rota = valor base do tipo de veículo (ou o valor informado na roteirização), por rota/viagem**; combustível (R$/L) e custo-hora saíram da tela e do cálculo (`costs.py` reescrito: `calcular_custo_rota`). A frota gerada ("Motorista 01") saiu: `POST /api/otimizar` usa os motoristas ativos do cadastro e, sem nenhum, responde 422 com "Não há motoristas cadastrados. Cadastre pelo menos um motorista...". O peso de referência só é guardado e editado: **não é limite e nunca bloqueia nem avisa**; o motor ainda não o usa (Etapa do OR-Tools). O teto de pedidos por viagem do agrupamento atual continua no painel "Capacidades Máximas por Modal" (2 tipos). Testes: 301 no backend passam, `npm test` e build ok; nada depende do `psycopg2`.)*
- [x] **Código, testes e build** (commit local, sem push).
- [x] **Aplicar as migrations `0004` e `0005` no Neon** (feito em 15/10/2026, junto com a `0006`) (você roda; backup antes; ver `docs/MIGRATIONS.md`): `alembic current` (deve mostrar `0003`) → `upgrade head --sql` (revisar) → `upgrade head` → `current` (deve mostrar `0005`). A `0004` já cadastra os dois tipos de veículo; a `0005` acrescenta a coluna do valor próprio do motorista.
- [x] **Validado no site (15/10/2026, junto com a Etapa 5b):** abrir "Motoristas", cadastrar um motorista, editar, desativar e reativar; editar o valor base e o peso de referência; gerar rotas com os campos de valor vazios e conferir R$ 130 (carro) e R$ 260 (Fiorino/Utilitário) com origem "padrão"; digitar um valor só para o utilitário (ex.: 300,50) e conferir que só as rotas dele mudam, com origem "informado"; com todos desativados, a mensagem pedindo o cadastro.
- [x] **Valor por rota informado na roteirização (ajuste de 14/10/2026, commit local sem push):** **Regra do valor por rota (14/10/2026):** o valor cadastrado em "Motoristas e veículos" (R$ 130 passeio, R$ 260 utilitário) é o **valor base**. Na tela de roteirização há um campo opcional por tipo ("Valor por rota, Passeio" e "Valor por rota, Utilitário"), vazio por padrão, com o valor base como dica ("padrão R$ 260,00"); aceita vírgula decimal. Campo vazio usa o valor base; o valor informado vale para todas as rotas daquele tipo nesta execução (os tipos são independentes); **zero é aceito se digitado de propósito**; negativo ou texto devolve 422 com mensagem em linguagem do operador. `POST /api/otimizar` aceita `valores_por_rota` (opcional, por nome do tipo) e o resultado traz, em cada rota (`valor_rota`, `origem_valor`) e no resumo (`kpis.valores_por_tipo`), o valor usado e a origem ("informado" ou "padrão"), mostrados na tabela de rotas, no balão do mapa e no cartão de custo. O romaneio (.csv) e as exportações da cobertura não têm coluna de custo hoje, então nada mudou neles; quando o romaneio ganhar custo (Etapa 13), levar o valor e a origem. **Evolução prevista (Etapa 6, lojas): o valor de cada loja por tipo de veículo preencherá esse campo automaticamente** (o operador ainda poderá trocá-lo). Testes: 322 no backend, 13 no frontend (`npm test`), build ok. A migration `0004` e o banco não mudaram.
- [x] **Valor próprio por rota do motorista (14/10/2026):** cada motorista pode ter um valor próprio por rota, opcional e editável a qualquer momento (por exemplo, quando ele muda de loja); vazio = usa o valor base do tipo. Coluna `motoristas.valor_rota` (NUMERIC(10,2), NULL, `CHECK (valor_rota IS NULL OR valor_rota >= 0)`) pela **revisão `0005`** (a `0004` já tinha sido publicada e não foi editada; `0005` é idempotente, `ADD COLUMN IF NOT EXISTS`, sem `DROP`/`TRUNCATE`/`DELETE`; SQL conferido com `--sql` e testado em SQLite rodando duas vezes; **não aplicada no Neon**). As rotas de motoristas aceitam e devolvem `valor_rota` (vírgula decimal; negativo ou texto = 422 em linguagem do operador; zero vale se digitado; no `PUT`, campo ausente mantém o valor e vazio o apaga), e a tela "Motoristas e veículos" tem o campo "Valor próprio por rota (opcional)" com a dica "Vazio usa o valor base" e o valor base do tipo ao lado. **Prioridade do valor da rota, do mais específico ao mais geral: (a) valor digitado na roteirização para o tipo de veículo (nesta execução); (b) valor próprio do motorista; (c) valor base do tipo.** A origem aparece em cada rota e no resumo: "informado nesta roteirização", "valor do motorista" ou "padrão" (no resultado: `origem_valor` = `informado`, `motorista` ou `padrão`; o resumo `kpis.valores_por_tipo` agrupa por tipo, valor e origem). Testes: 343 no backend, 16 no frontend (`npm test`), build ok.
- [x] **Aplicar a migration `0005` no Neon** (junto com a `0004`, se ainda não aplicada: `alembic upgrade head` roda as duas em sequência; backup antes; `alembic current` deve mostrar `0005`).
- [x] **Publicar frontend e backend juntos:** o frontend novo não envia mais a frota nem combustível/hora; o backend novo ignora esses campos de um frontend antigo, mas sem motoristas cadastrados não gera rotas.

Prompt original (para referência):
```
Implemente o cadastro de motoristas e veículos:
- Tabela motoristas (nome, tipo_veiculo, ativo) via Alembic. Tipos: "Carro de passeio" (R$130 por rota) e "Fiorino/Utilitário" (R$260 por rota), em uma tabela ou enum de configuração.
- CRUD protegido por token e tela de cadastro no frontend.
- O custo de rota passa a ser o valor base do veículo (em 15/10/2026 isso mudou: o R$ 260 é a DIÁRIA do motorista, não o preço da rota; ver a Etapa 5b); remova os campos de combustível (R$/L) e custo-hora da UI e do cálculo (reescreva costs.py e seus testes).
- Cada tipo de veículo ganha o campo opcional peso_referencia_kg ("peso de referência (kg)"), que pode ficar em branco ("sem referência"). Ele NÃO é limite: é só um guia para o motor de roteirização.
- Troque a frota gerada ("Motorista 01") em main.py pelos motoristas cadastrados.
Rode os testes e o build do frontend. Sem push.
```

## ✅ Etapa 5b — Rotas realizadas, escolha dos motoristas e diária
*(**Concluída e validada (15/10/2026).** Migrations aplicadas no Neon em 15/10/2026 (`alembic current` = `0006`, o que inclui a `0004` e a `0005`) e uso validado no site: seleção de motoristas na roteirização e rotas confirmadas funcionando. Tabela `rotas_realizadas` (id, `execucao_id` que agrupa as rotas de uma confirmação, `numero_rota`, `motorista_id` → `motoristas.id`, `data` em America/Sao_Paulo, `loja_hub`, `turno` opcional, `qtd_pedidos`, `distancia_km`, `status` `confirmada`/`cancelada`, `criado_em`, `criado_por`), revisão `0006` idempotente (`IF NOT EXISTS`, sem `DROP`/`TRUNCATE`/`DELETE`; SQL conferido com `--sql`, **não aplicada**); chave única `execucao_id` + `numero_rota` (confirmar de novo não duplica). **Escolha dos motoristas:** no painel esquerdo a lista vira um campo de escolha múltipla com os motoristas ATIVOS no formato "João - Utilitário - 1 rota realizada hoje" ("nenhuma rota hoje" quando zero); só os marcados entram na roteirização (isso não ativa nem desativa ninguém na tela "Motoristas"); o botão de executar só habilita com pelo menos um motorista marcado, com a mensagem "Marque pelo menos um motorista para gerar as rotas."; a capacidade por saída simultânea considera só os marcados; `POST /api/otimizar` recebe `motorista_ids` e recusa ids inativos ou inexistentes com 422 em linguagem do operador. **Confirmar rotas:** botão no resultado grava uma rota por viagem com o motorista de cada rota (`POST /api/rotas-realizadas/confirmar`) e mostra "João: +2 rotas (total hoje: 3)"; repetir não duplica; "Desfazer confirmação" (`POST /api/rotas-realizadas/{execucao_id}/desfazer`) marca como cancelada sem apagar; só as confirmadas contam (`GET /api/rotas-realizadas/hoje`). O resumo mostra "N rotas (M motoristas)" com os motoristas realmente usados. **R$ 260 é a diária, não o preço da rota:** saíram do painel de roteirização os campos "Valor por rota", o cartão "Custo estimado" e as colunas de custo da tabela de rotas (entrou o cartão "Rotas por motorista": quantas nesta roteirização e quantas hoje); na tela "Motoristas e veículos" o campo "Valor próprio por rota" ficou escondido (a coluna `valor_rota` continua no banco, sem uso) e "Valor base por rota" virou "Diária base" ("Valor da diária do motorista"). O código de cálculo antigo (`costs.py`, `valores_por_rota`) segue no backend sem uso na tela. Testes: 380 no backend (SQL de verdade em SQLite para contagem por dia em Brasília, inclusive 23h, só confirmadas contam, confirmação repetida e desfazer) e 34 no frontend; build ok.)*
- [x] **Código, testes e build** (commit local, sem push).
- [x] **`0006` aplicada no Neon** (15/10/2026; `alembic current` = `0006`). (você roda; backup antes; `alembic upgrade head` roda a `0004`, `0005` e `0006` em sequência, se ainda faltarem; `alembic current` deve mostrar `0006`).
- [x] **Validado no site (15/10/2026):** seleção de motoristas na roteirização e rotas confirmadas funcionando. Roteiro usado: marcar motoristas e gerar rotas; conferir que só os marcados aparecem; tentar executar sem nenhum marcado (botão desabilitado e mensagem); confirmar as rotas e ver "João: +N rotas (total hoje: M)"; confirmar de novo e ver que não duplica; desfazer e ver que a contagem volta; na tela "Motoristas e veículos", conferir "Diária base" e que o valor próprio não aparece.
- [x] **Publicar frontend e backend juntos:** o frontend novo envia `motorista_ids` (o backend novo recusa pedido sem motoristas marcados, e um frontend antigo não os envia).
- [x] **Confirmar e desfazer na tela (comportamento esperado):** depois de confirmar, o botão "Confirmar rotas" vira "Desfazer confirmação", então a **tela impede confirmar duas vezes**. A proteção do servidor contra duplicidade (chave única `execucao_id` + `numero_rota`) **não é visível na tela**: ela é testada automaticamente (confirmar o mesmo resultado de novo não grava nada a mais).
- [x] **Limite conhecido:** o resultado da roteirização fica **na memória do servidor** (no Render, plano gratuito). **Se o Render reiniciar (ou dormir e acordar), o resultado se perde e é preciso gerar as rotas de novo** antes de confirmar; a tela avisa "Este resultado não está mais disponível. Gere as rotas de novo.". Rotas já confirmadas ficam gravadas no banco e não se perdem.
- [ ] **Desativar os motoristas de teste** criados durante a validação (tela "Motoristas e veículos" → Desativar; o cadastro não apaga motorista). Enquanto estiverem ativos, aparecem na escolha da roteirização; as rotas de teste que já foram confirmadas continuam contando no "hoje" do dia em que foram feitas.

**Regra de negócio (para a Etapa 6, lojas — NADA disso está implementado agora, não há cálculo de pagamento):** o valor de **R$ 260 (Fiorino/Utilitário; o de passeio é R$ 130) é a DIÁRIA do motorista, não o preço de cada rota**. A diária cobre normalmente **4 rotas** (varia por loja). O **pagamento é proporcional às rotas feitas: diária × rotas feitas ÷ rotas por diária** (ex.: diária 260 com 4 rotas por diária, cada rota vale 65; 5 rotas pagam 325; 3 pagam 195). A **diária (por tipo de veículo) e as rotas por diária são definidas por loja** (em branco usa a diária base e 4 rotas). **No lugar do valor próprio do motorista, o cadastro de motoristas ganha a escolha das lojas em que ele trabalha (várias)**, que também filtra a lista de motoristas ao escolher o hub. **Cada rota confirmada vale a diária da loja onde saiu dividida pelas rotas por diária daquela loja.** Só contam as rotas **confirmadas** (tabela `rotas_realizadas`); o dia é o de America/Sao_Paulo.

## 🟨 Etapa 6a — Lojas, hub no mapa e Raio X km
*(**Pronta no código (16/10/2026), falta aplicar a migration `0007` no Neon, carregar as lojas e validar no site.** **Tabela `lojas`** (revisão `0007`, idempotente, sem `DROP`/`TRUNCATE`/`DELETE`; SQL conferido com `--sql`, **não aplicada**): `id`, `nome` (já inclui a filial, ex.: "Atacadão Guarujá"; **sem coluna filial**), `uf` (opcional), `endereco` (opcional), `lat`, `lng` (CHECK Brasil: latitude -34 a 6, longitude -74 a -34), `ativo`, `capacidade_peso` e `capacidade_volume` (opcionais, só informativas, nunca bloqueiam), janelas manhã 08-13, tarde 13-18 e noite 18-21 (noite pode não ser usada), `atualizado_em`, `atualizado_por`; **nome único** (sem diferença de maiúsculas/espaços, inclusive desativadas); loja **não é apagada, é desativada**. **Script `scripts/carregar_lojas.py`:** CSV em `data/lojas/` (**no `.gitignore`**: o repositório é público) com Nome, Estado, Endereço, Latitude e Longitude (endereço pode ficar em branco) ou o formato Google My Maps (WKT `POINT (longitude latitude)`, name, description; sem Estado, a loja entra sem UF e o operador completa na tela); aceita vírgula decimal ("-23,5614"), aspas, separador `,` ou `;`, UTF-8 ou Windows-1252; valida o Brasil e **avisa lojas com latitude e longitude trocadas (não são gravadas)**; resumo antes de gravar (válidas, sem endereço, sem Estado, duplicadas, coordenada suspeita) e só grava com `--gravar` e confirmação digitada; asyncpg, `DATABASE_URL` só por variável de ambiente, upsert por nome sem sobrescrever o que um operador editou na tela. **Tela "Lojas"** (botão no cabeçalho, protegida): listar, criar, editar, ativar/desativar, com validação de latitude/longitude (Brasil, valores trocados) e mensagens em linguagem do operador; rotas `GET/POST /api/lojas` e `PUT /api/lojas/{id}` (sem exclusão), com quem alterou e quando. **Mapa permanente:** todas as lojas ativas aparecem como marcadores; **hover** com nome, endereço e UF, uma informação por linha e só o que existir; **clique escolhe o hub** (marcador com borda verde) e **recalcula a cobertura e as faixas de CEP pela coordenada cadastrada, sem geocodificar o endereço**; botão **"Raio X km"** ao lado do nome da loja, com raio configurável (1 a 200 km, padrão 30); estilo escuro mantido. **Endereço livre do hub:** continua como a opção **"Outro endereço"** do seletor de loja (aparece sozinho se não houver nenhuma loja cadastrada) e funciona como antes; com loja escolhida, o **`loja_hub` gravado em `rotas_realizadas` é o nome da loja**. Cidade e código IBGE do hub vêm da cidade + UF cadastradas na loja (ver o ajuste de 16/10/2026 abaixo); sem elas, do prefixo de CEP mais próximo (a menos de 10 km), com aviso; se não houver, ficam vazios (nunca inventados). Trocar de loja com rotas ainda não confirmadas pede confirmação. Testes: 459 no backend (SQL real em SQLite para unicidade, desativar e upsert) e 45 no frontend; build ok (depois do ajuste de cidade: 498 e 47). Também corrigi a cor da atribuição e dos botões de zoom do mapa, que o CSS do Leaflet sobrepunha.)*
- [x] **Código, testes e build** (commit local, sem push).
- [x] **Correção de desempenho (16/10/2026): o mapa NÃO desenha mais um marcador por faixa de CEP** (eram milhares e travavam o site). O mapa mostra só as lojas, o hub, os círculos de raio e as rotas; o hover e o popup das faixas deixaram de existir e o mapa nem recebe mais a lista de faixas (o enquadramento passou a usar o raio escolhido). **Continuam intactos:** o cálculo da cobertura, o painel com as contagens (faixas, Total e Parcial, fonte, avisos), a lista de faixas guardada na tela para a exportação e as exportações CSV e XLSX, que seguem com todas as faixas de CEP. Medido (Chrome sem interface, 4.000 faixas em torno da Av. Paulista): antes, escolher a loja levava cerca de 0,9 a 1,3 s e trocar de loja cerca de 1,0 a 1,7 s, com 4.002 marcadores no DOM; depois, 27 a 34 ms com 2 marcadores. No servidor, com o banco simulado, a cobertura de 4.000 faixas leva cerca de 180 ms de processamento e a resposta tem 1,2 MB (64 KB compactada); o tempo da consulta SQL no Neon não foi medido (não conecto no banco). **Feito depois (16/10/2026):** o backend compacta as respostas a partir de ~1 KB (`GZipMiddleware`, `minimum_size=1000`; a cobertura de 4.000 faixas cai de 1,2 MB para ~64 KB), com o CORS e os downloads XLSX conferidos por teste (o CSV é gerado na própria tela, não passa pelo servidor); e o endpoint `/api/cobertura-ceps` registra no log do servidor uma linha por consulta com `total_ms`, `sql_ms` (tempo da consulta SQL), `faixas`, `modo` (loja ou endereço) e o raio, sem nome, endereço, e-mail nem string de conexão. **Para medir o SQL no Neon:** olhar essas linhas no log do Render depois de escolher uma loja grande.
- [x] **Ajuste de 16/10/2026 (cidade e cabeçalhos do CSV real; vale no lugar do que está dito acima sobre colunas e IBGE):** a tabela `lojas` ganhou a coluna **`cidade`** (opcional), acrescentada na própria revisão `0007`, que ainda não tinha sido enviada ao GitHub nem aplicada no Neon (se ela já tivesse sido aplicada, o caminho seria uma `0008` com `ADD COLUMN IF NOT EXISTS`). **O CSV real** tem as colunas, nesta ordem, **Nome, UF, Endereço Completo, Cidade, Latitude, Longitude**; o script reconhece os cabeçalhos **por nome** (a ordem não importa), sem diferença de maiúsculas, acentos ou espaços: Nome; UF ou Estado; Endereço, Endereco ou Endereço Completo; Cidade (ou Município); Latitude ou Lat; Longitude, Lng ou Lon. As coordenadas podem vir com ponto ou vírgula decimal. O resumo mostra **quais colunas foram reconhecidas** (e as que não foram achadas) e **quantas lojas estão sem cidade e sem endereço**. **Hover:** o endereço aparece **sem o ", Brazil" ou ", Brasil" do final** (o dado guardado não muda). **Tela "Lojas":** mostra e edita a cidade. **Código IBGE do hub** (usado na exportação onde o ponto de CEP não tem o seu) **vem de cidade + UF**, buscando na lista de municípios do IBGE (nome sem acento e sem diferença de maiúsculas; a mesma cidade em outro Estado não vale); se a cidade estiver vazia, sem Estado ou não for encontrada, vale o prefixo de CEP mais próximo (a menos de 10 km) e o operador é **avisado** no painel da cobertura; se nem isso houver, fica em branco. Testes: 498 no backend e 47 no frontend; build ok.
- [ ] **Aplicar a migration `0007` no Neon** (já com a coluna `cidade`) (você roda; backup antes; `alembic current` deve mostrar `0006` → `upgrade head --sql` (revisar) → `upgrade head` → `current` deve mostrar `0007`).
- [ ] **Carregar as lojas:** exportar a lista em CSV para `data/lojas/` (fora do git), rodar `python scripts/carregar_lojas.py --csv data/lojas/<arquivo>.csv` (só o resumo), conferir as lojas com coordenada suspeita/trocada e, se estiver certo, `--gravar` (com `$env:DATABASE_URL` só na sessão).
- [ ] **Validar no site depois do deploy:** ver as lojas no mapa; passar o mouse (nome, endereço e UF, uma informação por linha); clicar numa loja (hub com borda verde e cobertura recalculada sem digitar endereço); mudar o raio e usar "Raio X km"; gerar rotas partindo da loja e confirmar que o `loja_hub` é o nome da loja; desativar uma loja e ver que some do mapa; "Outro endereço" ainda funciona.
- [ ] **Publicar frontend e backend juntos** (o frontend novo envia `loja_id`).

**Etapa 6b (NÃO implementada na 6a): motorista por loja, diária por loja, rotas por diária e pagamento.** Regra de negócio já registrada acima (Etapa 5b): a diária cobre normalmente 4 rotas (varia por loja); pagamento = diária × rotas feitas ÷ rotas por diária; a diária (por tipo de veículo) e as rotas por diária são definidas por loja (em branco usa a diária base e 4 rotas); o cadastro de motoristas ganha a escolha das lojas em que ele trabalha (várias), que também filtra a lista de motoristas ao escolher o hub; cada rota confirmada vale a diária da loja onde saiu ÷ rotas por diária daquela loja.

Prompt original da Etapa 6 (para referência; vale o modelo abaixo, sem filial):
*(**Fica para a Etapa 6 (lojas), não implementado agora:** cadastro de lojas; **motorista com várias lojas**; **filtro por loja ao escolher o hub** (só os motoristas daquela loja aparecem); e **valor opcional por motorista e loja** (e por loja e tipo de veículo, que preencherá automaticamente o campo de valor na roteirização). O valor próprio atual do motorista (sem loja) é o passo anterior a isso.)*
- [ ] (fazer antes de carregar) Fora do código: exportar a lista de lojas em CSV (Google Sheets em português ou Google My Maps) com as colunas Nome, Estado, Endereço, Latitude e Longitude (endereço pode ficar em branco; a filial já vai no nome, ex.: "Atacadão Guarujá").
- **Modelo de dados e CSV de lojas (decisão de 15/10/2026; vale no lugar de qualquer menção a filial):** a **filial já faz parte do nome da loja** (ex.: "Atacadão Guarujá"), então **NÃO existe coluna `filial`** e a filial não aparece na tela nem no hover. A tabela `lojas` tem: `nome`, `uf` (Estado), `endereco`, `lat`, `lng`, `ativo`, `capacidade_peso` e `capacidade_volume` (opcionais), as janelas (manhã/tarde/noite) e os campos de auditoria (quem alterou e quando). **Hover do marcador:** nome, endereço e UF, **uma informação por linha, e só o que existir**. **CSV de importação:** colunas **Nome, Estado, Endereço, Latitude e Longitude** (endereço pode ficar em branco); aceita também o formato do **Google My Maps (WKT, name, description)**. O arquivo vem exportado do Google Sheets em português: aceitar **vírgula decimal** nas coordenadas (ex.: "-23,5614"), **células entre aspas**, separador **vírgula ou ponto e vírgula** e **UTF-8 ou Windows-1252**. **Validação:** latitude entre -34 e 6 e longitude entre -74 e -34 (Brasil); avisar no resumo se alguma loja tiver **os dois valores trocados**. **Resumo da importação:** quantas lojas estão **válidas, sem endereço, duplicadas (mesmo nome) e com coordenada suspeita**. **Nada disso está implementado agora** (a Etapa 6 ainda não começou).
```
Implemente a tabela lojas (nome, uf (Estado), endereco, lat, lng, ativo, capacidade_peso e capacidade_volume (ambas OPCIONAIS: podem ficar em branco), janelas manhã/tarde/noite com início e fim configuráveis e campos de auditoria); NÃO crie a coluna filial (a filial já faz parte do nome da loja) nem mostre filial na tela ou no hover. Crie um script para importar lojas de um CSV (colunas Nome, Estado, Endereço, Latitude e Longitude, endereço opcional; aceite também o formato WKT/name/description do Google My Maps; aceite vírgula decimal nas coordenadas, células entre aspas, separador vírgula ou ponto e vírgula e UTF-8 ou Windows-1252; valide latitude entre -34 e 6 e longitude entre -74 e -34 e avise se uma loja tiver os dois valores trocados; o resumo lista quantas lojas estão válidas, sem endereço, duplicadas (mesmo nome) e com coordenada suspeita), o CRUD em tela de admin e o mapa permanente com marcadores. O hover mostra nome, endereço e UF, uma informação por linha e só o que existir; o clique define a loja como hub (borda verde) e recalcula cobertura e faixas de CEP. Adicione o botão "Raio Xkm" ao lado do nome da loja, com raio configurável (padrão 30). Sem push.
```

## ⬜ Etapa 7 — Seleção de pedidos por loja e data
```
Implemente a lista de pedidos com checkbox, filtrada pela loja selecionada e por data. Só os pedidos marcados aparecem no mapa e entram na roteirização. Por enquanto a origem é o CSV/XLSX existente (descartado após o uso); inclua os campos ID, cliente, endereço, descrição, volume, peso, filial e janela. Crie uma camada de "fonte de pedidos" com interface única, para plugar Sheets e BigQuery depois. Mostre "Erro ao tentar encontrar endereço do pedido" quando a geocodificação falhar. Sem push.
```

## 🔄 Etapa 7b — Peso dos pedidos *(informativo: nunca bloqueia nem avisa por capacidade; o motor só o usa como guia)*

**Decisões do Diego (08/10/2026):**
1. **Ordem:** a subetapa 2 **não começa agora**. Primeiro vêm o **backup automático (Etapa 3)** e o **Alembic com rotas protegidas (Etapa 4)**, porque a tabela de pesos terá dados conferidos à mão e uma tela de edição que precisa de login e de migration.
2. **"Peso incompleto" é mostrado como mínimo**, por exemplo: "≥ 34 kg, faltam 2 itens" (ver a decisão 5).
3. **Quem mantém a tabela:** qualquer operador logado pode editar; o sistema registra **quem alterou e quando**.
4. **Janela de entrega** é outro assunto e fica em aberto.
5. **Decisão de produto (08/10/2026): o peso dos pedidos é apenas informativo.** O sistema mostra o peso de cada pedido e o total como **"≈ X kg (estimado)"**, ou **"≥ X kg, faltam N itens"** quando houver itens sem peso, e **NUNCA bloqueia nem avisa em vermelho por capacidade de veículo**. Quem decide o que o motorista leva é o operador. Ajustes por etapa:
   - **Motoristas e veículos:** cada tipo de veículo ganha o campo opcional **"peso de referência (kg)"**, que pode ficar em branco ("sem referência"). Não é limite: é só um guia para o motor.
   - **Lojas:** a capacidade por loja (peso e volume) deixa de ser obrigatória e passa a ser **opcional**.
   - **Roteirização (OR-Tools):** o motor usa o peso de referência do veículo, quando existir, **apenas como guia** para equilibrar as rotas e dividir viagens (sugestão, nunca restrição rígida). Sem referência, agrupa só por proximidade e setor. O operador pode mudar qualquer agrupamento, o sistema nunca recusa e **o motor não deixa de montar uma rota por causa do peso**.
   - **Telas:** mostrar o peso de cada pedido, o total das rotas selecionadas e o total por veículo, **sempre com o selo "estimado"** e o aviso de itens sem peso.
   - **Removidos do plano:** o aviso de 90% da capacidade e qualquer trava por peso.
6. **A pesquisa de pesos na internet foi encerrada:** rendeu pouco (**4 pesos de confiança média, 36 de baixa, 26 não achados e 34 não pesquisados**). O limite de buscas **não será aumentado** e os 34 **não serão continuados**. Próximo passo: **pedir os pesos à fonte real** (cadastro de itens do Atacadão, a operação ou pesagem) e **conferir à mão os SKUs mais vendidos**; os 4 pesos de confiança média e a revisão manual dos 36 de confiança baixa entram só como complemento.

**Decisão original:** em vez de depender da API do Atacadão (que não devolve peso), mantemos uma **tabela `item_pesos` no Neon**, com carga inicial extraída do nome do produto e **conferência manual dos itens mais vendidos**. Pedidos com itens sem peso aparecem como **"peso incompleto"** (o peso mostrado é então só um piso).

- [x] **Subetapa 1 — Estudo de viabilidade e CSV inicial** (feito, sem integrar nada, sem rede e sem tocar no banco): `scripts/estudo_peso.py` lê `data/peso/skus.csv` e `data/peso/itens_pedidos.csv` (ambos **fora do git**: o repositório é público) e gera `data/peso/item_pesos_inicial.csv` para revisão manual. Resultado com os 6.675 SKUs e 2.164 pedidos da amostra:
  - o nome traz o peso de **93,6% das unidades vendidas** (92,1% com confiança alta) e de 89,8% dos SKUs; 681 SKUs ficam sem medida;
  - mas só **39,1% dos pedidos ficam completos** (basta 1 item sem peso entre ~12 por pedido);
  - conferindo à mão os **248 SKUs** mais vendidos sem peso chega-se a 80% de pedidos completos, com **426** a 90%, com 567 a 95% e com 681 a 100%;
  - os sem peso são sobretudo contagens (un, rolos, folhas, ovos), dimensões e capacidades (saco de lixo, copo): o CSV traz esses casos em branco para você preencher.
- [ ] **Revisar o `data/peso/item_pesos_inicial.csv`** de cima para baixo (já vem ordenado por unidades vendidas): preencher os sem peso e conferir os de confiança "baixa". Para abrir no Excel em português use `python scripts/estudo_peso.py --excel` (o Excel lê "1.5" como data).
- [x] **Pesquisa de pesos na internet** (100 SKUs mais vendidos sem peso ou com confiança baixa; feita em 08/10/2026, fora do git, nada gravado no banco): `data/peso/item_pesos_pesquisa.csv`, ordenado por unidades vendidas, com peso sugerido, tipo (líquido, bruto ou estimativa), confiança (média ou baixa), link da fonte, trecho, como foi verificado e observação (inclusive o motivo de cada vazio). 40 dos 100 SKUs mais vendidos sem peso ou com confiança baixa ficaram com peso sugerido (**4 de confiança média**, conferidos em página aberta ou título claro, e **36 de confiança baixa**, em sua maioria só de resumo de busca ou de conta sobre pesos unitários); **26 foram pesquisados sem achar** e **34 ficaram com a pesquisa incompleta**, porque o limite de 200 buscas da sessão acabou. Os 40 pesos cobrem 37,8% das unidades desses 100 SKUs.
- [ ] **Revisar o `data/peso/item_pesos_pesquisa.csv`** (complemento: conferir à mão os 36 de confiança baixa abrindo o link e aproveitar os 4 de confiança média). Lições: a busca genérica cai em páginas do Tenda, Drogasil, Drogaraia, Panvel e Magalu, que não trazem peso ou dão 403; com filtro de domínios (Amazon, Mercado Livre, Carrefour, Telhanorte, Leroy Merlin, Pão de Açúcar...) o resultado da busca traz a ficha técnica, mas as páginas da Amazon, do Mercado Livre e do Carrefour abrem sem a ficha ou dão 403; Telhanorte e Pão de Açúcar abrem com a linha de peso. O WebFetch devolve um resumo, não o texto literal, então os "trechos" precisam de conferência. Nenhum EAN foi confirmado (códigos internos de loja não são EAN).
- [x] **Pesquisa na internet encerrada (decisão do Diego, 08/10/2026):** rendeu pouco (**4 pesos de confiança média, 36 de baixa, 26 não achados e 34 não pesquisados**). O limite de buscas **não será aumentado** e os 34 **não serão continuados**.
- [ ] **Pedir os pesos à fonte real:** cadastro de itens do Atacadão ou da operação (planilha com `id_sku`/código de referência e peso líquido e bruto) ou pesagem. O `data/peso/item_pesos_inicial.csv`, já ordenado por unidades vendidas, serve de lista de conferência.
- [ ] **Conferir à mão os SKUs mais vendidos** (de cima para baixo; 248 SKUs levam a 80% dos pedidos completos e 426 a 90%), com o que o Atacadão/operação mandar e, como complemento, os 4 pesos de confiança média e a revisão dos 36 de baixa da pesquisa.
- [x] **Subetapa 2 — Tabela `item_pesos`, tela de manutenção e fila "sem peso"** *(pronta no código em 09/10/2026; migration aplicada no Neon em 13/10/2026 (a tela carrega); carga inicial dos pesos concluída em 13/10/2026 (6.675 itens); o backup automático da Etapa 3 deste checklist está concluído e validado (13/10/2026), então já é seguro gravar dados conferidos à mão)*
```
Crie a tabela item_pesos no Neon via Alembic (id_sku, reference_code, nome, peso_kg, fonte, confianca, atualizado_em, atualizado_por; qualquer operador logado edita e o sistema registra quem alterou e quando), com carga a partir do CSV revisado (script com upsert, DATABASE_URL só pela variável de ambiente). Crie a tela de manutenção protegida por token: listar/editar o peso de um SKU e uma fila "sem peso" ordenada pelas unidades vendidas. SKUs novos que aparecerem nos pedidos entram na fila. Sem push.
```
  O que foi feito: **Alembic configurado** em `backend/` (usa asyncpg, porque o `psycopg2` está bloqueado pelo Windows nesta máquina; `DATABASE_URL` só pela variável de ambiente) com a revisão `0001` (ponto de partida, não altera o banco) e a `0002`, que cria `item_pesos` (`id_sku`, `reference_code`, `nome`, `peso_kg`, `fonte`, `confianca`, `atualizado_em`, `atualizado_por` e mais `unidades_vendidas`, para ordenar a fila). Rotas protegidas por login: `GET /api/item-pesos/resumo`, `GET /api/item-pesos/fila-sem-peso`, `GET /api/item-pesos` (busca por nome, código ou referência), `PUT /api/item-pesos/{id_sku}` (qualquer operador logado edita; fica registrado quem alterou e quando) e `POST /api/item-pesos/skus-vistos` (SKU novo entra na fila sem peso). Tela "Pesos dos itens" no cabeçalho do app. Script `scripts/carregar_item_pesos.py`: mostra o resumo (com peso, sem peso, inválidos) antes de gravar e só grava com `--gravar` e a confirmação digitada; aceita `;` ou `,` e vírgula decimal; ignora linhas sem peso (`--incluir-sem-peso` as põe na fila); não sobrescreve pesos editados na tela.
- [x] **Migration aplicada no Neon** (13/10/2026, junto com a `0003`; a tabela `item_pesos` existe e a tela carrega).
- [x] **Carga inicial concluída em 13/10/2026:** 6.675 itens gravados no Neon, **todos com peso**. Dos 6.675, **19 recipientes foram corrigidos à mão** (a capacidade em litros tinha sido lida como peso: caixa organizadora, mop, potes, cestos, baldes, lixeira, panela, jarras, garrafa térmica, sacos freezer, comedouro e bisnaga), com peso estimado por IA, `fonte` = `IA` e `confianca` = `baixa`.
- [ ] **Substituir pelos pesos reais:** os pesos com **fonte `IA`** ou **confiança baixa ou média** são estimativas e **devem ser substituídos quando o Atacadão ou a operação mandar os pesos reais** (a tela "Pesos dos itens" permite editar; a recarga do script não sobrescreve o que um operador editou).
- Passos usados (para referência e para futuras recargas; os passos 1 e 2 foram feitos junto com a Etapa 4):
```
# 1) Ver o SQL que será aplicado (não conecta no banco)
cd backend
python -m alembic upgrade head --sql

# 2) Aplicar a migration no Neon (a string do banco só na sessão, nunca em arquivo)
$env:DATABASE_URL = "<string do Neon>"
python -m alembic upgrade head
cd ..

# 3) Carga inicial: primeiro só o resumo (não conecta no banco)
python scripts/carregar_item_pesos.py --csv data/peso/<arquivo revisado>.csv

# 4) Gravar (mostra a previsão e pede para digitar GRAVAR)
python scripts/carregar_item_pesos.py --csv data/peso/<arquivo revisado>.csv --gravar
Remove-Item Env:DATABASE_URL
```
- [ ] **Ligar a fila aos pedidos:** hoje os pedidos (upload de planilha) não trazem SKU; quando os pedidos tiverem itens (Etapa 7 e conectores da Etapa 15), chamar `POST /api/item-pesos/skus-vistos` a cada carga para os SKUs novos entrarem na fila "sem peso".
- [ ] **Subetapa 3 — Peso por pedido, rota e veículo** *(rascunho do prompt)*
```
Calcule o peso de cada pedido (quantidade x peso do item) e mostre-o de forma apenas informativa: "≈ X kg (estimado)" ou, quando algum item não tiver peso, "≥ X kg, faltam N itens". Mostre também o total das rotas selecionadas e o total por veículo, sempre com o selo "estimado" e o aviso de itens sem peso. NUNCA bloqueie nem mostre aviso em vermelho por capacidade do veículo, e não crie aviso de 90% da capacidade: quem decide o que o motorista leva é o operador. Sem push.
```

**Perguntas:**
- ✅ **Quem mantém a tabela?** Qualquer operador logado, com registro de quem alterou e quando (decisão 3).
- ➡️ **Janela de entrega:** outro assunto, fica em aberto (decisão 4); não aparece nos dois CSVs do estudo.
- ❓ Existe outra fonte de peso? As colunas `weight` (BigQuery) e "Peso Entrega" (Sheets) do plano original trazem o peso do pedido ou do item?
- ❓ O peso deve ser **líquido** (o do rótulo, como no estudo) ou **bruto** (com embalagem)? A pesquisa de pesos na internet registra o tipo de cada peso achado (líquido, bruto ou estimativa) para ajudar nessa decisão.
- ❓ A tabela do BigQuery é **atualizada todo dia**? Isso define se SKUs novos entram na fila "sem peso" diariamente.

## ⬜ Etapa 8 — Roteirização automática (OR-Tools)  *(use o modo plano)*
```
Adicione ortools ao requirements e crie um solver VRP síncrono no FastAPI.
- Peso de referência do veículo (opcional): quando existir, o solver o usa APENAS como guia para equilibrar as rotas e dividir viagens (sugestão, nunca restrição rígida). Sem referência, agrupa só por proximidade e setor. O solver nunca deixa de montar uma rota por causa do peso, o operador pode mudar qualquer agrupamento e o sistema nunca recusa. Sem trava por peso e sem aviso de capacidade.
- Divisão automática em múltiplas viagens, priorizando setores diferentes/opostos (usando o peso de referência só como guia, quando houver); o motorista volta à loja entre viagens.
- Setores: 8 setores cardeais por azimute entre loja e pedido. Uma rota pode cobrir vários setores.
- Regra de rotação: o mesmo motorista não repete região em turnos diferentes no mesmo dia.
- Turno escolhido manualmente pelo operador.
- Tempo da rota = OSRM + tempo médio por parada (padrão 10 min, configurável).
- Distância entre paradas consecutivas.
- O botão "Executar Roteirização" só habilita com: hub escolhido, pedidos marcados, motoristas disponíveis e confirmação.
Escreva testes com 10, 20 e 40 pedidos e meça o tempo. Sem push.
```

## ⬜ Etapa 9 — Controle de duplicidade
```
Crie a tabela pedidos_roteirizados_hoje com ID do pedido, rota, motorista, turno, data e operador. Pedido já usado aparece como "já está na Rota X". Reselecionar exige confirmação em duas etapas (avisa, não bloqueia). Sem push.
```

## ⬜ Etapa 10 — Matriz de despacho
```
Na Matriz de Despacho, a coluna Motorista vem pré-preenchida com a sugestão do solver, com alternativas elegíveis clicáveis já filtradas pelas regras de rotação e disponibilidade. Sem push.
```

## ⬜ Etapa 11 — Relatórios de janela e km
```
Relatórios pós-cálculo, sem alterar o agrupamento: (a) validação de janela (loja e Delivery Window do pedido), indicando pedidos fora do prazo e o motivo; (b) limite de km por rota/motorista, com aviso "Rota X passou Y km do limite". Sem push.
```

## ⬜ Etapa 12 — Histórico
```
Crie o histórico permanente de cada roteirização (dados da matriz + data/hora + operador) com tela de consulta e filtros. Sem push.
```

## ⬜ Etapa 13 — Romaneio
```
Adicione ao romaneio .csv as colunas ID do pedido, cliente, peso (estimado, com o aviso de itens sem peso), latitude e longitude, mantendo todas as atuais. A coluna de janela de entrega fica pendente do schema do BigQuery. Sem push.
```

## ⬜ Etapa 14 — Layout novo
```
Reorganize o layout: o mapa ocupa a largura toda, os controles ficam em faixa horizontal acima, a lista de pedidos em painel retrátil sobre a borda do mapa, e as métricas (volume, rotas, extensão, custo) ficam abaixo do mapa e acima do romaneio. Sem push.
```

## ⬜ Etapa 15 — Google Sheets e BigQuery  *(depende de você)*
- [ ] Pedir ao time de dados: schema das tabelas do BigQuery e uma conta de serviço somente leitura.
- [ ] Compartilhar as planilhas do Sheets com o e-mail da conta de serviço.
- [ ] Guardar as credenciais como variáveis de ambiente no Render (nunca no GitHub).
```
Implemente conectores de pedidos para Google Sheets (links nomeados) e BigQuery (queries pré-salvas escolhidas pelo operador), ignorando o status do pedido, trazendo os últimos 3 ou 5 dias e deixando escolher a data de entrega. Use a camada de fonte de pedidos da Etapa 7. Credenciais por variável de ambiente. Sem push.
```
(Schema do BigQuery: cole junto com o prompt.)

# Memória Completa do Projeto — Evolução da Plataforma de Roteirização

> Documento gerado em 31/08/2026 para servir como contexto completo, caso a conversa
> seja perdida ou seja necessário retomar o trabalho do zero.

---

## 1. O QUE É O PROJETO

Uma **plataforma de inteligência logística e roteirização last-mile**, hoje usada
internamente pelo time de Delivery (dono do projeto: Diego). O sistema:

- Calcula áreas de cobertura por CEP a partir de um raio (usado para precificar
  serviço de entrega a lojas-cliente).
- Faz roteirização de pedidos (agrupamento de entregas por motorista/veículo),
  hoje de forma manual/rudimentar, e a evolução visa automatizar isso com um
  motor VRP (Vehicle Routing Problem).
- **Não substitui** o sistema interno que já envia rotas oficialmente aos
  motoristas — é uma ferramenta de planejamento/apoio.

### Stack técnica
- **Frontend:** React (Vite) + Tailwind + React-Leaflet (mapas), hospedado na **Vercel**.
- **Backend:** FastAPI (Python), hospedado no **Render** (plano free).
- **Banco de dados:** PostgreSQL, também no Render.
- **Roteamento:** OSRM (Open Source Routing Machine) para traçado de rota viária real.
- **Geocodificação:** BrasilAPI v2 (primária) + ViaCEP (validação cruzada) + Nominatim (OSM)
  + cache em Postgres.
- **Repositório:** `https://github.com/munizdiego12/logistica-mapa-cobertura` (público).
- **URL do backend em produção:** `https://routeflow-backend-v5ji.onrender.com/api`

---

## 2. COMO O PROJETO FUNCIONA HOJE (as-is, antes de qualquer mudança)

- Usuário digita o endereço do hub (loja central) em texto livre.
- Geocodificação: ViaCEP → Nominatim (OSM) → BrasilAPI como fallback, com cache em Postgres.
- Cálculo de raio Haversine fixo em 30km.
- **PROBLEMA CRÍTICO:** quando não encontra CEPs reais suficientes, o sistema
  substitui **silenciosamente** o resultado por 48 CEPs sintéticos distribuídos
  em 8 direções cardeais + o CEP da loja central (49 no total) — mascarando falha
  de dado como se fosse cálculo geográfico real. Isso ainda **não foi corrigido**
  (está na Etapa 2 do plano, ver seção 5).
- Upload manual de planilha de pedidos (.csv/.xlsx) — única fonte de pedidos hoje.
- Configuração de frota manual: preço do combustível (R$/L) + custo-hora do motorista.
- Roteirização via OSRM, sem VRP real (agrupamento simples por proximidade/capacidade).
- Exportação de romaneio (.csv) com: Rota, Motorista, Viagem, Veículo, Ordem_Parada,
  Endereço, Número, Bairro, CEP, Volume.
- Não existe: cadastro de motoristas, autenticação, janelas de entrega, histórico,
  controle de duplicidade de pedidos, conectores com Google Sheets/BigQuery.

---

## 3. TODAS AS REGRAS DE NEGÓCIO DEFINIDAS PARA A EVOLUÇÃO (to-be)

### 3.1 Motoristas e veículos
- Cadastro próprio de motoristas: nome + tipo de veículo (CRUD completo).
- Apenas 2 tipos de veículo por enquanto: **Carro de passeio** (R$130/rota) e
  **Fiorino/Utilitário** (R$260/rota). Caminhões e motos ficam de fora por enquanto.
- Custo de rota passa a ser **valor fixo por tipo de veículo**, eliminando os
  parâmetros de combustível (R$/L) e motorista (R$/h) usados hoje.
- Capacidade máxima por veículo varia **por loja** (não é um valor único fixo).
- Capacidade considera **combinação de peso + volume** (o que estourar primeiro).
  Os campos vêm do BigQuery (`amount`, `weight`) ou do Sheets ("Peso Entrega",
  "Volume Entrega").
- Motorista pode rodar até 3 turnos/dia (manhã, tarde, noite), por decisão própria
  — não é obrigatório.
- **Limite de km por rota/dia:** configurável por motorista/veículo. **Não interfere**
  na montagem da rota nem no VRP — é um cálculo de conferência feito **depois**.
  Se ultrapassado, mostra aviso (ex: "Rota 2 passou X km do limite") e gera
  cobrança de taxa extra à loja-cliente.

### 3.2 Precificação por CEP (função separada da roteirização)
- Ativada por um botão "Raio Xkm" ao lado do nome da loja — não interfere na
  roteirização de pedidos.
- Raio configurável pelo operador (inicial: 30km).
- **Eliminar o fallback sintético dos 48 CEPs cardeais.** Calcular geograficamente
  os CEPs reais dentro do raio. Se não conseguir geolocalizar algum CEP, o sistema
  **informa isso explicitamente**, nunca substitui silenciosamente.
- Fonte de geolocalização: **BrasilAPI v2 como primária** (já resolve fallback
  entre Correios/ViaCEP/WideNet internamente, retorna geolocalização) + **ViaCEP
  para validação cruzada** de cidade/endereço oficial.
- Cache em Postgres passa a funcionar como **base de cobertura nacional viva**,
  crescendo organicamente com o uso (em vez de depender de base pré-carregada).
- Observação de compliance: se no futuro usarem CEP Aberto como fonte adicional,
  os dados são licenciados sob ODbL (exige atribuição/compartilhamento em
  redistribuição) — checar antes de usar em relatórios exportados a clientes.
- Exportação da tabela de preços: mesmo layout atual (Código IBGE, UF, Cidade,
  Bairro, Range de CEP, Prazo, Distância), só que refletindo CEPs reais.

### 3.3 Roteirização e VRP
- Sistema deve **sugerir automaticamente** o agrupamento de pedidos por
  motorista/veículo (VRP real), respeitando capacidade (peso+volume). Operador
  valida ou ajusta a sugestão — não é 100% manual nem 100% caixa-preta.
- **Regra de rotação:** motorista não pode ser escalado para a mesma região em
  turnos diferentes no mesmo dia (evita favoritismo/desgaste).
- **Definição de região:** calculada geometricamente por ângulo (azimute) entre
  loja e pedido, dividindo 360° em **8 setores cardeais** (N, NE, L, SE, S, SO, O, NO).
  O campo Bairro é usado só para exibição, nunca como critério de decisão do
  algoritmo (bairros têm formato irregular).
- **Confirmado:** dentro do mesmo turno, uma única rota/motorista pode cobrir
  mais de um setor cardeal ao mesmo tempo — não é "1 motorista = 1 setor".
- **Múltiplas viagens:** quando os pedidos excedem a capacidade numa única saída,
  o sistema divide automaticamente em 2+ viagens, priorizando setores
  diferentes/opostos entre viagens. O motorista retorna à loja entre viagens.
- **Tempo estimado da rota** = tempo OSRM (deslocamento) + (tempo médio de parada
  configurável × número de paradas). Valor padrão sugerido: 10 min/parada.
  Exibido como "Tempo: Maps + 10min média de cada parada". Evita precisar de
  serviço pago de trânsito em tempo real.
- Sistema deve exibir a **distância entre cada pedido consecutivo** da rota
  (não só o total).
- **Falha de geocodificação de pedido individual:** mensagem padrão "Erro ao
  tentar encontrar endereço do pedido", exibida mesmo com endereço completo
  cadastrado (camada de segurança).
- Matriz de despacho: coluna Motorista vem **pré-preenchida** com a sugestão do
  algoritmo; mostra alternativas elegíveis clicáveis (ex: "outros: Motorista 03,
  Motorista 05"), já filtradas pelas regras de rotação/disponibilidade. Se a lista
  crescer muito no futuro, evolui para popover ("+4 outros").
- **Solver escolhido/sugerido:** OR-Tools (Google). Decisão sobre rodar no mesmo
  serviço FastAPI (síncrono) ou serviço separado: **decidido rodar síncrono
  dentro do próprio FastAPI**, dado o volume relatado pelo Diego (a maioria das
  lojas entre <10 e ~20+ pedidos por execução — escala pequena para o OR-Tools,
  resolve em milissegundos/poucos segundos mesmo no Render free). Revisar para
  assíncrono só se o volume crescer muito no futuro.

### 3.4 Estado interno de roteirização (controle de duplicidade)
- Um pedido já usado numa rota executada no dia aparece marcado (ex: "✅ já está
  na Rota 2") quando o operador revisita a tela de seleção.
- **Comportamento: avisar, não bloquear.** Se o operador tentar reselecionar um
  pedido já roteirizado, o sistema exige confirmação em duas etapas.
- Esse estado é **interno ao sistema** (tabela própria no Postgres,
  `pedidos_roteirizados_hoje`), não depende do status de entrega do BigQuery.
- Cada pedido usado deve registrar rastreabilidade completa, ex: "Pedido ID
  20239930, usado na Rota X, Motorista X, turno Manhã, dia 31/08/2026,
  operador: [nome]".

### 3.5 Origem e seleção de pedidos
- Duas modalidades independentes:
  - **Base de Dados** (Google Sheets ou BigQuery): pedidos dos últimos 3 ou 5
    dias, organizados por data; usuário escolhe a data de entrega desejada.
    - Google Sheets: área com links de planilhas nomeadas por finalidade/origem.
    - BigQuery: conjunto de queries pré-salvas — **essas queries ainda não
      existem**, serão criadas pelo próprio time (Claude vai ajudar a escrever
      quando o schema do BigQuery chegar). Os operadores não criam essas queries,
      só escolhem qual usar.
  - **Importação temporária de CSV/XLSX:** pedido processado, roteirizado e
    descartado após o uso (não é armazenado permanentemente) — **comportamento
    atual, mantido como está**.
- **Status do pedido no BigQuery é ignorado por completo** — confirmado que está
  inconsistente (quase 100% sem status final), problema tratado separadamente
  pelo time de dados, **não bloqueia este projeto**. Sistema puxa todos os
  pedidos da data escolhida, independente de status (entregue, cancelado, em
  andamento), porque a curadoria é manual via checkbox pelo operador.
- Campos mínimos por pedido: ID, cliente, endereço, descrição, volume, peso
  (`weight`), filial/loja de origem, janela de entrega associada.
- Interface: lista com checkbox — só os marcados aparecem no mapa e entram na
  roteirização.

### 3.6 Lojas e hub de origem
- Substituir campo de texto livre por **mapa permanente** com todas as
  lojas/filiais, usando coordenadas já existentes no **Google My Maps** da
  empresa (não depende de geocodificação).
- **Cadastro manual** das coordenadas — sem sync automático necessário (não é
  tão frequente que uma loja nova apareça; Diego adiciona manualmente quando
  necessário).
- Cada loja é um marcador (logo) na posição real. Hover mostra nome, filial,
  endereço (uma info por linha). Clique define a loja como hub (destaque visual,
  ex: borda verde) e recalcula automaticamente área de atendimento e faixas de CEP.
- Pedidos filtrados automaticamente pela loja selecionada (cada pedido vem com
  a filial de origem vinculada).

### 3.7 Janelas de entrega
- Três janelas por padrão: **Manhã (08h-13h), Tarde (13h-18h), Noite (18h-21h)**
  — início/fim configuráveis, variam por loja. Poucas lojas usam o turno noite.
- **Confirmado: validação de janela é só um relatório informativo pós-cálculo.**
  O VRP monta o agrupamento só por capacidade/setor; depois o sistema compara
  o tempo estimado da rota com a janela da loja e com Delivery Window
  Start/End do pedido, **sem alterar o agrupamento já feito**. Indica claramente
  quais pedidos ficarão fora do prazo e o motivo.
- Turno da execução (manhã/tarde/noite) é escolhido **manualmente pelo operador**
  na tela ao rodar a roteirização — **não é inferido pelo relógio**. Isso permite
  o operador adiantar rotas da tarde enquanto ainda é de manhã, por exemplo.

### 3.8 Gate de execução da roteirização
Botão "Executar Roteirização" só habilita quando, simultaneamente:
1. Uma loja está selecionada como hub;
2. Um ou mais pedidos estão selecionados (checkbox);
3. Motoristas estão cadastrados e disponíveis;
4. Usuário confirma a ação.

### 3.9 Romaneio (.csv) — exportação
- Estrutura atual **mantida integralmente**, sem remoção de colunas: Rota,
  Motorista, Viagem, Veículo, Ordem_Parada, Endereço, Número, Bairro, CEP, Volume.
- Novas colunas a adicionar: ID do pedido (rastreabilidade), nome do cliente,
  peso, latitude/longitude.
- Coluna de **janela de entrega** fica **pendente** — depende do schema completo
  do BigQuery, ainda não enviado.

### 3.10 Histórico
- Toda execução de roteirização gera um registro permanente (mesmos dados da
  Matriz de Despacho + data/hora + operador responsável) para consulta futura.
- Sem expurgo automático por padrão; política de retenção (ex: 1 ano) é decisão
  futura, não bloqueante.

### 3.11 Permissões e usuários
- Uso restrito ao time de Delivery, sem acesso de clientes/lojas.
- **Vários operadores vão usar o sistema** (confirmado: pode ser 10+, um por
  loja/região). **Qualquer operador pode mexer em qualquer loja** — não há
  restrição de "cada um só vê as suas lojas".
- Por isso, **autenticação individual é necessária** (não é "nice to have") —
  sem login, não dá para saber quem executou cada rota, o que quebra a
  rastreabilidade do histórico e do controle de duplicidade.
- Concorrência entre operadores: como cada um roteiriza lojas diferentes na
  prática, não há sobreposição relevante de pedidos entre operadores — o aviso
  de "pedido já roteirizado no dia" já cobre o cenário relevante, sem
  necessidade de lock ou aviso de edição simultânea.

### 3.12 Pendências externas (não bloqueiam o planejamento, mas bloqueiam partes específicas)
1. **Schema completo do BigQuery** (tabelas, campos, queries salvas) — ainda não
   enviado por Diego. Bloqueia: definição final do schema unificado de pedido,
   coluna de janela de entrega no romaneio, e as queries pré-salvas do BigQuery.
2. **Confirmação de credenciais/acesso** já existentes a BigQuery e Google
   Sheets — verificar com o time técnico.
3. Status final do pedido no BigQuery está inconsistente — **não bloqueia**
   (decisão de negócio já tomada: será ignorado).

---

## 4. PERGUNTAS FEITAS E RESPONDIDAS DURANTE O PLANEJAMENTO

| # | Pergunta | Resposta do Diego |
|---|----------|---------------------|
| 1 | Volume de pedidos por loja/dia? | Muito variável: algumas lojas <10, outras 10-20, outras 20+. Não dá pra dar número único. |
| 2 | Render tem timeout que afete o OR-Tools? | Diego não sabe, plano é o free. |
| 3 | Turno é escolhido manualmente ou inferido? | Escolhido manualmente pelo operador (para poder adiantar rotas da tarde de manhã). |
| 4 | Capacidade do veículo: peso, volume ou ambos? | Combinação dos dois (o que estourar primeiro). Vem do BigQuery (`amount`, `weight`) ou Sheets ("Peso Entrega", "Volume Entrega"). |
| 5 | Quem configura capacidade por loja? | Cadastro manual (tela de admin). |
| 6 | Existe login individual hoje? | Não, só o Diego usa até agora. |
| 7 | Quantos operadores no futuro? | Vários, pode ser 10+ (um por loja/região). |
| 8 | Cada operador só vê suas lojas ou qualquer um mexe em qualquer loja? | Qualquer operador pode mexer em qualquer loja → confirma necessidade de login individual desde já. |
| 9 | Janela de entrega é restrição ativa do VRP ou relatório pós-cálculo? | Só relatório informativo pós-cálculo, sem alterar o agrupamento. |
| 10 | Rota pode cobrir múltiplos setores no mesmo turno? | Sim, confirmado. |
| 11 | Queries do BigQuery já existem? | Não, serão criadas pelo time (Claude ajuda depois que o schema chegar). Operadores só escolhem, não criam. |
| 12 | Coordenadas das lojas precisam de sync automático com Google My Maps? | Não, cadastro manual é suficiente (não muda com frequência). |

---

## 5. O PLANO DE IMPLEMENTAÇÃO COMPLETO (ordem definida e aprovada pelo Diego)

1. **Autenticação e identificação de operadores** — Crítica ⬅️ **EM ANDAMENTO (ver seção 6)**
2. **Correção do cálculo de CEP/raio** (remover fallback sintético de 48 CEPs) — Crítica ⬅️ **PRÓXIMA**
3. Cadastro de motoristas e veículos — Alta
4. Cadastro de lojas, hub no mapa, capacidade e janelas — Alta
5. Origem dos pedidos (CSV mantido + preparação de conectores Sheets/BigQuery) — Alta
6. Seleção de pedidos por loja/data com checkbox — Alta
7. Motor de roteirização (VRP com OR-Tools) — Crítica
8. Controle de duplicidade de pedidos — Alta
9. Matriz de despacho evoluída (sugestão + alternativas) — Média
10. Validação de janela de entrega e limite de km (relatórios pós-cálculo) — Média
11. Histórico de roteirizações — Média
12. Romaneio: novas colunas (janela de entrega fica pendente do schema do BigQuery) — Baixa

Cada etapa no plano original tinha: Prioridade, Objetivo, O que será alterado,
Componentes afetados, Dependências, Riscos/impactos, Resultado esperado, Como validar
— formato detalhado disponível na mensagem original do plano, se precisar recuperar.

Além disso, há uma mudança de **layout de frontend** pedida pelo Diego (ainda não
implementada): o mapa hoje é pequeno e fica à direita; a ideia é o mapa ocupar
as duas bordas da tela (bem maior), as tabelas que ficavam à esquerda
(verticais) passarem para cima do mapa (horizontais), e as informações de
volume/rotas/extensão viária/custo que ficavam acima do mapa passarem para
**abaixo** do mapa, acima do romaneio. Feedback dado: a ideia geral é boa, mas
a lista de pedidos (com checkbox, pode ter 20+ itens) pode não funcionar bem
como faixa horizontal fixa — sugeri um painel retrátil/flutuante sobre a borda
do mapa como alternativa. **Isso ainda não foi implementado, ficou em aberto
como sugestão a decidir com Diego.**

---

## 6. STATUS ATUAL DETALHADO — ETAPA 1 (Autenticação)

### O que o Diego já tinha implementado (commit `06645dd` no GitHub) antes de eu revisar:
- `backend/auth.py` — funções de hash de senha (bcrypt), geração/validação de JWT.
- `backend/config.py` — variáveis de ambiente (SECRET_KEY, ALGORITHM, etc.).
- `backend/database.py` — modelo ORM `Operador` (id, nome, email, senha_hash, ativo, criado_em).
- `backend/main.py` — endpoints `/api/auth/register`, `/api/auth/login`, `/api/auth/me`.
- `frontend/src/components/Login.jsx` — tela de login/cadastro (criada mas não conectada ao app).
- `frontend/src/services/api.js` — instância axios com interceptor de token (criada mas não usada pelo App.jsx).

### Bugs críticos que eu encontrei e já corrigi:
1. **`backend/requirements.txt` estava em UTF-16** em vez de UTF-8 — corrompido,
   causaria falha ou comportamento incorreto no `pip install` do Render. **Corrigido**
   (reescrito em UTF-8 puro).
2. **`httpx` estava faltando no requirements.txt** — é importado sem try/except no
   `main.py` (usado em geocodificação e OSRM), então o app **quebraria ao iniciar**.
   **Corrigido** (adicionado `httpx==0.28.1`).
3. **`asyncpg` estava faltando** — usado (com try/except) para o cache persistente
   de geocodificação no Postgres; sem ele, o cache silenciosamente parava de
   persistir entre reinícios. **Corrigido** (adicionado `asyncpg==0.30.0`).
4. **`python-dotenv` nunca tinha sido adicionado** — `config.py` faz
   `from dotenv import load_dotenv`, mas a lib não estava no requirements.txt,
   o que quebraria a inicialização. **Corrigido**.
5. **Login sempre falhava com erro 500** — `main.py` chamava uma função
   `verificar_senha(...)` que não existe; a função real (definida em `auth.py`)
   se chama `verificar_senha_hash`. **Corrigido**.
6. **Frontend e backend não combinavam no contrato do login:**
   - `Login.jsx` enviava JSON `{email, senha}`, mas o backend usa o padrão OAuth2
     do FastAPI (`OAuth2PasswordRequestForm`), que exige **form-urlencoded** com
     campos `username`/`password`. **Corrigido** no frontend (agora monta um
     `URLSearchParams` com `username`/`password`).
   - `Login.jsx` usava `fetch('/api/auth/login')` (caminho relativo) em vez do
     cliente axios com a baseURL certa — em produção (domínios diferentes entre
     Vercel e Render) isso bateria no próprio frontend. **Corrigido** (agora usa
     a instância `api` do `services/api.js`).
   - O backend não devolvia dados do operador no login, mas o frontend esperava
     `data.operador`. **Corrigido** (backend agora retorna
     `{access_token, token_type, operador: {id, nome, email}}`).
7. **`Login.jsx` existia mas não era renderizado em lugar nenhum do `App.jsx`.**
   **Corrigido**: agora `App.jsx` guarda o estado do operador logado (recuperado
   do `localStorage`); sem operador logado, renderiza só a tela de `<Login>`;
   logado, renderiza o app normal, mostrando o nome do operador + botão "Sair"
   na barra superior.
8. **Nenhuma chamada existente do app (upload, otimizar, exportar, etc.) enviava
   o token de autenticação** — todas usavam `axios` "cru" com a constante
   `API_BASE`. **Corrigido**: criei uma instância `apiAuth` (axios com interceptor
   que injeta `Authorization: Bearer <token>` automaticamente) e troquei todas
   as chamadas do `App.jsx` para usar essa instância. Isso deixa o app pronto
   para quando as rotas de negócio forem protegidas de verdade (ainda não foram).
9. **`backend/tests/geocache.db`** (banco de teste) tinha sido commitado por
   engano. Removido do controle de versão e adicionado ao `.gitignore`.

### Melhoria de segurança adicional (a pedido do Diego):
- **`/api/auth/register` estava completamente aberto** — qualquer pessoa com a
  URL do backend poderia se cadastrar como operador. Diego pediu para corrigir.
  **Implementado:** agora o registro exige um campo `codigo_convite`, comparado
  com a variável de ambiente `OPERATOR_INVITE_CODE`. Sem essa variável
  configurada, o cadastro fica **bloqueado por padrão** (mais seguro do que
  deixar aberto por acidente). `Login.jsx` foi atualizado com um campo
  "Código de Convite" no formulário de cadastro.
- Confirmado com o Diego que a variável `JWT_SECRET_KEY` **já estava configurada**
  no Render antes dessas mudanças (então o token JWT já era seguro, apesar do
  valor padrão fraco embutido no código-fonte público do GitHub —
  `chave_secreta_padrao_dev_123` — que só seria um risco se a env var não
  estivesse setada).

### Como as correções foram entregues ao Diego:
- Inicialmente gerei um arquivo `.patch` (diff do git) — **não funcionou** porque:
  (a) o `requirements.txt` antigo era binário (UTF-16), então o git tratou como
  patch binário e faltava a "full index line"; (b) o patch tentava apagar
  `backend/tests/geocache.db`, que não existe no computador local do Diego
  (só existia no repositório remoto).
- Troquei a abordagem: gerei um **.zip com os arquivos já corrigidos por completo**
  (`backend/requirements.txt`, `backend/config.py`, `backend/main.py`,
  `frontend/src/App.jsx`, `frontend/src/components/Login.jsx`, `.gitignore`),
  para o Diego simplesmente substituir os arquivos correspondentes na pasta do
  projeto dele e commitar.
- Diego aplicou os arquivos, configurou `DATABASE_URL`, `JWT_SECRET_KEY` e
  `OPERATOR_INVITE_CODE` no painel do Render (confirmado via print), e deu commit/push.

### Testes que eu fiz no meu ambiente (sandbox) antes de entregar, e que passaram:
- `pip install -r requirements.txt` limpo, sem erros.
- `python -c "import main"` — importa sem erro (app carrega).
- Servidor local rodando: `POST /api/auth/register` sem código de convite →
  bloqueado corretamente (`403 Código de convite inválido`).
- `POST /api/auth/register` com código de convite certo → sucesso.
- `POST /api/auth/login` (form-urlencoded, username/password) → retorna
  `access_token` + dados do operador corretamente.
- `npm run build` do frontend → build limpo, sem erros de sintaxe/compilação.

### 🔴 PROBLEMA ATUAL EM ABERTO (ainda não diagnosticado):
O Diego testou no ambiente real de produção (Render + Vercel) e relatou:
- A tela de login **aparece corretamente antes de tudo** (confirma que a
  integração `App.jsx` + `Login.jsx` está funcionando).
- Testando a rota `/api/auth/login` diretamente pelo `/docs` (Swagger), ele
  **recebeu um `access_token` normalmente** (confirma que o backend em si,
  já deployado, está funcionando corretamente para login).
- Porém, ao tentar fazer login **pela tela de login de verdade** (o formulário
  do site), **dá erro**.

**Isso ainda não foi investigado.** Hipóteses a checar na próxima etapa (ainda
não confirmadas):
- CORS: o backend tem `allow_origins=["*"]` no `main.py`, então CORS não deveria
  ser o problema, mas vale confirmar se o erro no console do navegador é de CORS.
- A variável de ambiente do frontend (`VITE_API_URL`, usada em `services/api.js`)
  pode não estar configurada na Vercel, fazendo a instância `api` (usada dentro
  de `Login.jsx`) apontar para `http://127.0.0.1:8000` (valor padrão) em vez do
  backend real do Render — isso bateria em `localhost` do próprio navegador do
  usuário e falharia. **Essa é a hipótese mais provável no momento**, porque
  `Login.jsx` usa a instância `api` (de `services/api.js`, baseURL
  `import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'`), enquanto o resto
  do `App.jsx` usa a instância `apiAuth` (que aponta direto para a constante
  `API_BASE` hardcoded = `https://routeflow-backend-v5ji.onrender.com/api`).
  Ou seja, **há duas instâncias diferentes de cliente HTTP no frontend, com
  baseURLs potencialmente diferentes** — isso é a causa mais provável do erro
  e precisa ser corrigido (unificar para todos usarem a mesma baseURL, ou
  configurar `VITE_API_URL` corretamente na Vercel).
- Também vale checar a mensagem de erro exata que aparece na tela (ou no
  console do navegador, F12) para confirmar a causa antes de aplicar a correção.

**Próxima ação imediata:** pedir ao Diego a mensagem de erro exata (print da
tela + console do navegador, F12 → aba Console e aba Network) para confirmar a
hipótese acima antes de corrigir.

---

## 7. PRÓXIMOS PASSOS (em ordem)

1. **Diagnosticar e corrigir o erro de login na tela real** (problema atual em aberto).
2. Confirmar que login + cadastro funcionam de ponta a ponta em produção → **fechar Etapa 1**.
3. Avançar para a **Etapa 2**: remover o fallback sintético de 48 CEPs cardeais no
   endpoint `/api/cobertura-ceps` do `backend/main.py`, trocar para BrasilAPI v2
   como fonte primária, adicionar raio configurável e mensagem explícita de erro
   quando não conseguir geolocalizar.
4. Seguir a ordem das Etapas 3 a 12 listadas na seção 5.
5. Decidir com o Diego o que fazer com a ideia de mudança de layout do frontend
   (mapa maior + lista de pedidos — ver observação na seção 5).
6. Quando o Diego enviar o schema completo do BigQuery e confirmar credenciais
   de acesso a BigQuery/Google Sheets, desbloquear as partes pendentes das
   Etapas 5 e 12.

---

## 8. INFORMAÇÕES DE CONTA/AMBIENTE (não sensíveis, só referência)

- Repositório GitHub: `https://github.com/munizdiego12/logistica-mapa-cobertura` (público)
- Backend em produção (Render): `https://routeflow-backend-v5ji.onrender.com/api`
- Frontend em produção: Vercel (URL específica não fornecida na conversa)
- Variáveis de ambiente já configuradas no Render: `DATABASE_URL`, `JWT_SECRET_KEY`,
  `OPERATOR_INVITE_CODE`
- Variável de ambiente do frontend a verificar na Vercel: `VITE_API_URL`
  (possivelmente não configurada — ver seção 6, hipótese do bug atual)

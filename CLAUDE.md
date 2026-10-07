# CLAUDE.md

Plataforma de inteligência logística e roteirização last-mile do time de Delivery (dono: Diego). Calcula cobertura por CEP/raio (precificação para lojas-cliente) e roteiriza pedidos por motorista/veículo. É ferramenta de planejamento/apoio: **não substitui** o sistema interno que envia as rotas oficiais aos motoristas.

Contexto detalhado: `docs/MEMORIA_PROJETO_roteirizacao.md` (regras e decisões) e `docs/STATUS_E_PLANO_ATUALIZADO.md` (status e ordem atual).

## Regra obrigatória: apenas serviços gratuitos

**Tudo deve usar apenas serviços gratuitos.** Não introduzir APIs, bancos, hospedagem, mapas, solvers ou qualquer dependência paga (ex.: serviço de trânsito em tempo real, Google Maps API paga, Render pago). Ao propor soluções, escolher sempre a opção gratuita (ex.: Neon para Postgres, OSRM, BrasilAPI/ViaCEP/Nominatim, OR-Tools).

## Atualização do status (obrigatório)

**Ao concluir cada etapa, atualizar `docs/STATUS_E_PLANO_ATUALIZADO.md` e marcar a etapa em `docs/CHECKLIST_PROJETO.md`** (mover a etapa para "O que já está feito" com a evidência/commit e ajustar "O que falta" e a ordem sugerida).

## Stack

- **Frontend:** React (Vite) + Tailwind + React-Leaflet, hospedado na Vercel.
- **Backend:** FastAPI (Python), hospedado no Render (plano free). `backend/main.py` é o ponto de entrada.
- **Banco:** PostgreSQL (SQLAlchemy) no Neon (gratuito; o do Render expirava). Pendentes da Etapa 0: backup automático (GitHub Actions) e Alembic, que deve ser adotado antes de novas tabelas.
- **Roteamento viário:** OSRM. **Solver VRP:** OR-Tools, síncrono dentro do FastAPI.
- **Geocodificação:** BrasilAPI v2 (primária) + ViaCEP (validação cruzada) + Nominatim, com cache em Postgres.
- **Auth:** JWT + bcrypt; registro exige `codigo_convite` (`OPERATOR_INVITE_CODE`). Env vars: `DATABASE_URL`, `JWT_SECRET_KEY`, `OPERATOR_INVITE_CODE`; frontend: `VITE_API_URL`.
- **Cuidado:** `backend/requirements.txt` deve ficar em **UTF-8** (já voltou a UTF-16 antes).

## Regras de negócio principais

- **Veículos:** só Carro de passeio (R$130/rota) e Fiorino/Utilitário (R$260/rota). Custo fixo por tipo; sem combustível/hora-motorista. Sem caminhão/moto por ora.
- **Motoristas:** cadastro próprio (nome + tipo de veículo), até 3 turnos/dia (manhã, tarde, noite).
- **Capacidade:** varia por loja; combina peso + volume (o que estourar primeiro).
- **Peso dos pedidos:** não vem da API do Atacadão (ela não devolve peso). Decisão: tabela `item_pesos` no Neon, com carga inicial extraída do nome do produto (`scripts/estudo_peso.py`, que só lê arquivos locais) e conferência manual dos itens mais vendidos; pedido com item sem peso aparece como "peso incompleto" (o peso é um piso). Subetapa 1 (estudo e CSV inicial) feita; faltam a tabela, a tela de manutenção/fila "sem peso" e o peso por pedido/rota/veículo. **`data/peso/` (CSVs do BigQuery e o CSV de pesos) está no `.gitignore` e nunca deve ser versionado: o repositório é público.**
- **Limite de km por rota/dia:** não interfere no VRP; conferência pós-cálculo com aviso e taxa extra à loja.
- **Precificação por CEP:** função separada da roteirização, botão "Raio Xkm" (padrão 30 km, configurável). **Nunca** usar fallback sintético: CEP não geolocalizado é informado explicitamente. A cobertura vem **só** da tabela `cep_prefixos` (CNEFE 2022 do IBGE, um registro por prefixo de CEP de 5 dígitos, 27 UFs, ~24,6 mil linhas, ~4 MB), carregada por `scripts/carregar_cnefe.py` (uma UF por vez, upsert, apaga o download, para se a tabela passar de 100 MB; nunca `DROP`/`TRUNCATE`). Municípios do IBGE em `ibge_municipios` (`scripts/carregar_municipios.py`). A distância do "Raio X km" é em linha reta entre o hub e o centro do prefixo, não por estrada, e a legenda diz isso. Não há mais faixas manuais nem fallback: região sem prefixos mostra o aviso de região sem cobertura. Mensagens de tela não citam tabela, script, arquivo, API nem nome de serviço. Nenhum script pode ter URL/senha de banco no código: usar `DATABASE_URL`.
- **VRP:** sugere agrupamento automático respeitando capacidade; operador valida/ajusta. Região = 8 setores cardeais por azimute loja→pedido (Bairro só para exibição). Uma rota pode cobrir vários setores no mesmo turno. Motorista não repete a mesma região em turnos diferentes no mesmo dia. Excedeu capacidade → múltiplas viagens (setores opostos), com retorno à loja.
- **Tempo da rota:** tempo OSRM + (tempo médio de parada, padrão 10 min × paradas). Exibir distância entre paradas consecutivas. Falha de geocodificação de pedido: "Erro ao tentar encontrar endereço do pedido".
- **Janelas de entrega:** Manhã 08–13h, Tarde 13–18h, Noite 18–21h (configuráveis por loja). Validação é só relatório informativo pós-cálculo, sem alterar o agrupamento. Turno escolhido manualmente pelo operador.
- **Duplicidade:** pedido já roteirizado no dia é marcado; avisar, não bloquear (confirmação em duas etapas). Estado interno em `pedidos_roteirizados_hoje`, com rastreabilidade completa (pedido, rota, motorista, turno, data, operador).
- **Pedidos:** Base de Dados (Sheets/BigQuery, últimos 3–5 dias) ou CSV/XLSX temporário (descartado após uso). Status do pedido no BigQuery é ignorado. Seleção por checkbox; só os marcados entram no mapa e na roteirização.
- **Lojas/hub:** mapa permanente com coordenadas cadastradas manualmente (do Google My Maps); clicar define o hub e recalcula cobertura. Pedidos filtrados pela loja.
- **Gate de execução:** "Executar Roteirização" só habilita com loja selecionada, pedidos marcados, motoristas disponíveis e confirmação do usuário.
- **Romaneio (.csv):** manter colunas atuais (Rota, Motorista, Viagem, Veículo, Ordem_Parada, Endereço, Número, Bairro, CEP, Volume) e adicionar ID do pedido, cliente, peso, lat/long. Janela de entrega pendente do schema do BigQuery.
- **Histórico:** toda execução gera registro permanente (dados da matriz + data/hora + operador).
- **Usuários:** só time de Delivery; vários operadores, qualquer um mexe em qualquer loja; login individual obrigatório para rastreabilidade.

## Ordem das etapas

Feitas: **1** Autenticação; **2** CEP/raio sem fallback sintético; **2b** Base nacional de CEP via CNEFE/IBGE, **concluída** (27 UFs, ~24,6 mil prefixos, ~4 MB no Neon; cobertura por prefixo com Total/Parcial validada no site; faixas manuais e fallback removidos; código IBGE vindo de busca real, nunca fixo). Pendência da 2b antes do primeiro uso real: testar a importação do XLSX (coluna "Cobertura" por último e aba "Cobertura e fonte") na transportadora; e confirmar o termo de uso do CNEFE antes de entregar tabelas a clientes.

Ordem atual (a partir de agora):

1. **Etapa 0 (restante)** — backup automático (GitHub Actions) e Alembic; **0b** — remover `correcoes_etapa1_auth.patch` da raiz.
2. Proteger rotas de negócio (`/upload`, `/otimizar`, `/cobertura-ceps`) com o token.
3. **Etapa 3** — Cadastro de motoristas e veículos; **Etapa 4** — Lojas, hub no mapa, capacidade e janelas.
4. **Etapa 6** — Seleção de pedidos por loja/data; depois **Etapa 5** — Conectores Sheets/BigQuery (aguardam schema).
5. **Peso dos pedidos** (subetapas 2 e 3: tabela `item_pesos`, tela de manutenção, peso por pedido/rota/veículo), que a etapa seguinte usa na capacidade.
6. **Etapa 7** — VRP com OR-Tools, junto com **Etapa 8** — Controle de duplicidade.
7. **Etapas 9** (matriz de despacho), **10** (relatórios de janela e km), **11** (histórico) e **12** (romaneio com novas colunas).
8. Decidir o layout do frontend (mapa grande + painel retrátil de pedidos).

Pendências externas: schema do BigQuery e queries pré-salvas; credenciais de BigQuery e Google Sheets; confirmar o termo de uso/atribuição do CNEFE com o IBGE.

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

## ⬜ Etapa 3 — Backup automático (GitHub Actions)
- [ ] No GitHub: Settings → Secrets and variables → Actions → criar o secret `DATABASE_URL` com a string NOVA do Neon.
```
Crie um GitHub Actions (.github/workflows/backup.yml) que roda toda semana e manualmente, executa pg_dump usando o secret DATABASE_URL e guarda o dump compactado como artifact por 30 dias. Explique como restaurar o dump em um banco novo.
```
- [ ] Rodar o workflow uma vez à mão (aba Actions) e conferir o artifact.

## ⬜ Etapa 4 — Migrations e rotas protegidas
```
1) Configure Alembic no backend com migration inicial refletindo os models atuais (operadores, ceps_reais etc.), sem apagar dados existentes. Documente os comandos.
2) Proteja com o token JWT (get_current_operador) todos os endpoints de negócio: /api/upload, /api/otimizar, /api/otimizar/status, /api/cobertura-ceps, /api/exportar-tabela-frete-xlsx e /api/modelo-xlsx. Deixe abertos só login e register. Confirme que o frontend já envia o token e trate 401 deslogando o usuário.
3) Escreva testes para isso e rode-os.
```

## ⬜ Etapa 5 — Motoristas e veículos
```
Implemente o cadastro de motoristas e veículos:
- Tabela motoristas (nome, tipo_veiculo, ativo) via Alembic. Tipos: "Carro de passeio" (R$130 por rota) e "Fiorino/Utilitário" (R$260 por rota), em uma tabela ou enum de configuração.
- CRUD protegido por token e tela de cadastro no frontend.
- O custo de rota passa a ser o valor fixo do veículo; remova os campos de combustível (R$/L) e custo-hora da UI e do cálculo (reescreva costs.py e seus testes).
- Troque a frota gerada ("Motorista 01") em main.py pelos motoristas cadastrados.
Rode os testes e o build do frontend. Sem push.
```

## ⬜ Etapa 6 — Lojas, hub no mapa, capacidade e janelas
- [ ] Fora do código: exportar do Google My Maps a lista de lojas (nome, filial, endereço, latitude, longitude) em CSV.
```
Implemente a tabela lojas (nome, filial, endereço, lat, lng, capacidade_peso, capacidade_volume, janelas manhã/tarde/noite com início e fim configuráveis). Crie um script para importar lojas de um CSV, o CRUD em tela de admin e o mapa permanente com marcadores. O hover mostra nome, filial e endereço; o clique define a loja como hub (borda verde) e recalcula cobertura e faixas de CEP. Adicione o botão "Raio Xkm" ao lado do nome da loja, com raio configurável (padrão 30). Sem push.
```

## ⬜ Etapa 7 — Seleção de pedidos por loja e data
```
Implemente a lista de pedidos com checkbox, filtrada pela loja selecionada e por data. Só os pedidos marcados aparecem no mapa e entram na roteirização. Por enquanto a origem é o CSV/XLSX existente (descartado após o uso); inclua os campos ID, cliente, endereço, descrição, volume, peso, filial e janela. Crie uma camada de "fonte de pedidos" com interface única, para plugar Sheets e BigQuery depois. Mostre "Erro ao tentar encontrar endereço do pedido" quando a geocodificação falhar. Sem push.
```

## 🔄 Etapa 7b — Peso dos pedidos *(antes da Etapa 8: o solver usa o peso na capacidade)*

**Decisões do Diego (08/10/2026):**
1. **Ordem:** a subetapa 2 **não começa agora**. Primeiro vêm o **backup automático (Etapa 3)** e o **Alembic com rotas protegidas (Etapa 4)**, porque a tabela de pesos terá dados conferidos à mão e uma tela de edição que precisa de login e de migration.
2. **"Peso incompleto" é mostrado como mínimo**, por exemplo: "no mínimo 34 kg; faltam 2 itens".
3. **Quem mantém a tabela:** qualquer operador logado pode editar; o sistema registra **quem alterou e quando**.
4. **Janela de entrega** é outro assunto e fica em aberto.

**Decisão original:** em vez de depender da API do Atacadão (que não devolve peso), mantemos uma **tabela `item_pesos` no Neon**, com carga inicial extraída do nome do produto e **conferência manual dos itens mais vendidos**. Pedidos com itens sem peso aparecem como **"peso incompleto"** (o peso mostrado é então só um piso).

- [x] **Subetapa 1 — Estudo de viabilidade e CSV inicial** (feito, sem integrar nada, sem rede e sem tocar no banco): `scripts/estudo_peso.py` lê `data/peso/skus.csv` e `data/peso/itens_pedidos.csv` (ambos **fora do git**: o repositório é público) e gera `data/peso/item_pesos_inicial.csv` para revisão manual. Resultado com os 6.675 SKUs e 2.164 pedidos da amostra:
  - o nome traz o peso de **93,6% das unidades vendidas** (92,1% com confiança alta) e de 89,8% dos SKUs; 681 SKUs ficam sem medida;
  - mas só **39,1% dos pedidos ficam completos** (basta 1 item sem peso entre ~12 por pedido);
  - conferindo à mão os **248 SKUs** mais vendidos sem peso chega-se a 80% de pedidos completos, com **426** a 90%, com 567 a 95% e com 681 a 100%;
  - os sem peso são sobretudo contagens (un, rolos, folhas, ovos), dimensões e capacidades (saco de lixo, copo): o CSV traz esses casos em branco para você preencher.
- [ ] **Revisar o `data/peso/item_pesos_inicial.csv`** de cima para baixo (já vem ordenado por unidades vendidas): preencher os sem peso e conferir os de confiança "baixa". Para abrir no Excel em português use `python scripts/estudo_peso.py --excel` (o Excel lê "1.5" como data).
- [ ] **Subetapa 2 — Tabela `item_pesos`, tela de manutenção e fila "sem peso"** *(só depois das Etapas 3 e 4 deste checklist: backup automático, Alembic e rotas protegidas; rascunho do prompt)*
```
Crie a tabela item_pesos no Neon via Alembic (id_sku, reference_code, nome, peso_kg, fonte, confianca, atualizado_em, atualizado_por; qualquer operador logado edita e o sistema registra quem alterou e quando), com carga a partir do CSV revisado (script com upsert, DATABASE_URL só pela variável de ambiente). Crie a tela de manutenção protegida por token: listar/editar o peso de um SKU e uma fila "sem peso" ordenada pelas unidades vendidas. SKUs novos que aparecerem nos pedidos entram na fila. Sem push.
```
- [ ] **Subetapa 3 — Peso por pedido, rota e veículo** *(rascunho do prompt)*
```
Calcule o peso de cada pedido (quantidade x peso do item) e, quando algum item não tiver peso, mostre "peso incompleto" como mínimo (ex.: "no mínimo 34 kg; faltam 2 itens"). Some o peso por rota e compare com a capacidade do veículo (peso + volume, o que estourar primeiro). Sem push.
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
- Capacidade por peso e volume (o que estourar primeiro), da loja.
- Divisão automática em múltiplas viagens, priorizando setores diferentes/opostos; o motorista volta à loja entre viagens.
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
Adicione ao romaneio .csv as colunas ID do pedido, cliente, peso, latitude e longitude, mantendo todas as atuais. A coluna de janela de entrega fica pendente do schema do BigQuery. Sem push.
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

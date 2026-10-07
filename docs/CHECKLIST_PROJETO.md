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
- [x] Limpezas: requirements em UTF-8, senhas fora do código, código morto removido, CLAUDE.md

---

## 🔄 Etapa 2b — CEPs do Brasil inteiro (IBGE/CNEFE)

- [x] **Registrar a fase 1 como validada**
```
Atualize docs/STATUS_E_PLANO_ATUALIZADO.md marcando a fase 1 da Etapa 2b como validada em produção: Neon com 76 faixas carregadas, cobertura testada na Av. Paulista (24 CEPs) e na Av. Atlântica (6 CEPs), e Florianópolis (sem faixas) retornando o aviso correto. Faça commit sem push.
```

- [x] **Fase 2 — teste com o Acre** (leia o resultado antes de gravar no Neon)
```
Execute a fase 2, só com o Acre: script offline que baixa o CNEFE do AC, calcula a mediana por prefixo de 5 dígitos (com n_enderecos e dispersão) e grava com upsert no banco apontado pela variável DATABASE_URL, sem gravar a string em arquivo. Rode primeiro em um SQLite local e me mostre o resultado. Só grave no Neon depois que eu confirmar.
```
  Depois de confirmar: no PowerShell, defina `$env:DATABASE_URL`, rode o comando que o Claude Code indicar e confira o tamanho no Neon.
  - [ ] Conferir o tamanho de `cep_prefixos` no Neon (`pg_total_relation_size`).

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
- [ ] **Validar o passo 3 no site** (depois do deploy no Render): calcular a cobertura no DF (deve mostrar Total e Parcial, legenda e fonte), em SP (24, todas "Parcial", sem fonte do IBGE) e em Florianópolis (aviso de região sem cobertura); baixar o CSV e o XLSX e conferir a coluna "Cobertura", a legenda e a aba "Cobertura e fonte".

- [ ] **Fase 2 — Brasil inteiro, uma UF por vez** *(ordem aprovada: só depois do passo 3)*
```
O Acre foi validado. Rode o Brasil inteiro, uma UF de cada vez, medindo o tamanho da tabela no banco ao final de cada UF. Pare e me avise se passar de 100 MB no total. Faça commit sem push.
```

- [ ] **Fase 3 — completar com a BrasilAPI e usar o IBGE por município como último recurso**
```
Execute a fase 3 do plano da Etapa 2b: completar CEPs ausentes com a BrasilAPI v2 sob demanda, gravando no cache com precisao='brasilapi', e usar os centroides de município do IBGE como último recurso. Corrija também o código IBGE fixo (3550308) em database.py. Sem push.
```
  *(O código IBGE fixo já foi corrigido nos passos 1 e 2; a tabela de municípios do IBGE também já existe.)*

- [ ] **Fase 4 — limpeza e atribuição**
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

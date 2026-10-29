<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - Reproducible development host
Copyright (C) JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-DEV-SERVER banner" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a> | 🇵🇹 <b>Português</b></p>

### 🏗️ Anfitrião de desenvolvimento reproduzível para todo o ecossistema

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Language">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="Core">
  <img src="https://img.shields.io/badge/Tests-442%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.1.9-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-0F6CBD.svg" alt="Maturity">
</p>

---

**Verificação de honestidade - o que realmente funciona hoje:** todos os vinte e dois módulos nomeados abaixo (`config.py`, `inventory.py`, `remote_station.py`, `preflight.py`, `provision.py`, `migration.py`, `workspace.py`, `recipe.py`, `runner.py`, `durable_queue.py`, `ai_provider.py`, `incident_transport.py`, `repair_cycle.py`, `operations.py`, `delivery.py`, `cli.py`, `api.py`, `plugins.py`, `sandbox.py`, `taskflow.py`, `worker.py`, `signing.py`) são código real, não esboços, e estão cobertos por uma suite de testes real (442 testes a passar em `tests/test_*.py`). O que esse código real fez de facto, em concreto: validou documentos JSON, planeou migrações em disco, executou um subprocesso real e limitado num espaço de trabalho isolado real com um ambiente depurado real, persistiu uma fila/diário SQLite real entre reinícios e exercitou uma ida e volta de incidentes real assinada com HMAC - tudo contra esta cópia local ou uma costura de teste injetável, nunca contra o hardware Raspberry Pi 5/CM5 de destino para que este projeto é construído. O `provider suggest` só chama o `FakeProvider` determinístico; ligar um fornecedor de IA real é uma decisão explícita do utilizador, ainda por tomar. O `station preflight`/`station plan` descrevem um anfitrião remoto através de um inspetor injetável e nunca correram contra uma máquina remota real. Nada neste repositório aprovisionou um anfitrião nem executou uma implementação, e o ciclo de trabalhador (`queue work`) só correu contra simulacros do lançador e do git, nunca num anfitrião real - o `overall_maturity: "functional"` fixado no código do `deliver evaluate` di-lo com clareza a partir de dentro do próprio código. Veja o `CHANGELOG.md` para saber exatamente o que foi entregue, entrega a entrega.

---

> **Estado de segurança (safety e security):** este ecossistema não é um sistema de segurança certificado. Ainda não existe um caminho de E-STOP por hardware, nem limites ou interlocks impostos pelo firmware, nem um comando de movimento verificado; as imagens de firmware são verificadas com CRC32 e um HMAC-SHA256 de chave partilhada, não com uma assinatura assimétrica; TLS e TLS mútuo são opcionais e estão desativados por defeito; nenhuma placa própria foi ainda montada ou testada. Leia a [base de segurança](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md) e o [modelo de ameaças](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md) antes de confiar em qualquer afirmação aqui para a segurança de uma pessoa.

---

## 📋 Num relance

| | |
|---|---|
| Versão | `0.1.9` |
| Maturidade | Funcional |
| Testes | 442 (`python -m pytest -q tests`) |
| Tecnologia | Python 3.11+ / JSON Schema / systemd (host role, Linux only) / SQLite (durable task/state journal, from DS05 onward) |
| Destino | Um servidor de desenvolvimento |
| Em hardware real | Ainda não: não há registo de execução em hardware real para esta versão |

**Ir para:** [Visão geral](#-visão-geral) · [Arquitetura](#-arquitetura) · [Início rápido](#-início-rápido) · [Testes](#-testes) · [Estrutura do repositório](#-estrutura-do-repositório) · [Projetos relacionados](#-projetos-relacionados)

## 🚦 Estado do projeto

Cada linha é uma parte deste repositório e a luz diz até onde chega hoje. É escrita com o que o repositório consegue demonstrar (testes, compilações, execuções), não com o que está previsto.

🟢 Feito e verificado · 🟡 Funciona, com limites conhecidos · 🟠 Feito a meio ou ainda por verificar · 🔴 Por fazer ou a não funcionar

| Área | Estado | O que significa aqui |
|---|---|---|
| Software | 🟡 | Funciona para o seu propósito principal; a verificação de honestidade acima lista o que ainda falta |
| Testes | 🟢 | 442 testes automáticos, executados a cada alteração |
| Hardware real | 🔴 | Ainda não: não há registo de execução em hardware real para esta versão |
| Documentação | 🟢 | README em oito idiomas, verificado contra o manifesto a cada alteração |

## 🎯 Visão geral

O HYDRA-UMC-DEV-SERVER é infraestrutura de desenvolvimento para o ecossistema HYDRA-UMC/URTC:
um anfitrião reproduzível (destino: um Raspberry Pi 5 ou Compute
Module 5, 8 GB, arrancado por NVMe) que alojará o código-fonte
deste ecossistema e executará tarefas limitadas, protegidas por políticas, de programação/compilação/teste - para pessoas
e assistentes de IA por igual. **Não** é uma nova IA para treinar, **não** é um
sistema operativo de substituição, e nunca decide por si que uma
máquina é segura de alterar.

A DS01 entregou duas peças reais e úteis por si:

1. **Esquema de configuração** (`config validate`) - três documentos JSON
   (`HostProfile`, `ToolchainPolicy`, `TaskPolicy`), cada um com validação
   real e um teste negativo real para cada forma rejeitada. A invariante
   que mais importa desde o primeiro dia: `TaskPolicy.allow_deploy`
   é `False` por omissão, e só um documento que defina o literal booleano JSON
   `true` pode alguma vez produzir uma política com ele ativado.
2. **Descoberta de manifestos** (`inventory scan`) - o mesmo padrão real e testado
   que o papel de periferia do próprio HYDRA-UMC-OPS-AGENT já usa para encontrar e
   validar um `hydra-umc.project.json`, reutilizado aqui em vez de
   reimplementado.

A DS02 acrescenta mais três, todas sob o subcomando `station` e todas ainda em
"validar e descrever, nunca agir":

3. **Perfil de estação remota** (`station validate`) - um documento JSON
   (`RemoteIdentity` + `RemoteAccess` + ferramentas exigidas) com a
   mesma validação que acumula erros. A sua invariante do primeiro dia: o
   ponto de edição remota liga-se a loopback/rede privada, e um endereço
   encaminhável é recusado a menos que o documento defina o literal booleano
   `allow_public_bind: true`; a identidade é uma conta de sistema dedicada,
   nunca `root` nem um utilizador de sessão.
4. **Verificação prévia do anfitrião** (`station preflight`) - lê um perfil e
   reporta, através de uma costura de inspetor injetável, se *este* anfitrião está
   realmente pronto para se tornar essa estação (versão do Python, disco livre,
   espaço de trabalho gravável, ferramentas no `PATH`, porta livre, a identidade é uma
   conta de sistema real). Nunca altera o anfitrião.
5. **Plano de aprovisionamento simulado** (`station plan`) - mostra o que um instalador real
   *faria* (o argv de cada passo capturado como dado) mais o
   texto completo da unidade systemd, e recusa-se a construir sequer um plano sobre uma
   verificação prévia falhada. Nada é executado.

A DS03 acrescenta a migração conservadora, com a mesma regra de "ler e descrever, nunca agir"
- não copia nada e nunca toca na origem:

6. **Inventário + plano de migração** (`migrate inventory` / `migrate
   plan`) - percorre uma cópia de origem (apenas os ficheiros que o git considera parte
   do projeto - um `.venv` local / saída de compilação está ignorado pelo git e
   nunca é visto), calcula o SHA-256 de cada ficheiro e classifica-os:
   `tracked-clean`, `tracked-modified`, `untracked`, `private` (uma
   `PrivacyPolicy` alargável: a pasta de documentos privados, `.env*`, `*.pem`,
   `id_ed25519*`, ...). Os commits feitos mas nunca enviados são registados
   à parte. O `migrate plan` associa cada classe ao seu **próprio** destino entre quatro
   destinos demonstravelmente separados (`MigrationDestinations.from_dict`
   recusa raízes iguais ou aninhadas), agrupa os commits por enviar, emite um
   manifesto completo de hashes e imprime `REFUSED` se um ficheiro privado alguma vez
   se resolvesse sob uma raiz partilhável.

A DS04 é a primeira entrega que executa um subprocesso - e continua
estritamente protegida:

7. **Receita de tarefa limitada + executor de espaço de trabalho** (`task validate` / `task
   run`) - uma `TaskRecipe` fixa uma `revision` (um nome de ramo simples é
   recusado) e um `command` da lista de permitidos (o `argv[0]` tem de estar nos
   `allowed_commands` da política de tarefas, ou a execução é `rejected` e nada
   arranca). O `task run` aloca `<base>/<task_id>/` - recusando um que
   já exista, para que **duas tarefas nunca partilhem um espaço de trabalho** - executa o
   comando aí com um **ambiente depurado** (apenas `PATH` / `HOME` /
   `LANG` / `TZ`; nunca um `GITHUB_TOKEN`,
   `AWS_SECRET_ACCESS_KEY`, `ANTHROPIC_API_KEY`, `SSH_AUTH_SOCK` herdado),
   limitado por `timeout_seconds` e, ao esgotar-se o tempo ou ao cancelar, **mata todo o
   grupo de processos** - provado por um teste real que lança um
   filho de um filho e confirma que ambos desapareceram. Um `..`, um caminho
   absoluto ou uma ligação simbólica para fora do espaço de trabalho nos `input_paths` da receita é
   recusado. Não implementa nada. A saída do filho é lida continuamente enquanto ele corre e de cada fluxo só se guardam os últimos 8 KiB, pelo que uma compilação ou execução de testes muito verbosa não pode nem bloquear num pipe cheio nem fazer crescer a memória do anfitrião.

A DS05 acrescenta durabilidade - uma fila de tarefas e o seu diário de execução
que sobrevivem a um reinício do processo. Regista, não executa:

8. **Fila durável + diário de execução** (`queue enqueue` / `status` /
   `reconcile` / `journal`) - um armazém SQLite (WAL, transações imediatas
   para a concessão). O `enqueue` é idempotente - uma segunda chamada
   com o mesmo `task_id` devolve `created=False`, **nunca um segundo
   trabalho**. O `lease(worker, ttl)` reclama a entrada `queued` mais antiga;
   o `reconcile()` devolve uma concessão caducada a `queued` (seguro em cada
   arranque). Um `record_result` de um trabalhador que já não detém a
   concessão é **rejeitado, não aceite como concluído** - uma interrupção nunca
   se torna um falso êxito. Se a impressão digital da base observada no momento do
   resultado diferir da registada no `enqueue`, o resultado é guardado como
   `failed` / não promovível **mesmo com código de saída 0**. O evento
   `completed` do diário leva sempre `revision` + `recipe_fingerprint`; o
   diário guarda apenas caudas truncadas e o `prune_journal` limita as linhas, pelo que o
   disco se mantém limitado.

A DS06 acrescenta um fornecedor de IA intermutável - apenas o simulado determinístico,
por detrás de um contrato de segurança. Devolve uma cadeia que uma pessoa lê; não liga
nada ao executor, à fila nem a uma implementação:

9. **Fornecedor de IA intermutável** (`provider suggest`) - uma costura `AIProvider`;
   o `FakeProvider(scenario=...)` é totalmente determinístico. O `run_provider_step`
   transforma um **tempo limite**, um **esgotamento de quota** ou uma **saída malformada**
   do fornecedor num resultado nomeado e limitado (nunca uma exceção que escale); um
   `ProviderBudget` configurado (chamadas / tokens / custo) **pára o passo antes de o exceder**,
   sem chamada feita; e a resposta do fornecedor é **dado, nunca instruções** - uma
   sugestão que diga "ignora as instruções anteriores / implementa já / dá-me root" é
   copiada à letra, o `injection_flagged` fica definido, e
   `grants_no_permissions` / `triggers_no_deploy` continuam verdadeiros para **todos** os
   resultados. Que fornecedor real usar, e a sua autorização, é uma decisão
   do utilizador (hoje `kind` tem de ser `"fake"`).

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}

$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.1.6", "maturity": "functional", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

Não há invocação por omissão para lá da demonstração que o `run.sh` realiza,
nem interface gráfica nesta entrega - veja
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) para a superfície real e
completa de comandos.

Mais dois comandos, `plugin list` e `serve`, cobrem o ciclo de vida dos plugins e uma API HTTP local autenticada (só loopback, token Bearer). Um plugin fica inerte até ser ativado contra o SHA-256 aprovado dos seus ficheiros e só pode acrescentar verificações, relatórios e geradores nomeados (declarados com `provides` em `plugin.json`, executados com `plugin run` ou pela API, cada um limitado por um tempo limite e um tamanho máximo); a API não executa nenhuma tarefa nem implementa nada. Veja [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) e [docs/PLUGINS.md](docs/PLUGINS.md). Além disso, o executor de tarefas envolve o comando numa sandbox bubblewrap ou systemd-run quando o equipamento a tem (sem home, sem rede a não ser que a política a abra, só a área de trabalho gravável), limita os argumentos de cada comando, obtém a revisão fixada, limita as tarefas em simultâneo e remove a área de trabalho no fim; os plugins correm por omissão no seu próprio processo. Nada disto correu ainda num equipamento real.

## 🧩 Papel no HYDRA-UMC

O **HYDRA-UMC-DEV-SERVER** é o anfitrião de desenvolvimento do ecossistema: executa tarefas de compilação e de testes limitadas e permitidas em áreas de trabalho isoladas e coordena candidatos de reparação com o `HYDRA-UMC-OPS-AGENT`. Nunca aprova as suas próprias tarefas e não implanta nada; a entrega a um nó passa sempre pelo `HYDRA-UMC-UPDATER`.

## 🏛️ Arquitetura

<p align="center">
  <img src="images/architecture.svg" alt="HYDRA-UMC-DEV-SERVER architecture" width="100%">
</p>

### ARQUITETURA E DECISÕES DE DESENHO

- **As aprovações são assimétricas e ligadas ao patch.** Um ciclo de reparação verifica candidatos e aprovações apenas com chaves públicas Ed25519 (um segredo HMAC partilhado tem de estar também do lado que verifica, pelo que quem pudesse verificar poderia falsificar; `allow_symmetric_keys` mantém-no como opção voluntária). Uma aprovação nomeia o patch que aprova (`approved_patch_ref`) e traz uma validade (`expires_at`, UTC); ambos são assinados, e um ciclo recusa uma aprovação de outro patch, sem eles ou expirada.
- **A sandbox foi executada num kernel real.** A sandbox `systemd-run` foi executada num anfitrião Linux com systemd (tests/test_sandbox_real_host.py): uma tarefa escreve no seu espaço de trabalho e em mais lado nenhum, não consegue ler a pasta pessoal do utilizador do serviço, não tem rede e é morta pelo kernel quando usa cinco vezes o seu `MemoryMax`. A execução descobriu duas falhas que os testes da linha de comandos não podiam ver: um espaço de trabalho em `/tmp` ou `/var/tmp` fazia a unidade falhar (estado 226) até ser montado com `BindPaths`, e um em `/home`, `/root` ou `/run/user` não é alcançável de todo, pelo que agora é recusado com o motivo antes de correr o que quer que seja. Os testes são ignorados, dizendo porquê, num anfitrião sem sandbox utilizável; o bubblewrap não foi executado. Se o pacote opcional `cryptography` estiver instalado, a derivação da chave pública e a assinatura passam por ele (tempo constante) em vez do código puro da RFC 8032; `signing_backend()` diz qual.
- **Nenhuma tarefa tem permissão de implementação por omissão.** Este é o
  critério de aceitação literal da própria DS01, imposto pelo valor por omissão do dataclass
  `TaskPolicy` - e não apenas afirmado em prosa - e coberto por um teste dedicado
  para cada forma de um documento tentar contrabandeá-lo (um campo em falta,
  um com erro ortográfico, um valor não booleano).
- **Um coletor reporta uma falha real e honesta - nunca adivinha.**
  O `scan_project_manifests()` devolver um `ManifestScanIssue` para um manifesto
  presente mas partido, em vez de o descartar em silêncio, é o padrão estabelecido
  que este ecossistema já usa noutro sítio (veja o `inventory.py` do próprio
  HYDRA-UMC-OPS-AGENT) - reutilizado aqui, não reinventado.
- **A propriedade e as relações entre projetos não são deste repositório
  para voltar a decidir.** O [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e o
  [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) documentam a
  tabela de propriedade de estado deste repositório e o seu agrupamento de 17
  relações entre projetos em necessárias/opcionais/só de desenvolvimento.
- **Só a biblioteca padrão nesta entrega.** O `config validate` e o `inventory
  scan` não precisam de nenhuma dependência de terceiros - uma entrega posterior acrescenta
  uma apenas quando o código dessa entrega genuinamente a precisar (um controlador de fila durável
  para a DS05, um SDK de fornecedor de IA para a DS06), nunca
  de forma especulativa.
- **Esta entrega só valida e descobre - não executa
  nada.** Não há espaço de trabalho, execução de tarefas, fila nem
  chamada de rede em nenhum ponto deste repositório ainda.

## 🚀 Início rápido

Requer Python 3.11 ou superior.

```bash
./build.sh  # Linux, macOS (build.bat on Windows)
./run.sh    # demo: inventory scan, then config validate
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

## 🧪 Testes

442 testes automáticos correm com `python -m pytest -q tests`. Os testes da sandbox são saltados, a dizer porquê, num equipamento sem sandbox utilizável; nenhum precisa de hardware.

A CI executa `HYDRA_UMC_CI=1 python tools/ci_validate.py`, que verifica o manifesto, os documentos, os oito README e as imagens.

## 🏗️ Compilação e publicação

```bash
chmod +x build.sh   # uma só vez
./build.sh          # cria o .venv, pip install -e ".[dev]", verificação de compilação + testes
./run.sh                                  # demonstração real: inventory scan contra este
                                           # espaço de trabalho do GitHub, depois config validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

No Windows: `build.bat` e depois `run.bat` (a mesma demonstração sem argumentos) /
`run.bat inventory scan ...` / `run.bat config validate ...`.
O `build-test.sh`/`.bat` faz a mesma verificação não alteradora de sintaxe Python
que o fluxo de CI deste projeto faz, sem tocar na versão do projeto nem no CHANGELOG -
NÃO executa a suite de testes em si; execute `./build.sh`/`build.bat` (ou
`python -m unittest discover -s tests` diretamente) para a suite de testes local completa.

**Resolução de problemas**

- O `config validate` termina com `1` e `INVALID: ...`: leia a mensagem - lista
  todos os campos que falharam, não apenas o primeiro. Consulte
  [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) para a forma exata esperada.
- O `inventory scan` reporta um problema num diretório que esperava limpo:
  esse diretório tem um `hydra-umc.project.json` presente mas ilegível,
  malformado ou sem um campo obrigatório - um diretório sem nenhum manifesto
  nunca é reportado como problema.

## 📂 Estrutura do repositório

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository structure of HYDRA-UMC-DEV-SERVER" width="100%">
</p>

<details>
<summary>Versão em texto da árvore</summary>

```text
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/   código-fonte
│   ├── __init__.py             Versão do pacote
│   ├── config.py               Esquema + validação de HostProfile/ToolchainPolicy/TaskPolicy (DS01)
│   ├── inventory.py            Descoberta real, só de leitura, de hydra-umc.project.json (DS01)
│   ├── remote_station.py       RemoteStationProfile: identidade + acesso remoto + ferramentas (DS02)
│   ├── preflight.py            Verificação de prontidão do anfitrião, só de leitura, através de um inspetor injetável (DS02)
│   ├── provision.py            Plano de aprovisionamento simulado + texto da unidade systemd, nunca executado (DS02)
│   ├── migration.py            Inventário de migração conservadora + plano de destinos separados, não copia nada (DS03)
│   ├── workspace.py            Espaço de trabalho isolado por tarefa; recusa ../, absolutos e ligações simbólicas para fora (DS04)
│   ├── recipe.py               TaskRecipe: revisão fixa + comando da lista de permitidos (DS04)
│   ├── runner.py               Executor limitado: ambiente depurado, tempo limite, morte de todo o grupo de processos (DS04)
│   ├── durable_queue.py        Fila SQLite durável + concessões + diário de execução só de acrescento, sobrevive a um reinício (DS05)
│   ├── ai_provider.py          Costura de fornecedor de IA intermutável + contrato de segurança; só o simulado determinístico (DS06)
│   ├── incident_transport.py   Mensagens de incidente assinadas com HMAC + verificação + sessão completa de ida e volta (DS07)
│   ├── repair_cycle.py         Ciclo com portas reprodução→...→verificação com reversão + a porta do candidato (DS08)
│   ├── operations.py           Cópia de segurança/restauro verificados do estado + verificação de saúde operacional (DS09)
│   ├── delivery.py             Manifesto de entrega (sha256 por ficheiro entregue) + avaliação honesta de maturidade, nunca afirma de mais (DS10)
│   ├── cli.py                  Ponto de entrada dos subcomandos config / inventory / station / migrate / task / queue / provider / incident / repair / ops / deliver
│   ├── api.py                  Uma pequena API HTTP autenticada, só em loopback (todas as rotas exceto a de saúde pedem um token)
│   ├── identifiers.py          O único sítio que diz o aspeto que um nome (conta, caminho, id de tarefa ou de worker) pode ter
│   ├── plugins.py              Ciclo de vida dos plugins: descobrir, validar, ativar, executar, desativar
│   ├── sandbox.py              Isolamento ao nível do sistema operativo do executor de tarefas
│   ├── signing.py              Assinaturas Ed25519 para candidatos de reparação, aprovações e manifestos de cópia de segurança
│   ├── taskflow.py             O que rodeia a execução de uma tarefa: preparar o repositório na revisão fixada, o limite de concorrência e a vida da área de trabalho
│   └── worker.py               O ciclo do worker que leva uma tarefa do arrendamento ao resultado
├── configs/                    documentos de configuração de exemplo
├── tests/                      testes de cada módulo e das configurações de exemplo
├── docs/                       documentos do projeto
├── examples/plugins/           Plugins de exemplo: um relatório e um gerador
├── examples/                   plugins/: plugins de exemplo (host-report, readme-generator)
├── images/                     Multimédia e ícones da aplicação
├── tools/                      ferramentas do projeto e verificações da CI
├── .github/                    fluxo de CI e modelos de problemas
├── build.sh / build.bat        venv + instalação editável + verificação de compilação + testes
├── run.sh / run.bat            Demonstração real de inventory scan + config validate (sem argumentos), ou reencaminha um comando real da CLI
├── bump_version.py             Subida de versão ao estilo conta-quilómetros (executada só pelo comando `bump` explícito)
├── bump_manifest_version.py    Sincroniza a versão do hydra-umc.project.json com a nativa (--sync)
├── CHANGELOG.md                o que mudou em cada versão
├── build-test.sh               verificação de compilação sem alterações
├── hydra-umc.project.json      manifesto: versão, maturidade, família
├── pyproject.toml              metadados do pacote
└── test.sh                     executa os testes
```

</details>

## 🗺️ Roteiro e limites conhecidos

**Limites conhecidos hoje**

Esta versão entrega a DS01 até à DS10 - o plano de dez entregas está
concluído. Cada entrega, por ordem:

- **DS02 - Estação remota reproduzível.** ✅ Entregue: um perfil de estação
  remota validado, uma verificação prévia do anfitrião só de leitura e um plano de aprovisionamento
  simulado (subcomandos `station`). Nenhum anfitrião é alterado e nenhum
  passo é executado.
- **DS03 - Migração conservadora.** ✅ Entregue: calcular o hash e classificar cada
  ficheiro de uma cópia de origem e planear cada classe (limpo / modificado /
  não acompanhado / privado) para o seu próprio destino separado, com um pacote
  para os commits por enviar (subcomandos `migrate`). Não copia nada e
  nunca toca na origem. Executar um plano aprovado é uma entrega posterior.
- **DS04 - Espaço de trabalho e executor limitado.** ✅ Entregue: espaço de trabalho
  isolado por tarefa (duas tarefas nunca colidem; caminhos `..`, absolutos e de ligações
  simbólicas para fora do espaço de trabalho recusados), apenas um comando da lista de permitidos, um ambiente
  depurado e um tempo limite que mata todo o grupo de processos
  (subcomandos `task`). Executa um subprocesso mas não implementa nada.
- **DS05 - Fila durável e resultados rastreáveis.** ✅ Entregue: uma fila SQLite
  com concessões e um diário de execução só de acrescento que sobrevivem a um
  reinício; um enfileiramento duplicado nunca é um segundo trabalho, uma interrupção
  nunca um falso êxito, uma base movida bloqueia a promoção (subcomandos
  `queue`).
- **DS06 - Fornecedor de IA intermutável.** ✅ Entregue (a metade simulada): um
  fornecedor simulado determinístico por detrás de um contrato de segurança - tempo limite /
  malformado / quota tornam-se resultados limitados, um orçamento pára o passo,
  a sugestão é dado inerte que não concede nada e não implementa nada
  (`provider suggest`). O fornecedor real é uma decisão do utilizador.
- **DS07 - Incidentes coordenados com o HYDRA-UMC-OPS-AGENT.** ✅ Entregue:
  um transporte de incidentes autenticado com HMAC, com verificações de repetição / personificação /
  sobrecarga / versão e uma ida e volta completa de submissão → diagnóstico → verificação
  pós-implementação que reconcilia após uma ligação caída
  (`incident verify`).
- **DS08 - Primeiro ciclo de reparação totalmente controlado.** ✅ Entregue: uma
  máquina de estados com portas reprodução→incidente→correção→regressão→build-test→aprovação→instalação isolada→verificação
  que bloqueia um candidato adulterado ou mal dirigido e
  reverte perante uma verificação pós-instalação falhada (`repair check-candidate`).
- **DS09 - Operação/restauro estáveis.** ✅ Entregue: verificações de saúde
  operacional sobre a fila e o disco, e uma cópia de segurança/restauro
  verificados do estado que recusa uma cópia de outra instância ou uma
  corrompida (subcomandos `ops`).
- **DS10 - Pacote de entrega e avaliação honesta de maturidade.** ✅
  Entregue: o `deliver manifest` regista um sha256 para cada ficheiro entregue
  e lê de volta a superfície real da CLI, a versão e o número de testes; o `deliver
  evaluate` reporta cada uma das dez entregas contra prova real
  (a DS06 é `partial` - só o simulado é entregue), lista sete limitações
  com clareza e reporta uma `overall_maturity` fixada no código como `functional`.

**Maturidade.** O plano está concluído; a maturidade é `functional`: o software está construído e coberto por testes, mas não foi verificado em hardware nem em serviços reais, o que é um passo separado e posterior. O que há neste repositório é uma implementação funcional e testada de - um esquema de configuração, perfis validados,
planos simulados, um executor limitado, uma fila durável, um fornecedor simulado, um
transporte assinado, um ciclo de reparação com portas, cópias de segurança verificadas e uma
avaliação que se recusa a afirmar de mais. Nada aqui aprovisiona um anfitrião,
executa uma implementação, liga as peças num ciclo de trabalhador nem tocou
em hardware de destino. O `deliver evaluate` di-lo exatamente, e a sua
lista `known_limitations` é a lista honesta de tarefas por fazer. Veja
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para o que cada entrega inclui
e exclui explicitamente.

## 🌍 Idiomas

Este README e os documentos do repositório existem em oito idiomas: inglês, espanhol, alemão, francês, italiano, japonês, chinês e português (Portugal). São escritos em conjunto e a CI verifica que os oito ficheiros têm as mesmas secções e as mesmas ligações. Este repositório não tem ecrã nem catálogo de mensagens próprios, por isso não há textos de interface para traduzir.

## 🔗 Projetos relacionados

Este projeto faz parte do ecossistema de robótica HYDRA-UMC do mesmo autor (JuanenRac / Electro Hobby 3D). Vale a pena conhecê-los, porque um pedido pode ser, na verdade, sobre um destes e não sobre este repositório.

**Diretamente relacionados**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — é dono do ciclo de vida dos incidentes de manutenção (evidências, diagnóstico, alteração aprovada por uma pessoa, implementação canário, verificação); o DEV-SERVER coordena-se com ele em vez de o substituir, e nunca aprova as suas próprias tarefas.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — o contrato JSON-Schema partilhado contra o qual será validada toda a troca de tarefas/resultados entre o DEV-SERVER e o resto do ecossistema, quando esse contrato existir.
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — o consumidor real de um candidato construído pelo DEV-SERVER e aprovado pelo OPS-AGENT; a entrega a um nó passa sempre pelo caminho atómico-por-verificação do próprio UPDATER, nunca por uma cópia direta a partir de um executor.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — outro irmão de «Operações do ecossistema»: constrói uma imagem nova do CM5 em vez de alojar trabalho de desenvolvimento.

**Também fazem parte do ecossistema**

*Hardware e plataforma centrais*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — o desenho da placa-mãe do braço robótico: anfitrião CM5 + STM32H745 de dois núcleos, pensado para orquestrar até 8 braços de ferramenta por CAN-OTA/SPI-OTA (firmware numa fase inicial; ainda sem placa montada).
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — camada de produto reproduzível do Raspberry Pi OS para o CM5: agente só de leitura, configuração/perfis validados, aprovisionamento Wi-Fi de primeiro contacto.

*Backend central e clientes*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — o back-end headless real (REST/WebSocket) com que todos os clientes de controlo realmente comunicam.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — painel web de controlo com visualização 3D em tempo real de vários robôs.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centro de comando de enxame para desktop (PySide6) para vários servidores ao mesmo tempo.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — aplicação Android nativa de controlo, com início de sessão biométrico e um companheiro Wear OS emparelhado.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — aplicação de controlo para iOS/iPadOS (Flutter) com sincronização WebSocket em tempo real.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interface tátil nativa para o ecrã tátil DSI de 7" integrado, executada no próprio CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — criador/editor gráfico de URDF para desktop que envia os modelos concluídos para o catálogo do STUDIO.
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — editor de modelos STL para desktop que transforma/substitui/remove/adiciona peças reais no mesmo catálogo de modelos que o HYDRA-UMC-EDITOR-URDF também edita.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — fronteira de coordenação para frotas AGV/AMR através de um publicador MQTT VDA 5050 (testado apenas contra uma frota emulada).
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordenador de células CNC de alto nível com acesso ao estado GRBL e aos bytes de controlo (testado apenas contra um emulador).
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — fronteira de coordenação para droides com patas/humanoides, com um emissor de comandos para o Boston Dynamics Spot (testado apenas contra um emulador).
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordenador de células laser que lê 3 sinais GPIO (chave, caixa e interlock) (testado apenas contra um chip simulado; não pode armar nem disparar um laser).
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordenador seguro de fluxo de placa de alto nível para pick-and-place com OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — fronteira de coordenação segura para impressoras 3D Moonraker/Klipper, com comandos de trabalho reais protegidos por portas.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordenador com um transporte ROS 2 baseado em rclpy importado sob demanda (ainda não executado contra uma instalação ROS 2).
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — fronteira de coordenação para UAV com câmara, com um emissor de comandos MAVLink (testado apenas contra um emulador).

*Plataforma de ferramentas URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware da placa física Universal Robot Tool Controller, mais de 25 perfis de ferramenta por barramento CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — ferramenta gráfica de gravação para desktop das placas URTC, por CAN-OTA e também SWD/JTAG de chip completo.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — ferramenta de diagnóstico CAN em tempo real para desktop das placas URTC, com um painel por perfil de ferramenta.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternativa no navegador ao URTC-TESTER através da Web Serial API, sem instalação local.
- **[URTC-GATEWAY](https://github.com/JuanenRac/URTC-GATEWAY)** — gateway à frente do barramento CAN do URTC: lista de identificadores permitidos, limite de taxa e chave de sessão; software testado num computador, ainda não num barramento real.

*Nó de IA de visão (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — centro de integração do pipeline de visão Hailo-8, com uma verificação real de prontidão de hardware por fase.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registo real de modelos compilados com verificação segura de carga por arquitetura Hailo e soma de verificação.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — pipeline GStreamer real e gerador de configuração MediaMTX com uma fronteira de integração HailoRT real.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — lei de correção de servovisão baseada em posição com autorização condicionada ao estado da zona; ainda sem estimativa de pose por câmara.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — lógica v0 de violação de zonas, atualidade da calibração e pedido de E-STOP que lê as posições dos objetos de um ficheiro; nenhum detetor a alimenta e ainda não há E-STOP físico ligado.

*Nó de IA cognitiva (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — centro de integração do pipeline cognitivo do Hailo-10 (orquestração de LLM/VLA/voz).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — codificação/descodificação real de tokens de ação e geração de trajetórias para um modelo Visão-Linguagem-Ação.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — front-end de voz real (VAD + analisador de intenções) com um relé para o relógio limitado e protegido por confirmação.
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — decomposição real de tarefas baseada em regras e recuperação semântica de erros sobre os códigos de erro do MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — pesquisa real de documentos TF-IDF só com a biblioteca padrão sobre a documentação Markdown deste ecossistema.
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — técnico de manutenção de IA local, protegido por políticas, para o próprio ecossistema: observa, diagnostica e propõe correções; os dois níveis de maior risco não estão implementados de propósito.

*Orquestração e enxame*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — centro de integração com um contrato real de relatório de saúde gRPC/Protobuf e uma máquina de estados de missões.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — fila real de trabalhos por prioridade com deduplicação, sobre uma API HTTP real.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — um vigilante real de saúde da frota por gRPC, com repetição/recuo próprios e deteção de identidade incoerente.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — planeador real de trajetórias 3D baseado em RRT com validação real de colisões com obstáculos e espaço de trabalho.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — sincronização real de estado CRDT LWW-Element-Map, testada por propriedades para a convergência de várias células.

*Gémeo digital e simulação*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — centro de integração do motor de gémeo digital, com um contrato real de sincronização de compatibilidade de versões.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — encaminhador hardware-in-the-loop com um interlock de software de colisão entre a simulação e o hardware real (testado sem hardware real).
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — cinemática direta real e validação de limites de juntas sobre um subconjunto real de URDF.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — gerador procedural real de cenas 2D com exportação de anotações YOLO/COCO.

*Dados e análise*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — armazém real de séries temporais sobre sqlite3 com uma API HTTP real de ingestão/consulta.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — detetor real de anomalias por FFT e linha de base estatística, com monitorização de deriva.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — cálculo real de OEE/disponibilidade sobre o histórico do DATALAKE, com exportação CSV reprodutível.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — pipeline real de ingestão CAN/WebSocket para o DATALAKE, com deduplicação por sequência.

*Gateway industrial*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — centro de integração que retransmite para protocolos industriais, com uma camada real de lista de comandos permitidos e contrapressão.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — espaço de endereços OPC-UA real, verificado com uma sessão de cliente real do protocolo binário.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — broker MQTT real com autenticação opcional por cliente e ACL de tópicos.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — endpoints XML MTConnect `/probe` e `/current` reais com saída em modo degradado.

*Ferramentas complementares*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — painéis de Resumos Inteligentes e Realce de Anomalias sobre o DATALAKE/ANOMALY-DETECTOR, com um recurso estatístico honesto.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — CLI da frota com um contrato de códigos de saída real e estável, um cliente vivo genuíno da API do HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — aplicação companheira WearOS com padrões de alerta tátil e um relé de voz para o telemóvel emparelhado (ainda não executada num relógio físico).
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — catálogo de capacidades de adaptadores externos, só GET por desenho.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware de um rack de montagem de placas com descodificação real do ID da ferramenta e lógica de pré-aquecimento Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware mais um companheiro de visão em Python real para uma cabeça de ferramenta de inspeção térmica/RGB.

## 📚 Documentação

Onde ler mais:

* **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — cada subcomando, as suas opções e o contrato de códigos de saída.
* **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — a forma JSON real de `HostProfile`/`ToolchainPolicy`/`TaskPolicy`.
* **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — propósito, os dois modos de funcionamento, âmbito inicial e disposição do disco.
* **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — o mapa completo das 17 relações e a tabela de propriedade de estado.
* [Base de segurança do ecossistema](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md)
* [Modelo de ameaças do ecossistema](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md)
* [Registo de alterações deste repositório](CHANGELOG.md)
* [Licença deste repositório](LICENSE.md)

## 🤝 Contribuir e comunidade

* Antes de um pull request execute `HYDRA_UMC_CI=1 py -3 tools/ci_validate.py` (ou `HYDRA_UMC_CI=1 python3 tools/ci_validate.py`): tem de imprimir `CI_VALIDATION=PASS`. Não execute `build.sh` nem `build.bat` para esta verificação; compilar não é verificar.
* Os oito README são escritos a partir de uma única fonte em HYDRA-UMC-DOCS; não os edite à mão. Altere a fonte e escreva-os de novo com `tools/make_readmes.py`.
* Não afirme num README o que não foi executado: diga «simulado» ou «não testado em hardware» quando for a verdade.
* Consulte [CONTRIBUTING.md](CONTRIBUTING.md), o [código de conduta](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md) e [SUPPORT.md](SUPPORT.md).

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENÇA

GPL-3.0-or-later - [LICENSE](LICENSE).

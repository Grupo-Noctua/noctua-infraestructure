# Frontends A/B no load balancer

As imagens podem exibir um selo no canto inferior direito em todas as telas:

| Variante | Identificação | Configuração do deploy |
|---|---|---|
| A | **FRONTEND A**, azul | `frontend_image` |
| B | **FRONTEND B**, laranja | `frontend_image_b` |

O Dockerfile `files/frontend-variant/Dockerfile` deriva as duas imagens do mesmo
build do frontend. Acrescenta o selo ao HTML fora da raiz React; JavaScript, CSS,
rotas e proxy são herdados da imagem-base. Não use uma imagem já identificada como
base de outra variante.

## Construir e publicar

Na raiz da infraestrutura, após `docker login`:

```powershell
python scripts/publish_images.py --namespace SEU_USUARIO --release release-lb-001 --frontend-variants
```

O script constrói e verifica backend e os dois frontends antes do primeiro push.
As tags publicadas são:

- `SEU_USUARIO/noctua-backend:release-lb-001`
- `SEU_USUARIO/noctua-frontend:release-lb-001` (A)
- `SEU_USUARIO/noctua-frontend:release-lb-001-b` (B)

O build intermediário `release-lb-001-base` permanece local. Use `--build-only`
para construir e testar sem publicar. Sem `--frontend-variants`, a publicação
continua produzindo o frontend original.

### Derivar de uma imagem existente

Para reaproveitar um frontend já construído, sem reconstruir o backend:

```powershell
docker build --platform linux/amd64 --build-arg FRONTEND_BASE=SEU_USUARIO/noctua-frontend:RELEASE_BASE --build-arg FRONTEND_VARIANT=A -t SEU_USUARIO/noctua-frontend:release-lb-001 ./files/frontend-variant
docker build --platform linux/amd64 --build-arg FRONTEND_BASE=SEU_USUARIO/noctua-frontend:RELEASE_BASE --build-arg FRONTEND_VARIANT=B -t SEU_USUARIO/noctua-frontend:release-lb-001-b ./files/frontend-variant
python tests/check_frontend_image.py SEU_USUARIO/noctua-frontend:release-lb-001 --variant A
python tests/check_frontend_image.py SEU_USUARIO/noctua-frontend:release-lb-001-b --variant B
docker push SEU_USUARIO/noctua-frontend:release-lb-001
docker push SEU_USUARIO/noctua-frontend:release-lb-001-b
docker image inspect SEU_USUARIO/noctua-frontend:release-lb-001 --format '{{json .RepoDigests}}'
docker image inspect SEU_USUARIO/noctua-frontend:release-lb-001-b --format '{{json .RepoDigests}}'
```

Execute os pushes somente após ambos os testes passarem. Copie as referências
publicadas `repositorio@sha256:...`, com prefixo `docker.io/`, para a configuração.

## Configurar e implantar

Em `files/application.local.json`, preencha os digests reais:

```json
{
  "frontend_image": "docker.io/SEU_USUARIO/noctua-frontend@sha256:DIGEST_A",
  "frontend_image_b": "docker.io/SEU_USUARIO/noctua-frontend@sha256:DIGEST_B"
}
```

Esse trecho deve ser incorporado à configuração existente. O segundo campo é
opcional: ausente ou `""` significa usar `frontend_image` em todos os nós.
As duas imagens precisam ter referências distintas; o modo A/B exige pelo menos
duas instâncias frontend.

**n8n:** reimporte `application-n8n-noctua.json`, reassocie a credencial AWS aos
quatro nós HTTP e inicie uma nova execução em **Start application deploy**.
O workflow lê o JSON e o script remoto pelos volumes existentes do Compose.

**CLI:** execute `python scripts/application.py deploy`.

Ambos os caminhos ordenam os IDs das instâncias e distribuem A, B, A, B… nessa
ordem. Com duas instâncias, cada uma recebe uma imagem. A atribuição é estável
enquanto o conjunto de IDs não mudar. Novas instâncias ou substituições no ASG
precisam de nova execução do deploy; o workflow não é disparado automaticamente
por eventos de Auto Scaling.

Ordem das etapas com dois frontends:

1. Banco e backend.
2. Assets **das duas imagens em cada frontend**.
3. Imagem A no primeiro frontend e B no segundo, com validação individual.

O n8n retorna seis resultados: banco, backend, duas preparações de assets e dois
deploys frontend. Se a preparação de assets falhar, o fluxo não avança para a
troca do HTML. Os assets antigos também são retidos para abas abertas e rollback.

## Demonstrar a distribuição

Abra a URL do ALB retornada pelo deploy e recarregue a página para observar os
selos. O selo identifica a variante que entregou o **HTML daquela navegação**;
chamadas de API e assets podem chegar a outros nós.

Não há garantia de alternância A/B a cada F5. Ambos os targets precisam estar
saudáveis, e stickiness pode manter requisições no mesmo target. Navegar internamente
pela SPA não busca outro HTML; faça uma recarga completa.

Também é possível observar várias respostas sem cookies pelo PowerShell:

```powershell
$url = 'http://DNS_DO_ALB'
1..20 | ForEach-Object {
    $html = curl.exe --fail --silent --show-error -H 'Cache-Control: no-cache' "$url/?lb-demo=$_"
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao consultar o ALB' }
    [regex]::Match(($html -join "`n"), 'FRONTEND [AB]').Value
}
```

## Validação local desta alteração

Foram construídas e verificadas as imagens locais `noctua-frontend:lb-a` e
`noctua-frontend:lb-b`, derivadas de
`elersonalves/noctua-frontend:release-20261102-dashboard-03`.
Os testes verificam selo, cache do HTML, JavaScript, rotas SPA, download DOCX,
healthcheck e proxy HTTP.

Também passaram os 53 testes da suíte Python/Node e a execução do workflow n8n
em container descartável, com duas variantes configuradas e nós HTTP reais contra
respostas AWS simuladas (`--http --scenario create`).

## Publicação e implantação — 02/11/2026

As imagens validadas foram publicadas no repositório `elersonalves/noctua-frontend`:

| Variante | Tag | Instância |
|---|---|---|
| A | `release-lb-001` | `i-044cc689c92e27fb6` |
| B | `release-lb-001-b` | `i-0767856a89f924b69` |

- A: `sha256:ee5e4cb35a2636d7910f833d787067303c5abf45d94c73c521c3fe305c83650d`
- B: `sha256:b6d2ab9d7cab664bd3d87fe8f74e913ab8009034facd8ec651b95329a905ee18`
- Configuração local atualizada com os dois digests.
- Backend existente revalidado antes das etapas de frontend.
- Assets preparados em ambos os nós, seguidos dos deploys e smoke tests individuais.
- Os dois targets ficaram `healthy`. Em 20 requisições ao ALB foram observados
  10 HTMLs A e 10 HTMLs B.
- URL: `http://noctua-application-alb-2031967245.us-east-1.elb.amazonaws.com`.
- Workflow n8n `NTbwjpWJ8NpdW7Q4` atualizado com os três nós alterados para A/B,
  preservando credenciais e demais configurações. Backup anterior no container:
  `/home/node/.n8n/application-before-lb-20261102.json`.

O deploy completo inicialmente parou com `Schema checksum changed`: o SQL local
difere do baseline registrado no banco. A implantação desta release foi concluída
somente para os frontends, via CLI/SSM, após verificar o backend existente. O schema
não foi alterado. Uma próxima execução **completa** do CLI/n8n ainda exige reconciliar
essa divergência de baseline; atualizar o workflow não resolve a divergência do SQL.

# Plataforma documental de P9

- **Etapa:** P9 — Contratos, documentos y aceptación
- **Fecha de verificación local:** 13 de agosto de 2026
- **Decisiones rectoras:** ADR 0017 y ADR 0018

Este documento registra la operación sustituible de render, almacenamiento privado, análisis de
malware y jobs. No selecciona infraestructura productiva ni amplía la semántica contractual.

## Entorno canónico de emisión

Las emisiones definitivas solo se procesan en `claridez-render-weasyprint-69.0-debian12-v1`,
construido por `apps/api/docker/render-worker.Dockerfile` sobre:

- Python `3.13.14-slim-bookworm`, índice oficial fijado por digest
  `sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8`;
- WeasyPrint `69.0` y lockfile de Python;
- DejaVu Sans `2.37-6`, Pango `1.50.12`, HarfBuzz `6.0.0`, libjpeg y libopenjp2 fijados;
- stylesheet, wordmark, fuentes y manifiesto de assets hasheados;
- `PYTHONHASHSEED=0`, `SOURCE_DATE_EPOCH=0`, PDF/A-3u y fuentes completas;
- límites de 20 segundos de CPU, 512 MiB de memoria virtual, 30 segundos por proceso y 2 MiB
  de entrada HTML, 25 MiB de salida y 250 páginas;
- validación estructural estricta del PDF generado antes de calcular el checksum y sellar el
  artefacto.

El fetcher solo reconoce `claridez-asset:wordmark`. JavaScript, estilos suministrados por la
plantilla, `@import`, red, `file://` y cualquier otro recurso fallan cerradamente. La imagen se
ejecuta como usuario no privilegiado. El artefacto emitido se almacena; nunca se reconstruye como
si fuese el original.

El spike final produjo dos veces un PDF multipágina de 1.060.929 bytes con tablas, español,
saltos y asset local, ambos con SHA-256
`93ee73e8fdddcf87d47a5fd1860e38b79cac95260dfb0964731ec44ffcb23d66`. Los probes de HTTP y
`file://` fallaron. Esta igualdad dentro de la misma imagen no establece igualdad entre plataformas.

## Almacenamiento privado

El dominio usa `PrivateObjectStorage` y no conoce buckets, ETag ni SDK de proveedor. P9 incluye:

- adaptador filesystem para desarrollo local, bajo `.runtime/documents` resuelto siempre desde la
  raíz del repositorio y compartido por Django y el worker, en un volumen privado y cifrado por la
  plataforma anfitriona;
- adaptador S3-compatible para una superficie productiva futura: create-only mediante
  `If-None-Match: *`, checksum SHA-256 propio enviado como checksum/metadata y SSE-S3 o SSE-KMS;
- claves CSPRNG opacas (`generated/...` o `quarantine/...`) sin nombres, correos ni otros datos
  personales;
- proxy de descarga autorizado por Claridez. Signed URLs pueden agregarse como otro adaptador sin
  cambiar la autorización.

La elección productiva entre S3, R2, B2 u otro servicio compatible sigue abierta. Todo candidato
debe demostrar operaciones create-only, cifrado, recuperación/versionado, lifecycle sin destruir
evidencia protegida, backup y restauración.

Los adaptadores filesystem y S3-compatible tratan la colisión como un conflicto create-only
atómico: nunca truncan, concatenan ni sustituyen el objeto ganador. En filesystem se escribe y
sincroniza un temporal exclusivo y se publica con un enlace atómico; en S3 se exige la precondición
`If-None-Match: *` y se reconocen `409/412` como colisión controlada.

### Coherencia y recuperación

Una emisión usa key determinista por UUID de versión: si el proceso cae después de escribir el
objeto, el reintento verifica SHA-256/tamaño y completa la fila sin sobrescribir. Un upload crea
primero fila y job durable; el finalizador solo avanza cuando el objeto existe y coincide. Un
objeto ausente o sustituido bloquea entrega y deja evidencia append-only.

El runbook de backup/restauración debe operar como una unidad:

1. detener nuevas escrituras documentales y el worker;
2. capturar un backup consistente de PostgreSQL y del namespace de objetos inmutables bajo el
   mismo identificador de corte; en un proveedor, incluir versiones y replicación independientes;
3. restaurar ambos conjuntos en un entorno aislado, sin apuntar al namespace original;
4. aplicar migraciones con el migrador y reconciliar privilegios;
5. ejecutar `documents_storage_verify --organization <uuid>` para cada organización y comprobar
   conteo, tamaño y SHA-256 antes de habilitar lecturas o workers;
6. conservar el backup y la evidencia del ensayo según la política de retención aplicable.

No existe proceso de disposición física en P9. La verificación no repara sobrescribiendo.

## Materialidad y privacidad de aceptación

`explicit-review-v1` compara únicamente campos contractuales autorizados del snapshot. Un cambio
observable produce `review_required`, sin decidir validez, nueva emisión, nueva aceptación, adenda,
terminación ni efectos sobre P8. Revisiones internas, procedencia técnica, renderer, metadata y
bytes diferentes sin cambio semántico no constituyen materialidad contractual por sí solos.

La evidencia de aceptación conserva siempre versión emitida, artefacto y SHA-256 exactos,
manifestación/versionado, contraparte, challenge, atribución, tiempos y correlación. IP y
user-agent son campos opcionales; su captura requiere habilitar por separado una política explícita
y está desactivada de forma predeterminada.

La migración documental final protege con triggers PostgreSQL la ausencia de borrado físico en las
22 tablas privadas. Los registros históricos append-only y las versiones estrictamente inmutables
conservan además sus guards de actualización y privilegios mínimos; las máquinas de estado siguen
mutando únicamente mediante sus transiciones controladas.

## Uploads y malware

Solo uploads externos PDF/JPEG/PNG pasan por cuarentena, validación conjunta de extensión, MIME,
magic bytes y parser, y ClamAV. El perfil local usa la imagen oficial
`clamav/clamav:1.4` fijada por digest
`sha256:7173cd3d57a839c6fee673b07246301e0d1f68f5a14a5ca063f502323bf1cc61`.
Se observaron ClamAV `1.4.6`, firmas `28087`, un archivo limpio como `clean`, EICAR como
`infected` y un puerto inaccesible como timeout; el código y las pruebas separan además
`unsupported`, error técnico e incompleto. Solo `clean` permite descarga.

Los artefactos del renderer controlado no pasan artificialmente por este scanner. Conservan
procedencia, SHA-256, verificación de integridad y autorización independientes.

## Jobs durables

`DocumentJob` es un ledger PostgreSQL tenant-aware. El worker usa `FOR UPDATE SKIP LOCKED`, lease,
at-least-once, idempotencia por tipo/clave, backoff acotado, máximo de intentos, estado `dead` y
`DocumentJobAttempt` append-only. Atiende finalización de upload, render, scan y verificación de
integridad. Una caída tras el claim recupera el lease vencido; repetir un efecto no duplica
artefactos ni evidencia.

El perfil `documents` de Compose inicia ClamAV y el worker canónico; Django web solo encola el
trabajo pesado.

```text
npm run documents:start
npm run documents:status
npm run documents:logs
npm run documents:stop
```

## Fuentes técnicas

Consultadas el 12 de agosto de 2026:

- [WeasyPrint 69.0 y changelog](https://doc.courtbouillon.org/weasyprint/latest/changelog.html)
- [API y seguridad del URL fetcher de WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html)
- [Conditional writes de Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
- [Boto3 `PutObject`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html)
- [Protocolo `clamd`](https://docs.clamav.net/manual/Usage/ClamdProtocol.html)
- [Imagen oficial Docker de ClamAV](https://docs.clamav.net/manual/Installing/Docker.html)

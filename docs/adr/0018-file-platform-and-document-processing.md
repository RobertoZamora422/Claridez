# ADR 0018 — Plataforma de archivos y procesamiento documental

- **Estado:** Aceptado
- **Fecha:** 2026-08-12
- **Reemplaza a:** No aplica; concreta el primer caso asíncrono exigido por ADR 0004
- **Reemplazado por:** No aplica

## Contexto

P9 introduce los primeros binarios privados, la generación server-side de PDF y el análisis de
contenido externo no confiable. Estas operaciones no caben de forma segura en PostgreSQL ni deben
depender del proceso HTTP: consumen CPU, memoria y tiempo, incorporan dependencias nativas y pueden
fallar por causas transitorias.

Un documento contractual debe conservar los bytes exactos emitidos. Regenerarlo después con otra
versión del motor, fuentes o sistema operativo no reconstruye necesariamente el original. Por eso
la reproducibilidad se define mediante un entorno canónico versionado y la conservación del
artefacto, no mediante igualdad binaria entre Windows y Linux.

Los artefactos generados por Claridez y los uploads externos tienen procedencias y niveles de
confianza distintos. Ambos requieren almacenamiento privado, checksum propio, inmutabilidad y
autorización; solo el contenido externo no confiable debe atravesar obligatoriamente cuarentena,
validación y malware antes de poder entregarse.

ADR 0004 difirió una cola hasta existir un proceso real. Render de PDF y análisis de malware son
ese primer caso. La decisión debe garantizar entrega durable, idempotencia, retries y operación sin
adoptar por popularidad un framework o proveedor todavía no evaluado.

## Decisiones aceptadas

### 1. Entorno canónico de render

1. Toda emisión definitiva se producirá exclusivamente en un entorno canónico de render,
   reproducible y versionado. Si el entorno aprobado no está disponible, la emisión falla cerrada;
   el proceso web local no podrá declarar definitivo un PDF alternativo.
2. Cada versión de entorno fijará y registrará:
   - sistema operativo e imagen de ejecución por digest inmutable;
   - motor PDF y versión exacta;
   - dependencias nativas relevantes;
   - fuentes y sus hashes;
   - assets y su manifest versionado;
   - configuración, locale, zona y opciones del renderer;
   - versión del código de render;
   - políticas de red, archivos y recursos permitidos.
3. Las fuentes y assets formarán parte de la entrada controlada. No se resolverán recursos remotos
   durante una emisión definitiva.
4. No se exige que Windows y Linux, ni dos plataformas heterogéneas, produzcan bytes idénticos. Los
   spikes podrán medir estabilidad entre ejecuciones del mismo entorno canónico. La emisión
   contractual solo es válida cuando se ejecuta en ese entorno.
5. El artefacto exitoso se conservará como evidencia original. No se dependerá de regenerarlo para
   reproducir lo emitido. Restaurar una copia íntegra de los mismos bytes no es regenerar.
6. Una versión emitida exitosa tendrá un único artefacto PDF sellado. Reintentos previos al sellado
   serán idempotentes y no publicarán duplicados. Un render posterior expresamente autorizado
   creará otra emisión y otro artefacto; no sobrescribirá el anterior ni heredará su aceptación. La
   mera diferencia de bytes no se interpreta como cambio contractual material.

### 2. Superficie segura de plantillas y renderer

1. El pipeline aceptará únicamente el lenguaje cerrado, versionado y validado por ADR 0017.
2. JavaScript permanecerá deshabilitado. No se permitirán código, imports, navegación de atributos,
   objetos ORM, `file://`, recursos externos arbitrarios, red saliente, fuentes remotas ni rutas del
   host.
3. HTML, CSS, URLs, imágenes, SVG y demás assets se restringirán a allowlists y parsers aprobados.
   SVG u otro formato activo o complejo se rechazará o rasterizará mediante un tratamiento
   explícito antes de entrar al renderer.
4. El proceso de render usará límites de tiempo, memoria, CPU, tamaño y número de páginas; un límite
   excedido será fallo, nunca una emisión parcial.
5. La imagen se ejecutará con usuario no privilegiado, filesystem de trabajo efímero, sin secretos
   innecesarios y con acceso únicamente a la entrada y salida del job. Los logs no contendrán el
   documento ni PII innecesaria.
6. El PDF resultante se validará estructuralmente antes de sellarse y almacenarse. Una validación
   fallida no produce una versión emitida disponible.

### 3. Checksums e integridad

Claridez mantendrá checksums propios y separados:

- SHA-256 de los bytes canónicos del snapshot contractual, conforme a ADR 0017;
- SHA-256 del contenido de la versión de plantilla y del manifest ordenado de fuentes/assets cuando
  corresponda;
- SHA-256 de los bytes exactos del artefacto PDF emitido;
- SHA-256 de los bytes originales exactos de cada upload externo.

Los hashes se calcularán en streaming sobre los bytes que efectivamente se almacenan, antes de
marcar el objeto como disponible, y se persistirán en metadata autoritativa de PostgreSQL. Una
verificación posterior a escritura, una restauración, una auditoría de integridad o una lectura
sensible volverá a comparar bytes y checksum según la política operativa. Una discrepancia bloquea
la entrega, registra un incidente de integridad y nunca se corrige regenerando silenciosamente.

ETag, MD5, checksum multipart, version ID o metadata del proveedor podrán servir como defensas
adicionales, pero nunca sustituirán el SHA-256 propio de Claridez. Un checksum acredita integridad
de bytes; no es una firma electrónica ni demuestra identidad de una persona.

### 4. Dos niveles de confianza

#### Artefactos generados internamente

Un `GeneratedArtifact` requiere:

- procedencia enlazada con snapshot, plantilla, versión emitida, job y entorno de render;
- almacenamiento privado y object key opaca;
- SHA-256 de los bytes exactos;
- escritura única, inmutabilidad y comprobación de integridad;
- autorización antes de toda lectura o descarga;
- historia de intentos y fallos sin alterar el artefacto sellado.

Al provenir del renderer controlado y de entradas cerradas, no atravesará artificialmente el mismo
scanner de malware que un upload externo. Esta excepción no relaja validación estructural,
aislamiento, hash, almacenamiento privado ni trazabilidad.

#### Uploads externos no confiables

Todo upload externo seguirá obligatoriamente:

```text
creado
  → quarantined
  → validating
  → pending_scan
  → clean | infected | rejected | scan_error
```

La validación aplicará una allowlist administrada por servidor, tamaño máximo configurable dentro
de un límite global, nombre seguro, extensión, tipo declarado, magic bytes y parser apropiado. Una
discordancia, estructura inválida o formato no permitido produce `rejected`.

Archivos comprimidos solo se admitirán mediante política explícita y límites de profundidad,
número de entradas, expansión, ratio, tamaño total y tiempo. Cifrado no soportado, bombas de
descompresión, parsers incompletos y contenido anidado no analizable fallarán cerrados.

Solo el estado `clean`, derivado de un intento completo y vigente, habilitará la disponibilidad.
`infected`, `unsupported`, `timeout`, `technical_error`, `skipped`, `incomplete`, fallo del scanner
o ausencia de resultado mantendrán el archivo indisponible. `scan_error` podrá reintentarse de
forma acotada, pero jamás se reinterpretará como limpio.

### 5. Almacenamiento privado detrás de un puerto

1. Los binarios se almacenarán fuera de PostgreSQL mediante un puerto privado propiedad de
   `claridez.documents`. PostgreSQL conservará identidad, tenant, vínculo de dominio, estado,
   tamaño, MIME verificado, checksum, procedencia y metadata mínima.
2. El puerto exigirá buckets o contenedores privados, TLS, cifrado en reposo, claves opacas y únicas
   sin PII, escritura condicional sin sobrescritura, lectura por stream, inspección de metadata y
   soporte verificable de recuperación.
3. La object key no será un identificador público ni se construirá con nombres de personas,
   organizaciones, eventos o archivos. El tenant scope se validará en la metadata autoritativa;
   prefijos o buckets por organización serán defensa adicional, no autorización.
4. El versionado o object lock del proveedor podrá reforzar la conservación, pero no sustituirá la
   inmutabilidad del dominio ni su checksum. Las reglas lifecycle de P9 no podrán destruir
   evidencia contractual ni archivos del dominio.
5. El puerto de dominio no expondrá una operación de destrucción física en P9. La limpieza técnica
   de fragmentos de multipart que nunca llegaron a constituir un archivo deberá distinguirse de la
   disposición de evidencia y quedar limitada al adaptador y a una política operativa aprobada.
6. La selección entre un proveedor S3-compatible, Cloudflare R2, Backblaze B2 u otra alternativa
   se realizará mediante spike de privacidad, costo, portabilidad, límites, versionado, lifecycle,
   recuperación, desarrollo local y salida. Ningún proveedor se adopta por este ADR.

### 6. Coherencia entre PostgreSQL y objetos

El object store no participa en transacciones PostgreSQL. Por ello:

1. Cada operación reservará primero una identidad, object key opaca y estado pendiente dentro de
   PostgreSQL; el job idempotente escribirá el objeto una sola vez, verificará tamaño y SHA-256 y
   solo después lo marcará disponible.
2. Ninguna respuesta expondrá un objeto en estado pendiente, no verificado, en cuarentena o con
   integridad fallida.
3. Una clave de idempotencia y la escritura condicional impedirán duplicar o sobrescribir evidencia
   al reintentar. Si el objeto ya existe, se verificará contra la metadata esperada antes de
   continuar.
4. Un reconciliador acotado detectará metadata pendiente, objeto ausente, objeto inesperado o hash
   divergente y dejará evidencia del resultado. No fabricará filas, no declarará limpio un upload y
   no eliminará silenciosamente evidencia.
5. Backups, versionado y restauración se diseñarán como una unidad operativa PostgreSQL–objetos. Una
   restauración deberá comprobar referencias y hashes; una ausencia quedará marcada e investigable,
   nunca sustituida por una regeneración.

### 7. Autorización y transporte de descarga

La autorización de lectura pertenece siempre a Claridez y se evalúa antes de elegir transporte.
El dominio devolverá una concesión interna de descarga para un archivo exacto, actor o sesión,
propósito y tiempo; el adaptador podrá servir los bytes mediante:

- descarga proxy desde Django para mayor control; o
- URL firmada temporal del proveedor para descargar directamente.

Ambos adaptadores exigirán el mismo contrato. Una URL firmada tendrá vida mínima, método y objeto
exactos, headers de respuesta seguros y no podrá ampliar scope. No expondrá object keys en APIs o
logs más allá de lo técnicamente inevitable para el proveedor. Revocación y cambios de permisos
impedirán emitir nuevas URLs; su corta duración limitará una URL ya emitida. Para acceso externo,
además se validará el grant de ADR 0017.

El servicio aplicará nombres de descarga sanitizados, `Content-Disposition` seguro,
`X-Content-Type-Options: nosniff`, tipo verificado y políticas de caché acordes con contenido
privado. Un hash incorrecto, estado distinto de disponible o análisis externo distinto de `clean`
bloqueará la entrega.

### 8. Malware y evidencia de análisis

El scanner estará detrás de un puerto sustituible. Una implementación podrá usar ClamAV, un
servicio gestionado o una capacidad del proveedor de almacenamiento solo si conserva el contrato
de estado, evidencia y fail-closed de Claridez.

Cada intento de análisis será append-only y registrará, como mínimo:

- archivo, checksum y tamaño exactos analizados;
- motor, versión y versión de firmas cuando exista;
- inicio, fin, timeout y número de intento;
- resultado tipado: `clean`, `infected`, `unsupported`, `timeout`, `technical_error`, `skipped` o
  `incomplete`;
- identificadores de correlación/job y metadata diagnóstica minimizada;
- procedencia de la decisión que cambió el estado del archivo.

Un resultado anterior no cubre bytes diferentes. Reemplazar el objeto exige otra identidad de
archivo y otro análisis. Solo un intento completo `clean` sobre el SHA-256 vigente habilita la
disponibilidad; todos los demás resultados permanecen bloqueados y auditables.

### 9. Primer mecanismo asíncrono

P9 adoptará inicialmente un ledger durable de jobs en PostgreSQL, dentro del monolito modular, sin
Redis ni broker adicional. La elección se justifica porque PostgreSQL ya es una dependencia
operada y permite registrar, en la misma transacción del comando, el trabajo necesario para render,
verificación, reconciliación y malware.

1. El comando autorizado creará el job y su payload mínimo de IDs, tenant, propósito, tipo,
   idempotency key y correlación dentro de la misma transacción que el estado de dominio. No se
   almacenarán binarios, tokens ni PII innecesaria en el payload.
2. Un proceso worker separado del ciclo HTTP, pero desplegado desde el mismo artefacto del
   monolito, reclamará jobs con locks PostgreSQL, lease y recuperación de jobs abandonados. El
   framework o comando concreto queda sujeto a spike; no cambia este protocolo.
3. La semántica será at-least-once. Todo handler deberá ser idempotente, comprobar el estado actual
   y reutilizar la misma identidad/object key; no se prometerá exactly-once.
4. Los retries serán acotados, con clasificación retryable/no retryable, backoff y jitter cuando
   corresponda. Al agotar intentos, el job pasará a fallo terminal o dead-letter investigable sin
   presentar salida parcial como éxito.
5. Cuando el orden sea necesario, se serializará por agregado o clave de recurso. La concurrencia
   entre jobs distintos seguirá permitida y los locks tendrán orden documentado.
6. Cada intento registrará timestamps, worker/version, correlación, causa tipada, duración y
   resultado. Logs y métricas operativas se mantendrán separados de la evidencia de negocio.
7. El worker ejecutará únicamente jobs tipados creados por comandos autorizados. Entrará por una
   frontera tenant-aware de infraestructura específica para background jobs, inaccesible a vistas
   y dominio ordinario, y no establecerá libremente el GUC. RLS, claves tenant-aware y privilegios
   mínimos continuarán activos.
8. Reinicio, caída después de escribir el objeto, timeout del scanner y caída antes de confirmar el
   resultado deberán ser recuperables sin duplicar emisiones, artefactos ni evidencia.

Esta decisión satisface el caso real exigido por ADR 0004. Adoptar después un broker, Redis, Celery,
Dramatiq o un servicio gestionado requerirá demostrar necesidad operativa y compatibilidad con el
protocolo; si cambia la decisión central, deberá reemplazar este ADR.

### 10. Aislamiento y privilegios

1. Metadata de artefactos, archivos, jobs e intentos será privada, incluirá `organization_id`, FK y
   unicidades tenant-aware y tendrá RLS simétrica con `ENABLE` y `FORCE ROW LEVEL SECURITY`.
2. Credenciales del object store, scanner y renderer serán específicas por entorno, de privilegio
   mínimo y no se almacenarán en la base, logs, jobs ni repositorio.
3. Pruebas negativas con dos organizaciones cubrirán metadata, object keys, jobs, descargas proxy,
   URLs firmadas, reintentos y restauración. Conocer UUID, checksum u object key ajenos no otorgará
   acceso.
4. El adaptador local conservará privacidad y el mismo contrato observable. No usará rutas
   públicamente servidas ni permitirá que una prueba exitosa con filesystem local se presente como
   validación de un proveedor productivo.

## Aspectos provisionales

- Los nombres físicos de artefactos, archivos, jobs, intentos y estados podrán ajustarse durante la
  implementación si conservan las máquinas y responsabilidades definidas.
- El framework concreto que ejecute el worker queda abierto; el ledger PostgreSQL, la transacción
  de alta, la semántica at-least-once y el protocolo de recuperación no son provisionales.
- Proxy y URL firmada son adaptadores permitidos. La política podrá elegir uno por tipo/tamaño de
  archivo sin trasladar autorización al proveedor.

## Asuntos diferidos

- Proveedor productivo de almacenamiento y topología de buckets o contenedores.
- Motor PDF y versión concretos, imagen canónica y estrategia de despliegue resultantes del spike.
- Scanner concreto: ClamAV, servicio gestionado o capacidad compatible del proveedor.
- Framework/comando de worker, frecuencia, concurrencia y dimensionamiento operativo.
- Allowlist inicial, límites máximos y admisión de formatos comprimidos.
- Política de verificación periódica de integridad y objetivos específicos de backup/restore del
  object store.
- Cualquier disposición física de archivos o evidencia, conforme a ADR 0017.

Estos detalles deberán cerrarse antes de implementar u operar su adaptador correspondiente. Podrán
cambiar detrás de los puertos sin modificar el dominio mientras preserven el contrato aceptado.

## Validación pendiente

Antes de implementar cada adaptador deberán realizarse spikes comparables de:

- HTML/CSS a PDF, navegador headless y motor dedicado, incluyendo fidelidad, seguridad,
  dependencias, fuentes, imágenes, rendimiento, reproducibilidad, licencia y despliegue;
- S3-compatible, R2, B2 u otra alternativa, incluyendo privacidad, costo, portabilidad, versionado,
  lifecycle, backup, restauración, desarrollo local y salida;
- ClamAV, servicio gestionado y capacidad de proveedor, incluyendo tipos, límites, timeout,
  firmas, disponibilidad, costos y manejo de comprimidos;
- worker PostgreSQL bajo retries, concurrencia, abandono, recuperación y apagado ordenado.

La implementación completa deberá probar:

- render únicamente en el entorno canónico y conservación de los bytes emitidos;
- checksums separados y detección de sustitución/corrupción;
- escritura única, reconciliación y restore coherente PostgreSQL–objetos;
- cuarentena, validación MIME/parser, malware y bloqueo de todo resultado distinto de `clean`;
- autorización y aislamiento con proxy y/o URLs firmadas temporales;
- idempotencia, retries, backoff, fallo terminal, correlación y recuperación del worker;
- migración desde cero y desde P8 final, OpenAPI y gates generales aplicables.

## Alternativas consideradas

- **Binarios en PostgreSQL:** rechazada por costo de base, backups y serving, sin una justificación
  extraordinaria para P9.
- **Regenerar el PDF cuando se necesite:** rechazada porque renderer, fuentes o assets pueden cambiar
  y no reconstruir los bytes aceptados.
- **Igualdad byte a byte entre Windows y Linux:** rechazada como invariante; la autoridad es el
  entorno canónico versionado y el artefacto conservado.
- **Escanear de igual forma todo PDF interno:** rechazada porque confunde procedencia controlada con
  contenido externo. El renderer interno conserva defensas propias.
- **Presentar uploads antes del scan:** rechazada; pendiente, error, timeout o análisis omitido no
  significan seguro.
- **Usar ETag/MD5 como checksum:** rechazada porque sus semánticas dependen del proveedor y del modo
  de carga.
- **Autorizar en el object store:** rechazada; signed URLs transportan una decisión ya tomada por
  Claridez.
- **Trabajo pesado dentro de HTTP:** rechazado por timeout, reintentos ambiguos y recursos no
  acotados.
- **Broker/Redis desde el inicio de P9:** no seleccionado porque PostgreSQL cubre el volumen inicial
  sin otra dependencia operativa. Se reevaluará con métricas reales.

## Consecuencias

- La emisión definitiva requerirá operar una imagen canónica y un worker además de Django, React y
  PostgreSQL. Desarrollo nativo en Windows podrá preparar o solicitar trabajos, pero no producir
  emisiones definitivas fuera de esa imagen.
- PostgreSQL gana tablas de jobs y metadata, pero no almacena binarios. El object store añade una
  frontera no transaccional que exige estados pendientes, idempotencia y reconciliación.
- Los uploads externos tendrán latencia antes de estar disponibles. Ese costo es deliberado para no
  presentar contenido no analizado como seguro.
- Cambiar almacenamiento, scanner, transporte de descarga o framework del worker será posible
  detrás de puertos, siempre que preserve checksums, evidencia, estados y autorización.
- La ausencia de destrucción física y lifecycle destructivo para evidencia incrementará consumo
  hasta que una etapa posterior apruebe disposición.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [ADR 0003 — Fundamentos multiempresa](0003-multitenancy-foundations.md)
- [ADR 0004 — Diferir infraestructura asíncrona](0004-defer-asynchronous-infrastructure.md)
- [ADR 0005 — Observabilidad incremental](0005-incremental-observability.md)
- [ADR 0006 — Toolchains reproducibles](0006-reproducible-toolchains.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0010 — Identidad local y sesiones](0010-local-identity-and-server-sessions.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0017 — Dominio contractual y evidencia documental](0017-contractual-domain-and-documentary-evidence.md)

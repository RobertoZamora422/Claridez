# ADR 0017 — Dominio contractual y evidencia documental

- **Estado:** Aceptado
- **Fecha:** 2026-08-12
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

P9 debe permitir emitir, presentar, aceptar y conservar instrumentos contractuales vinculados con
la historia de una reserva. La solución debe preservar la cotización aceptada, la cadena de
reprogramaciones de P8 y la evidencia exacta observada por la contraparte, sin convertir un PDF,
una aceptación o una reserva individual en toda la relación contractual.

El Blueprint asigna plantillas, contratos, documentos y archivos a un único dominio conceptual.
Separarlo ahora en `claridez.contracts` y `claridez.documents` duplicaría autoridad sobre emisiones,
artefactos y evidencia. A la vez, un modelo llamado `Contract` que represente simultáneamente la
relación contractual, una versión, el PDF y la aceptación impediría mantener identidades e historia
independientes.

P9 necesita acceso externo acotado, pero no un portal de cliente completo. También necesita
registrar retención y legal hold sin inventar plazos jurídicos ni abrir una vía de destrucción
física. La aceptación propia de Claridez conservará evidencia técnica y contractual; no se
presentará como firma electrónica acreditada ni como conclusión jurídica.

## Decisiones aceptadas

### 1. Propiedad modular y dependencias

1. `claridez.documents` será la única autoridad del dominio documental de P9. No se creará
   `claridez.contracts` como módulo independiente.
2. El módulo mantendrá límites internos explícitos entre:
   - plantillas y versiones;
   - expedientes contractuales;
   - instrumentos contractuales;
   - versiones emitidas;
   - aceptación y evidencia;
   - acceso externo;
   - retención.
3. La generación, los artefactos, los uploads y el almacenamiento pertenecen a la misma autoridad
   documental, con la plataforma técnica definida por ADR 0018. Un adaptador de almacenamiento no
   adquiere autoridad sobre el significado contractual de los bytes.
4. Toda integración entre módulos usará puertos públicos estrechos y DTO o proyecciones inmutables.
   Está prohibido compartir modelos ORM mutables, managers, `QuerySet`, iteradores lazy o accesos
   dispersos a tablas ajenas.
5. `documents.public` podrá exponer proyecciones mínimas a módulos futuros. P9 no definirá
   documentos financieros, permisos financieros, pagos, saldos, devoluciones ni consecuencias
   económicas de cancelaciones.

### 2. Agregados e identidades separadas

Se formalizan los siguientes conceptos, cuyos nombres físicos podrán ajustarse sin mezclar sus
responsabilidades:

1. **Expediente contractual (`ContractualRecord`).** Representa la relación documental y
   contractual asociada con una raíz de reserva. Existirá como máximo uno por
   `(organization_id, root_reservation_id)`. Se crea solo por una acción documental explícita y
   puede contener varios instrumentos a lo largo de la vida de la raíz.
2. **Instrumento contractual (`ContractualInstrument`).** Es la identidad lógica de un documento
   jurídico tipado dentro del expediente. Cuando exista política aprobada, sus tipos podrán incluir
   contrato principal, adenda, terminación, anexo u otro instrumento expresamente definido.
3. **Versión emitida del instrumento (`IssuedInstrumentVersion`).** Es una emisión concreta,
   inmutable y ordenada de un instrumento. Una nueva versión de un contrato no constituye por sí
   misma otro tipo de instrumento.
4. **Artefacto generado (`GeneratedArtifact`).** Son los bytes exactos producidos para una versión
   emitida, junto con su procedencia, metadata de render y SHA-256. Su almacenamiento e integridad
   se rigen además por ADR 0018.
5. **Aceptación (`AcceptanceEvidence`).** Es evidencia append-only de una manifestación vinculada a
   una versión emitida, un artefacto exacto y el SHA-256 exacto de ese artefacto.
6. **Acceso externo (`ExternalAccessGrant` y `AcceptanceChallenge`).** El grant concede únicamente
   un propósito y scope acotados; el challenge separado autoriza un único intento de aceptación
   dentro de ese scope.
7. **Retención.** La clasificación, la referencia a política, el legal hold, su liberación, la
   elegibilidad para disposición y sus eventos son hechos distintos de la eliminación física.

No se automatiza qué cambio jurídico produce una nueva versión, una adenda, una terminación, un
anexo, un contrato nuevo u otro instrumento. Esa decisión requiere una política explícita de
materialidad y tratamiento jurídico.

### 3. Plantillas y lenguaje de variables

1. Una `DocumentTemplate` es una identidad lógica privada de una organización. Sus
   `DocumentTemplateVersion` son append-only y quedan inmutables al publicarse.
2. Los estados mínimos serán `draft`, `published` y `retired`. Solo una versión publicada y activa
   podrá originar una emisión definitiva. Retirar una versión no altera emisiones previas.
3. Las variables pertenecerán a un catálogo cerrado y versionado. Cada variable declarará tipo,
   formato, obligatoriedad y puerto autoritativo de procedencia. No habrá evaluación arbitraria de
   código, expresiones libres, imports, navegación de atributos ni acceso a ORM.
4. El sistema validará de forma fail-closed la sintaxis, la versión del catálogo, las variables
   usadas y sus valores. Una variable obligatoria ausente, desconocida o inválida impedirá la
   emisión; no se sustituirá silenciosamente por vacío.
5. Texto, HTML, URLs y demás contextos se escaparán y sanitizarán según su destino. Las plantillas
   no podrán desactivar esas defensas.
6. El preview será no contractual, quedará marcado como tal y no creará una versión emitida,
   artefacto contractual ni aceptación. La emisión definitiva usará exclusivamente datos
   congelados y el entorno canónico de ADR 0018.

### 4. Autoridades externas y snapshot contractual

`claridez.documents` consumirá únicamente estas autoridades:

- `claridez.commercial`: `QuotationVersion` aceptada, sus líneas y la evidencia comercial de
  aceptación;
- `claridez.scheduling`: raíz, reserva vigente, cadena, sede, espacio, intervalos,
  reprogramaciones, cancelaciones y `ScheduleEvent`;
- `claridez.people`: identidad canónica y proyección aprobada de la contraparte;
- `claridez.organizations`: identidad contractual de la organización, sedes, espacios,
  configuración, membresías y zona horaria;
- `claridez.operations`: preparación operativa y su relación existente con la reserva, sin
  convertirse en fuente contractual.

Servicios, cantidades, precios, descuentos, moneda, totales y condiciones comerciales provendrán
exclusivamente de la `QuotationVersion` aceptada y sus líneas inmutables. Nunca se reconstruirán ni
recalcularán desde el catálogo vigente.

Cada versión emitida congelará un snapshot contractual canónico y versionado que incluya, como
mínimo:

- identificadores y versiones de las proyecciones fuente;
- organización y contraparte;
- cotización y líneas aceptadas;
- raíz y reserva vigente al emitir;
- sede, espacio, fecha, hora, intervalos y zona cuando sean contractualmente relevantes;
- plantilla y versión;
- catálogo/version del lenguaje y variables resueltas;
- procedencia, timestamps técnicos y versión del esquema del snapshot.

El snapshot se serializará mediante un esquema canónico que produzca bytes UTF-8 deterministas y
tendrá su propio SHA-256. Ese hash expresa identidad verificable del snapshot; no es el SHA-256 del
PDF ni una firma electrónica.

### 5. Reprogramación, cancelación y materialidad

1. P9 consume la raíz, la reserva vigente y los eventos canónicos de scheduling sin modificar
   estados, transiciones, cadenas, locks, guardianes ni historia de P8.
2. Una emisión registra tanto la raíz como la reserva que estaba vigente al emitir. La sucesión de
   reservas no reescribe el snapshot ni el instrumento emitido.
3. Una diferencia de bytes del PDF no constituye por sí misma un cambio contractual. Una política
   explícita de materialidad decidirá si un cambio requiere nueva emisión y, separadamente, nueva
   aceptación.
4. Ninguna aceptación se trasladará a otra versión emitida, otro artefacto ni otros bytes. Si se
   produce otro artefacto, este comienza sin aceptación aunque represente el mismo snapshot.
5. Una cancelación preserva el expediente, los instrumentos, las versiones, los artefactos y la
   aceptación. P9 no deduce por sí mismo si debe emitirse terminación, adenda u otro instrumento.

### 6. Aceptación y evidencia

La aceptación propia de Claridez es un mecanismo de manifestación y conservación de evidencia. No
se denominará ni presentará como firma electrónica acreditada, avanzada o certificada. Su
suficiencia para un caso de uso concreto y los textos legales requieren política aprobada y revisión
jurídica ecuatoriana.

Una aceptación exitosa será append-only y quedará vinculada permanentemente a:

- expediente, instrumento y versión emitida exactos;
- artefacto exacto y SHA-256 exacto del PDF;
- texto de manifestación presentado y su versión;
- identidad o proyección aprobada de la contraparte y, cuando corresponda, representación
  declarada;
- grant y challenge utilizados;
- método y resultado de autenticación o atribución;
- instante de presentación, instante de recepción del servidor y zona aplicable;
- IP y user-agent minimizados conforme a política;
- identificadores de correlación y solicitud;
- versión del mecanismo de aceptación y demás evidencia expresamente aprobada.

El servicio comprobará de nuevo, dentro de una única transacción, vigencia y scope del grant,
challenge no consumido, artefacto/hash presentados y ausencia de replay antes de registrar la
aceptación y consumir el challenge. Reintentar el mismo comando no podrá crear evidencia duplicada.
No existirá capability, endpoint ni servicio interno que permita aceptar en nombre de la
contraparte.

### 7. Acceso externo acotado

1. P9 ofrecerá enlaces externos seguros de lectura, descarga y, cuando se apruebe el mecanismo,
   aceptación. No creará cuentas públicas ni un portal de cliente completo.
2. Cada grant tendrá token opaco CSPRNG de al menos 256 bits, propósito, scope exacto, destinatario
   o contexto de atribución, expiración, estado y revocación. Solo se almacenará un HMAC o hash
   resistente del token, con versión del mecanismo; nunca el token recuperable.
3. Los identificadores públicos no serán enumerables y las respuestas no revelarán existencia de
   recursos fuera del scope.
4. Un grant de lectura podrá reutilizarse solo dentro de su propósito, scope, expiración y estado.
   El challenge de aceptación será distinto, de vida corta y single-use; su consumo será
   transaccional y protegido contra replay.
5. La validación del grant podrá crear una sesión externa corta, `Secure`, `HttpOnly`, restringida
   al mismo propósito y sin acceso al workspace. Cada operación sensible volverá a comprobar el
   grant asociado; revocarlo o expirarlo bloqueará también una sesión externa ya creada.

### 8. Autorización interna conjuntiva

Las capabilities documentales constituyen autoridad propia. Una capability o relación de
`commercial`, `scheduling`, `operations` u otro módulo nunca concede por sí sola acceso documental
ni sustituye la capability documental requerida.

Cuando corresponda, una operación interna exigirá conjuntamente:

```text
sesión válida
+ CSRF para toda escritura HTTP
+ organización y membresía activas
+ authorized_tenant_scope
+ capability documental requerida
+ capability del dominio fuente realmente aplicable
+ relación de dominio existente
+ propósito permitido
```

La relación de dominio solo reduce el conjunto alcanzable por una capability documental ya
concedida. `sales:read` no sustituye `contractual_record:read`; `sales:manage` no sustituye
`contractual_instrument:issue`; `EventPreparation → Reservation` no concede acceso por sí misma.
P9 no creará modelos artificiales de asignación comercial, operativa o financiera.

La matriz inicial será:

| Capability | `propietario` | `administrador` | `comercial` | `operaciones` | `finanzas` |
| --- | :---: | :---: | :---: | :---: | :---: |
| `document_template:read` | Sí | Sí | Sí | No | No |
| `document_template:manage` | Sí | Sí | No | No | No |
| `contractual_record:read` | Sí | Sí | Sí | Sí, con propósito operativo y relación existente | No |
| `contractual_instrument:issue` | Sí | Sí | Sí | No | No |
| `contractual_acceptance:read` | Sí | Sí | Sí | No | No |
| `contractual_artifact:download` | Sí | Sí | Sí | Sí, con propósito operativo y relación existente | No |
| `document_external_access:manage` | Sí | Sí | Sí | No | No |
| `document_file:manage` | Sí | Sí | Sí | No | No |
| `document_retention:manage` | Sí | Sí | No | No | No |

Para Operaciones, `contractual_record:read` y `contractual_artifact:download` exigirán además
`operation:read`, una relación real `EventPreparation → Reservation` dentro de la misma raíz y un
propósito operativo permitido. Esa relación limita alcance; no concede la capability documental.
Finanzas permanece deny-by-default para todo P9 hasta que P10 o una etapa posterior apruebe su
propia semántica. No existe capability interna de aceptación ni capability de destrucción.

### 9. Aislamiento, historia y retención

1. Toda tabla privada de P9 incluirá `organization_id`, relaciones y unicidades tenant-aware, RLS
   simétrica con `ENABLE` y `FORCE ROW LEVEL SECURITY`, y privilegios mínimos. No habrá UUID global
   implícito ni evaluación lazy fuera de `authorized_tenant_scope`.
2. Versiones de plantilla publicadas, snapshots, versiones emitidas, artefactos, aceptaciones,
   consumos de challenges y eventos de retención serán inmutables o append-only. Cada hecho tendrá
   una autoridad canónica; no se duplicarán bitácoras que puedan divergir.
3. P9 podrá modelar clasificación de retención, referencia y versión de política, legal hold,
   liberación autorizada, elegibilidad para disposición y eventos append-only con actor, razón,
   tiempo y procedencia.
4. P9 no incorporará capability, endpoint, acción frontend, job ni servicio de destrucción física
   para contratos, instrumentos, versiones, aceptaciones, evidencia o archivos del dominio. La
   disposición física queda diferida hasta aprobar política jurídica, plazos y control reforzado;
   no se condiciona a una futura implementación de MFA.
5. P9 no abrirá una vía lateral para anonimizar o eliminar evidencia histórica de P7. Un legal hold
   prevalecerá sobre cualquier elegibilidad calculada, pero liberarlo no ejecutará disposición.

### 10. Migración y compatibilidad

1. Las migraciones se probarán desde cero y desde el esquema final de P8, sin modificar estados,
   constraints, historia ni invariantes de P8.
2. No habrá backfill que fabrique expedientes, instrumentos, versiones, contratos, aceptaciones,
   firmas, artefactos o archivos. El expediente se crea bajo demanda por un comando documental
   autorizado.
3. Una reserva histórica sin actividad documental se representará honestamente como
   `sin contrato emitido`.
4. La implementación deberá conservar puertos públicos, claves tenant-aware, RLS, privilegios
   mínimos, orden de migración y recuperación. P9 no ejecuta ni presume el cutover de un entorno
   destino de etapas anteriores.
5. P9 no modificará cotizaciones aceptadas ni anticipará entidades, estados, cálculos o permisos de
   P10 y etapas posteriores.

## Aspectos provisionales

- Los nombres físicos propuestos para los agregados podrán ajustarse durante la implementación si
  conservan exactamente sus identidades, cardinalidades y responsabilidades.
- El catálogo inicial de tipos de instrumento será cerrado y mínimo. La existencia de un valor
  técnico no decidirá cuándo corresponde jurídicamente utilizarlo.
- El catálogo inicial de variables y sus DTO fuente se cerrará con los datos legales aprobados
  antes de habilitar la emisión correspondiente.

## Asuntos diferidos

- Datos legales obligatorios de la organización y de la contraparte.
- Método inicial de aceptación, representación de quien acepta, texto de manifestación y política
  de atribución.
- Política de materialidad ante reprogramaciones, cancelaciones u otros cambios, incluida la
  decisión entre nueva versión, adenda, terminación u otro instrumento.
- Política jurídica de retención, plazos, disposición y controles reforzados para una futura
  destrucción física.
- Firma electrónica acreditada, avanzada o certificada y cualquier proveedor asociado.
- Portal de cliente completo, identidad pública persistente y funcionalidades de P10 en adelante.

Estos asuntos bloquean únicamente la superficie que dependa de ellos. No impiden construir, tras
autorización expresa, la arquitectura base con políticas y puertos fail-closed.

## Validación pendiente

La implementación de P9 deberá demostrar:

- cardinalidad de expediente por raíz, múltiples instrumentos y versiones inmutables;
- snapshots canónicos y separación entre hash semántico y artefacto;
- plantillas fail-closed, preview no contractual y puertos sin ORM;
- autorización conjuntiva, matriz completa, CSRF y pruebas negativas con dos organizaciones;
- grants, challenges, expiración, revocación, consumo transaccional y replay;
- aceptación ligada al artefacto exacto sin transferencia entre bytes;
- migraciones desde cero y desde P8 final sin backfill inventado;
- ausencia ejecutable de cualquier superficie de destrucción física y de semántica P10.

## Alternativas consideradas

- **`claridez.contracts` y `claridez.documents` separados:** rechazada porque dividiría autoridad
  sobre emisión, artefactos, aceptación y retención.
- **Un `Contract` único por raíz:** rechazada porque no puede representar varios instrumentos y
  confunde la relación contractual con su documento principal.
- **Usar “versión contractual” como tipo de instrumento:** rechazado; identidad lógica, tipo y
  emisión versionada son ejes distintos.
- **Vincular todo solo con la reserva vigente:** rechazado porque perdería la estabilidad del
  expediente al reprogramar. Vincular solo con la raíz también sería insuficiente para saber qué
  reserva estaba vigente al emitir; se conservan ambas referencias en su nivel correspondiente.
- **Recalcular desde catálogo o datos vivos:** rechazado porque reescribiría el significado de la
  cotización aceptada.
- **Transferir aceptación si el snapshot no cambia:** rechazado porque la contraparte aceptó bytes
  concretos, no una regeneración futura.
- **Portal público completo en P9:** rechazado por ampliar identidad y superficie sin necesidad para
  lectura y aceptación acotadas.
- **Eliminar físicamente cuando venza una política provisional:** rechazado hasta contar con
  política jurídica y control reforzado aprobados.

## Consecuencias

- La raíz de reserva obtiene un expediente estable sin limitar la evolución a un único contrato.
- La separación entre snapshot, instrumento, emisión, artefacto y aceptación aumenta el número de
  identidades, pero evita transferir evidencia o reescribir historia.
- Reprogramar o cancelar no decide por sí solo una consecuencia jurídica; la política de
  materialidad será explícita y auditable.
- Operaciones solo podrá leer documentos cuando reúna capability documental, capability operativa,
  relación existente y propósito permitido. Finanzas no obtiene acceso por inferencia.
- La ausencia de destrucción física puede incrementar almacenamiento hasta aprobar la política
  posterior, pero evita una capacidad irreversible sin base ni controles cerrados.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [Especificación aprobada de 5.1](../product/ITERATION_5_1_COMMERCIAL_FLOW.md)
- [Especificación aprobada de 5.2](../product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md)
- [Especificación aprobada de P8](../product/P8_SCHEDULING_AND_ADVANCED_RESERVATIONS_SPECIFICATION.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0010 — Identidad local y sesiones](0010-local-identity-and-server-sessions.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0012 — Integridad comercial](0012-commercial-scheduling-and-monetary-integrity.md)
- [ADR 0013 — Coordinación comercial-operaciones](0013-commercial-operations-coordination-and-integrity.md)
- [ADR 0014 — Multi-espacio y catálogo](0014-multi-space-business-configuration-and-catalog-boundaries.md)
- [ADR 0015 — Límites de people/CRM](0015-people-crm-boundaries-and-commercial-authority.md)
- [ADR 0016 — Propiedad de scheduling](0016-scheduling-ownership-and-temporal-integrity.md)
- [ADR 0018 — Plataforma de archivos y procesamiento documental](0018-file-platform-and-document-processing.md)

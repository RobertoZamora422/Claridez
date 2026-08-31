# ADR 0023 — Experiencia externa, comunicaciones y portal P14

- **Estado:** Aceptado
- **Fecha:** 2026-08-31
- **Reemplaza a:** No aplica; refina ADR 0004, ADR 0009, ADR 0015, ADR 0017 y ADR 0018
  únicamente en los puntos expresamente indicados, sin sustituir sus autoridades
- **Reemplazado por:** No aplica

## Contexto

El Blueprint define un único límite funcional P14 —Formularios, comunicaciones y portal— para
captar consultas, entregar mensajes transaccionales y ofrecer al cliente una superficie externa
segura. El producto ya posee autoridades separadas para persona y consentimiento, oportunidad,
agenda, documentos y aceptación, cuentas por cobrar y operación. P14 debe componerlas sin crear una
segunda persona, oportunidad, agenda, autoridad documental, saldo o workspace para clientes.

P9 introdujo el primer worker asíncrono real mediante `DocumentJob`: un ledger PostgreSQL
exclusivamente documental con claim concurrente, lease, ejecución at-least-once, idempotencia,
retries y fallo terminal. No implementó el outbox transaccional de comunicaciones diferido por ADR 0004. P14 constituye el primer caso transversal que debe registrar una intención de comunicación
en la misma transacción que el hecho de dominio y entregarla después mediante proveedores
externos.

P9 también implementó acceso externo documental con `ExternalAccessGrant`,
`ExternalDocumentSession`, `AcceptanceChallenge`, `ExternalTokenLocator`, rate limiting y evidencia
de aceptación vinculados a versiones y artefactos documentales exactos. Esas estructuras no son una
identidad externa general ni una sesión de portal y deben permanecer bajo autoridad exclusiva de
Documents.

El propietario aprobó el plan consolidado P14 y cerró cuatro precisiones adicionales: el tenant de
una captación anónima se resolverá en servidor antes de RLS; identidad externa y grants por evento
serán conceptos distintos; las preferencias se fusionarán de forma conservadora sin reinterpretar
consentimiento; e Identity conservará fuera de Communications la entrega de sus mensajes globales.
Este ADR formaliza únicamente la arquitectura previa. Su aceptación no autoriza todavía la
implementación P14.

## Decisiones aceptadas

### 1. Un dominio funcional y dos módulos técnicos

1. El límite funcional P14 se implementará mediante exactamente dos módulos técnicos:

   - `claridez.communications`, autoridad de plantillas y versiones de mensajes, preferencias y
     supresiones, intenciones, mensajes lógicos, outbox, programación técnica, intentos, resultados
     y eventos de proveedor;
   - `claridez.portal`, autoridad de formularios públicos, locators propios, recibos técnicos de
     captación, `PortalPrincipal`, challenges de autenticación, sesiones, grants y scopes externos.

2. Esta separación no crea dos módulos funcionales de producto ni autoriza un tercer módulo P14.
   Los coordinadores de aplicación no son autoridades de datos y solo invocan puertos públicos.
3. La flecha del siguiente grafo significa que el consumidor depende del proveedor:

   ```text
   coordinadores de aplicación ─▶ portal / communications / dominios propietarios

   portal ─▶ organizations
      ├────▶ people
      ├────▶ commercial
      ├────▶ scheduling
      ├────▶ documents
      ├────▶ receivables
      ├────▶ operations, solo proyección cliente expresamente aprobada
      └────▶ communications

   communications ─▶ organizations
             ├──────▶ people
             └──────▶ crm, solo interacción semántica aprobada

   crm ─▶ people / commercial
   ```

4. Los dominios propietarios no importarán Communications para preservar el grafo. Un coordinador
   transaccional solicitará el hecho propietario y la intención de comunicación mediante sus
   respectivos puertos. Communications no importará Portal, Commercial, Scheduling, Documents,
   Receivables u Operations.
5. Ningún módulo importará modelos, managers, servicios internos o migraciones de otro para
   consultar o escribir su estado. Una FK física tenant-aware no concede autoridad y no sustituye
   el puerto público.

### 2. Autoridades exactas de Portal

1. `PortalPrincipal` representa una identidad externa dentro de una organización. No es
   `identity.User`, no es `Membership`, no concede capacidades internas y no pertenece al
   workspace.
2. La sesión autentica exactamente un `PortalPrincipal`. Autenticar un principal no autoriza por
   sí mismo ningún `EventRequest`, documento, reserva, obligación o acción.
3. Un grant de Portal autoriza un conjunto cerrado de scopes sobre el ancla estable:

   ```text
   organization + canonical_person + event_request
   ```

   El grant pertenece además a un principal concreto, conserva procedencia, creación, revocación y
   auditoría, y no puede cruzar organización.

4. Una misma identidad externa puede tener varios grants independientes para distintos
   `EventRequest`. No existe acceso implícito a todas las solicitudes de la persona.
5. Antes de confirmar una reserva, el grant puede autorizar la proyección comercial y documental
   asociada al `EventRequest`. No se fabricará agenda.
6. Después de confirmar, Portal podrá incorporar al grant una relación opcional con la raíz y la
   reserva vigentes obtenidas desde `scheduling.public`. La raíz no reemplaza el ancla del grant.
7. Una reprogramación conserva el grant y resuelve la reserva vigente de la misma raíz. Una
   cancelación conserva la historia autorizada y aplica la política de acciones disponibles sin
   borrar ni reescribir el grant.
8. Los scopes serán explícitos y deny-by-default. Como máximo podrán cubrir resumen del evento,
   agenda cliente, lectura/descarga/aceptación documental, consulta de receivables y administración
   de preferencias propias. Un scope desconocido o ausente se deniega.
9. Challenges, sesiones y grants son estado privado tenant-aware de Portal. Sus tokens son opacos;
   el secreto no se almacena en claro y su uso, expiración, rotación y revocación quedan auditados.

### 3. Resolución pública de organización antes de RLS

1. Ningún `organization_id`, `form_id`, header, parámetro o claim aportado sin protección por un
   cliente anónimo constituye autoridad para elegir tenant.
2. Portal poseerá un locator externo global y estrictamente técnico. La ruta pública contendrá un
   valor opaco de alta entropía; la base conservará solo su HMAC y la referencia mínima a
   organización y formulario. El locator no contendrá título, esquema, contactos, campaña,
   contenido, estado funcional ni otro dato privado del formulario.
3. La resolución seguirá obligatoriamente esta secuencia:

   ```text
   request anónimo
     -> HMAC y búsqueda exacta del locator técnico de Portal
     -> organizations.public confirma Organization activa
     -> se crea una autorización externa restringida y server-side
     -> transacción exterior + scope de esa organización
     -> se consulta el formulario privado y publicado
     -> se valida y ejecuta la captación dentro del mismo scope
   ```

4. Se añadirá en infraestructura organizacional un scope externo estrecho —nombre físico
   provisional— que solo acepte una autorización server-side producida por un locator válido. No
   aceptará un UUID crudo, no validará Membership y no expondrá el helper del GUC a vistas,
   serializers o dominios.
5. Ese scope refina ADR 0009 únicamente para entradas externas aprobadas. Mantendrá transacción
   exterior, GUC local, anidación solo para el mismo tenant, materialización dentro del scope y RLS
   fail-closed. No sustituye `authorized_tenant_scope` para actores internos.
6. La organización y el formulario se revalidarán después de entrar al scope. Un locator revocado,
   organización suspendida, formulario no publicado o relación divergente responderán de forma
   opaca y equivalente.
7. Portal podrá usar el mismo patrón, con kinds separados, para localizar challenges y sesiones
   antes de RLS. Los índices globales conservarán únicamente HMAC, tenant, kind y referencia
   técnica necesaria; el estado funcional permanecerá en tablas privadas de Portal.
8. Se aplicarán respuestas anti-enumeración, límites por locator/IP hash/contacto hash, tamaño
   máximo, validación de origen y challenge adaptable. Las pruebas incluirán locators alterados,
   revocados y cruzados entre dos tenants.

### 4. Captación y coordinador transaccional

1. El flujo normal será exactamente:

   ```text
   captación P14
     -> people resolve/create
     -> people registra consentimiento/evidencia
     -> commercial crea EventRequest
     -> communications crea intent + outbox
   ```

2. Un coordinador de aplicación perteneciente a la capa de aplicación de Portal abrirá una única
   transacción PostgreSQL dentro del scope ya resuelto. No tendrá tablas propias de negocio ni será
   un tercer módulo.
3. Los puertos mínimos nuevos serán:

   - `organizations.public`: confirmar organización activa para una entrada externa y enumerar
     organizaciones activas para el worker de Communications;
   - `people.public`: resolver/crear persona para captación, registrar `ConsentEvent` con
     procedencia pública, proyectar conjunto canónico y contacto actual autorizado para challenge
     y resolver consentimiento efectivo para Communications;
   - `commercial.public`: crear `EventRequest` desde captación y proyectar identidad/estado cliente
     de una solicitud;
   - `communications.public`: solicitar, cancelar o sustituir una intención, consultar resultado
     minimizado y administrar preferencias propias;
   - `portal.public`: valores inmutables estrictamente necesarios para coordinadores externos, sin
     ORM;
   - `documents.public`: listar, leer, descargar y aceptar mediante una autorización Portal
     minimizada que Documents vuelve a validar;
   - `scheduling.public`: proyectar agenda cliente por `EventRequest` y resolver la raíz/reserva
     vigente cuando exista;
   - `receivables.public`: proyectar saldo, próxima obligación, historial y recibos cliente por
     `EventRequest`;
   - `crm.public`: registrar de forma idempotente una interacción semántica aprobada sin estado
     técnico;
   - `operations.public`: únicamente una proyección cliente de alto nivel si una decisión de
     producto posterior la autoriza; hasta entonces no expone datos P13.

4. People ejecutará normalización, aliases, locks, deduplicación y canonicalización. Si teléfono y
   correo resuelven personas incompatibles, la operación fallará cerradamente y no creará otra
   persona, lead u oportunidad.
5. Commercial seguirá siendo la única autoridad de `EventRequest`; el formulario no crea una
   entidad `Lead` u `Opportunity` paralela.
6. Communications creará su propia intención y fila de outbox por medio de su puerto dentro de la
   misma transacción. People, Commercial, Portal y el coordinador tienen prohibido escribir tablas
   privadas de Communications.
7. El proveedor nunca será llamado dentro de esta transacción. Una indisponibilidad externa no
   deshace el hecho de negocio ya comprometido; la entrega queda durablemente pendiente.
8. El recibo de captación de Portal será técnico e idempotente: organización, formulario, clave,
   hash canónico, atribución minimizada y resultado. No copiará persona ni `EventRequest`.

### 5. Identidad externa y prueba de control del contacto

1. People conserva teléfono/email canónicos, aliases, fusión y revisiones. P14 no añadirá a People
   un estado de contacto verificado ni reinterpretará sus datos históricos.
2. Portal demostrará control mediante challenge, OTP o magic link enviado al contacto actual
   proyectado por `people.public`. El challenge quedará ligado a organización, principal o intento
   de enrolamiento, persona canónica, kind de contacto, fingerprint/HMAC del valor y revisión de
   People.
3. Al consumir un challenge, Portal volverá a resolver el conjunto canónico y el contacto actual.
   Un cambio de valor, revisión, organización o persona invalidará el challenge sin revelar la
   causa.
4. Una sesión server-side conservará principal, revisión/fingerprint de autenticación, creación,
   última actividad, expiración idle, expiración absoluta, rotación y revocación. Toda operación
   protegida revalidará sesión, principal y grant dentro del mismo tenant.
5. Un cambio de contacto invalida challenges pendientes y obliga a reautenticar una sesión cuyo
   fingerprint o revisión ya no coincida, como máximo en la siguiente operación protegida.
6. La recuperación repite una prueba de control sobre un contacto actualmente autorizado. Si no
   existe un canal utilizable, se requiere un procedimiento humano futuro, auditado y aprobado; no
   se inventan preguntas secretas ni fallback permisivo.
7. Los TTL exactos de challenges, idle y expiración absoluta serán parámetros de seguridad/producto
   cerrados antes de implementar. Este ADR solo exige que sean acotados, que challenges sean
   single-use y que sesiones roten y sean revocables.
8. Portal podrá usar Communications para sus challenges porque cada solicitud posee organización
   explícitamente resuelta. Communications no decidirá autenticación ni validez del challenge.

### 6. Merge de People, principals, grants y preferencias

1. Portal y Communications resolverán el conjunto canónico actual mediante `people.public`; no
   reescribirán ni asumirán la historia de People.
2. Si un merge deja un único principal aplicable, Portal conservará evidencia de la vinculación
   anterior y operará contra la persona canónica actual sin trasladar silenciosamente grants entre
   principals.
3. El grant conservará como evidencia la persona referenciada al emitirlo. En cada autorización,
   Portal resolverá su conjunto actual y exigirá que el principal, la persona histórica del
   `EventRequest` y el ancla efectiva pertenezcan al mismo conjunto canónico; no reescribirá FKs
   históricas de People o Commercial.
4. Si dos principals previamente distintos convergen en el mismo conjunto canónico, Portal:

   - marcará la colisión para conciliación auditada;
   - invalidará nuevos challenges y ampliaciones automáticas de scope;
   - no unirá principals, sesiones ni grants;
   - no permitirá que una sesión de un principal use grants del otro;
   - exigirá una decisión humana explícita para cualquier conciliación posterior.

5. Communications conservará historia propia de preferencias y supresiones, separada de
   `ConsentEvent`.
6. Para propósitos opcionales, cualquier supresión aplicable a un miembro del conjunto canónico
   prevalecerá. Solo una acción explícita posterior sobre la identidad canónica podrá restablecer
   una preferencia permisiva.
7. El merge no creará permiso, opt-in ni consentimiento. People seguirá decidiendo consentimiento
   efectivo; la base jurídica y el efecto legal definitivo de cada acción permanecen sujetos a
   política aprobada.

### 7. Consentimiento, preferencias y destinatario autorizado

1. People es la única autoridad de `ConsentEvent`, su evidencia y el consentimiento efectivo.
2. Communications es la única autoridad de preferencias, unsubscribe, supresiones por canal y
   propósito, hard bounces y su historia auditable.
3. Un unsubscribe modifica Communications. Solo invocará un puerto de People para registrar una
   revocación cuando una política legal aprobada determine que esa acción equivale a revocación de
   consentimiento.
4. Antes de materializar un mensaje, Communications evaluará de forma conjuntiva:

   - propósito y política aprobada;
   - consentimiento efectivo de People cuando corresponda;
   - preferencia/supresión efectiva de Communications;
   - contacto actual autorizado de People;
   - restricciones del canal y del proveedor.

5. Ausencia, contradicción no resuelta o policy desconocida fallan cerradamente. Una excepción para
   mensajes obligatorios de seguridad o servicio exige política aprobada y no permite incorporar
   contenido promocional.
6. La proyección del destinatario se resolverá lo más cerca posible del envío. El mensaje conservará
   solo el snapshot mínimo necesario, su fingerprint y la decisión aplicada; no convertirá ese
   snapshot en contacto maestro.

### 8. Intención, mensaje, outbox, intento y resultado

1. Communications distinguirá cuatro niveles:

   - intención: solicitud idempotente del dominio propietario, con propósito, agregado, versión
     causal, destinatario lógico y momento elegible;
   - mensaje lógico: canal, destinatario proyectado, plantilla/version exacta, variables resueltas,
     decisión de política, contenido hash y estado agregado de entrega;
   - intento: una llamada concreta a un adaptador, con número, tiempos, proveedor/cuenta,
     idempotency key, identificador externo y error normalizado;
   - evento de proveedor: evidencia autenticada recibida por webhook o conciliación, con identidad,
     tiempo del proveedor, tiempo de recepción y payload minimizado.

2. La intención y el outbox se crearán atómicamente. La materialización del mensaje será
   idempotente y conservará plantilla/version y variables necesarias sin registrar secretos en
   logs.
3. Los estados físicos podrán ajustarse durante implementación, pero deberán distinguir como
   mínimo pendiente, elegible, claimed, retry, entregado al proveedor, resultado confirmado,
   cancelado/obsoleto y fallo terminal.
4. Los errores se normalizarán como autenticación, rate limit, indisponibilidad, destinatario
   inválido, rechazo de política, permanente o desconocido. El detalle del proveedor no se
   convierte en vocabulario de dominio.
5. Un webhook o respuesta del proveedor puede avanzar el estado técnico del mensaje; nunca crea
   `EventRequest`, aceptación documental, reserva, pago, aplicación, devolución ni otro hecho de
   negocio.

### 9. Protocolo PostgreSQL de outbox y worker

1. El outbox y sus intentos serán tablas privadas de Communications protegidas por organización y
   RLS. PostgreSQL es la cola inicial; no se introducirán Redis, Celery, Dramatiq ni broker.
2. Claim usará locks no bloqueantes equivalentes a `FOR UPDATE SKIP LOCKED`, orden determinista,
   identidad de worker, lease recuperable y contador de intentos.
3. El worker hará commit del claim antes de llamar al proveedor. No mantendrá locks de filas durante
   I/O de red.
4. La entrega será at-least-once. Todo handler y adaptador deberá ser idempotente por organización,
   intención/mensaje y payload hash. Se enviará idempotency key al proveedor cuando exista, pero
   esa garantía externa no sustituye la persistencia local.
5. Un lease vencido permite reclaim. Un crash después de que el proveedor acepte y antes de
   persistir el resultado se resolverá mediante la misma idempotency key o conciliación; no se
   declarará exactly-once.
6. Retries usarán backoff exponencial con jitter, respetarán `Retry-After`, tendrán máximo acotado y
   terminarán en fallo observable. Reintentar manualmente crea una nueva acción auditada; no
   reescribe intentos previos.
7. El orden solo se exigirá cuando el originador declare una clave causal y secuencia. Un mensaje
   posterior no adelantará otro pendiente de la misma secuencia material.
8. El dominio propietario decide que un recordatorio quedó obsoleto. El coordinador invoca
   `communications.public` para cancelar o sustituir la intención dentro de la transacción del
   cambio autoritativo. Communications compara versión y supersesión; no reconstruye agenda,
   saldos o documentos desde copias locales.
9. Ante caída del proveedor, el hecho de negocio permanece confirmado, la cola conserva trabajo,
   se aplican límites/circuito y se alerta por edad, retries y fallos terminales.

### 10. Relación con ADR 0004 y `DocumentJob`

1. ADR 0004 permanece vigente: una infraestructura asíncrona requiere caso real, entrega,
   reintentos, orden, idempotencia, observabilidad y decisión explícita.
2. ADR 0018 satisfizo por primera vez esa condición para procesamiento documental mediante
   `DocumentJob`. P14 no se presenta como la primera asincronía absoluta.
3. Este ADR acepta el primer outbox transaccional transversal, limitado a Communications.
4. `DocumentJob`, `DocumentJobAttempt`, handlers y worker permanecen exclusivamente bajo
   `claridez.documents`; no aceptarán tipos de trabajo P14 ni se convertirán en cola genérica.
5. P14 reutilizará las propiedades probadas de claim, lease, at-least-once, idempotencia, retries y
   fallo terminal. Solo podrá extraer utilidades técnicas sin estado ni autoridad mediante un
   cambio explícito que preserve los dos ledgers tipados.
6. Un broker futuro requiere evidencia de que PostgreSQL no satisface latencia, throughput,
   aislamiento u operación y otra decisión arquitectónica.

### 11. Dispatcher y tenancy

1. El dispatcher de Communications seguirá el precedente documental: obtendrá organizaciones
   activas mediante una función tipada nueva de `organizations.public` y procesará una organización
   por vez.
2. Cada claim, materialización, envío, conciliación y registro de resultado entrará en
   `infrastructure_tenant_scope(organization_id, purpose="communications_worker")` o abstracción
   equivalente aprobada.
3. El worker no tendrá `BYPASSRLS`, tenant global, scope persistente de conexión ni permiso para
   seleccionar organización desde datos del mensaje sin revalidación.
4. No se creará una tabla global para localizar trabajo del dispatcher. Solo una necesidad medida
   de escala podrá justificarla mediante decisión posterior.
5. Los locators globales estrictamente necesarios para ingress externo —formularios, tokens Portal
   o endpoints webhook— no son colas ni fuentes de verdad: contienen únicamente HMAC, kind, tenant
   y referencia técnica mínima, y se revalidan dentro del scope.

### 12. Proveedores, adaptadores y webhooks

1. Correo, WhatsApp y antiabuso se consumirán mediante adaptadores definidos por Communications o
   Portal según su autoridad. SES, Resend, Meta, Twilio, Turnstile u otro proveedor no aparecerán en
   entidades ni estados de negocio fuera de campos técnicos de procedencia.
2. La selección definitiva, región, residencia, coste, soporte y operación permanecen pendientes.
   No se instalará una plataforma omnicanal ni infraestructura adicional sin necesidad demostrada.
3. Cada endpoint webhook tendrá un locator opaco o identidad de cuenta validada server-side que
   permita resolver la organización antes del scope. La firma nunca se valida con datos elegidos
   libremente por el request.
4. El receptor verificará HTTPS, firma sobre cuerpo crudo, timestamp/ventana de replay, secreto y
   cuenta/topic esperados antes de parsear efectos.
5. Cada evento tendrá unicidad por proveedor, cuenta y event id; si el proveedor no ofrece id
   estable, se usará un hash canónico con ventana y procedencia. El mismo evento nunca crea dos
   transiciones.
6. Los eventos se almacenarán primero como evidencia técnica y se reconciliarán mediante una
   máquina monotónica. Un evento tardío o fuera de orden puede completar historia, pero no degrada
   un estado confirmado ni reabre un fallo terminal sin una acción explícita.
7. Los webhooks serán endpoints sin CSRF porque no usan autenticación de navegador; su defensa es
   autenticidad, replay protection, rate limit, tamaño máximo e idempotencia. Portal y formularios
   aplicarán CSRF/origen según su superficie.

### 13. Integración documental sin reutilizar P9 como Portal

1. `claridez.documents` conserva en exclusiva documentos, expedientes, instrumentos, versiones,
   artefactos, descargas, aceptación, evidencia y retención.
2. `ExternalAccessGrant`, `ExternalDocumentSession`, `AcceptanceChallenge`,
   `ExternalTokenLocator`, `ExternalRateLimitBucket`, eventos y demás estado P9 permanecen en
   Documents. Portal no los importa, consulta, crea, extiende ni usa como principal, sesión o grant.
3. Los enlaces directos P9 siguen funcionando con su cookie, purpose, expiración y scopes propios.
   Una sesión Portal no es `ExternalDocumentSession` y un grant Portal no es
   `ExternalAccessGrant`.
4. Portal autenticará el principal y autorizará un grant/scoped action sobre el `EventRequest`.
   Después llamará a puertos de `documents.public` con un valor inmutable definido por Documents
   que contenga solo organización, `EventRequest`, referencia externa del principal/grant,
   assurance y acción solicitada.
5. Documents volverá a validar dentro de su autoridad la relación con expediente, instrumento,
   versión y artefacto, además de sustitución, disponibilidad, retención y acción permitida. La
   autorización efectiva es conjuntiva: sesión Portal válida + grant Portal suficiente + decisión
   documental válida.
6. Para lectura y descarga, Documents materializa la proyección o stream; Portal no obtiene
   storage keys ni consulta archivos privados.
7. Para aceptación desde Portal, un comando nuevo de `documents.public` revalidará versión y bytes
   exactos, idempotencia y manifestación y creará la evidencia bajo Documents con procedencia de
   autenticación Portal. No convertirá la sesión Portal en grant/session/challenge P9 ni permitirá
   que Portal escriba `AcceptanceEvidence`.
8. El flujo directo P9 podrá continuar usando internamente su `AcceptanceChallenge`; ese registro
   no se reutiliza para autenticar Portal. Compartir primitivas criptográficas sin estado solo será
   posible si el ADR o implementación demuestra que no mueve ni diluye autoridad documental.
9. Documents resolverá sus propias raíces e identidades. Portal no copiará `root_reservation_id` ni
   relaciones documentales como fuente de verdad.

### 14. Fronteras con dominios existentes

1. **People:** única autoridad de persona, contactos, aliases, merge, consentimiento y evidencia.
   Portal posee prueba de control y Communications preferencias; ninguno modifica esa autoridad.
2. **Commercial:** `EventRequest` sigue siendo la única oportunidad. Portal consume una proyección
   cliente y no altera estados por una entrega o login.
3. **Scheduling:** única autoridad temporal. Expondrá una proyección cliente por `EventRequest` con
   fecha, hora, zona, sede/espacio publicables y estado derivado. No expondrá buffers, holds, locks,
   revisiones ni ocupación privada.
4. **Receivables:** única autoridad de obligación, calendario, pagos, aplicaciones, reversos,
   devoluciones, recibos y saldo. Portal consume saldo, próxima obligación e historia minimizada.
   Un webhook de pago no crea un pago recibido.
5. **Operations:** conserva toda autoridad P13. P14 no reabre P13. Portal no expone checklist,
   incidencias, recursos, responsables o notas. Una proyección cliente de alto nivel será
   deny-by-default y solo existirá si el contrato de producto la aprueba expresamente.
6. **CRM:** intentos, webhooks, bounces y resultados técnicos nunca salen de Communications. Para
   un propósito marcado como interacción comercial, Communications podrá invocar un puerto
   idempotente de CRM una sola vez al alcanzar la transición semántica aprobada. CRM guardará
   persona, `EventRequest`, canal, dirección, propósito, timestamp, referencia y resumen; nunca
   cuerpo, proveedor, intento ni estado técnico.
7. **Identity:** `identity.User` es global y puede pertenecer a varias o ninguna organización. Sus
   mensajes actuales de recuperación y verificación siguen siendo decididos y entregados por
   Identity conforme a ADR 0010. P14 no fabrica tenant ni los migra a Communications. Una futura
   unificación del transporte global y tenant-aware requiere decisión separada.
8. **Organizations:** conserva Organization global, Membership, settings, capacidades y scopes.
   Clientes externos nunca reciben Membership.

### 15. Recordatorios

1. Scheduling decide recordatorios temporales y efectos de reprogramación/cancelación.
2. Receivables decide recordatorios de obligaciones.
3. Documents decide documentos o aceptaciones pendientes.
4. Portal decide únicamente autenticación, recuperación y acciones propias del portal.
5. Un coordinador obtiene la decisión del dominio propietario y solicita a Communications una
   intención con propósito, `not_before`, versión causal e idempotencia. Communications solo
   programa, suprime y entrega.
6. No habrá cron que copie o reconstruya agenda, saldo, aceptación o estado comercial en
   Communications.

### 16. Seguridad, capacidades y privilegios

1. Toda tabla privada P14 tendrá `organization_id`, FKs/unicidades tenant-aware, RLS `ENABLE` y
   `FORCE`, políticas simétricas y pruebas con el rol `claridez_app`.
2. `claridez_app` no tendrá `DELETE` ni `TRUNCATE` sobre preferencias históricas, intents, mensajes,
   outbox consumido, intentos, provider events, principals, grants, challenges o auditoría. Las
   mutaciones de estado usarán comandos controlados; hechos consumados se corrigen con nuevos
   hechos.
3. Se requerirán capacidades atómicas, como mínimo, para leer/administrar formularios, leer/gestionar
   plantillas, solicitar comunicaciones, leer entregas, reintentar fallos, leer/gestionar
   preferencias y leer/gestionar/revocar grants Portal.
4. El nombre físico y la matriz exacta de esas capabilities se aprobarán antes de abrir endpoints.
   Ningún rol heredará acceso por similitud. Además de la capability P14, una acción intermodular
   exigirá la capacidad del dominio propietario cuando corresponda.
5. Tokens y locators serán aleatorios, opacos, almacenados como HMAC, comparados en tiempo constante
   y revocables. Los secretos de proveedor estarán fuera del repositorio, separados por ambiente y
   rotables.
6. Formularios, login, challenges, recuperación, sesiones, downloads y webhooks tendrán rate limits
   distintos. No se confiará en headers de proxy hasta aprobar la topología.
7. Portal usará cookies `Secure`, `HttpOnly`, `SameSite` y path propio, CSRF en mutaciones,
   `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, CSP y `nosniff` donde corresponda.
8. Logs y métricas no contendrán cuerpos, variables sensibles, destinatarios completos, tokens,
   OTP, storage keys, secretos ni payloads crudos. Usarán IDs internos, hashes, códigos normalizados
   y correlation IDs.
9. El cliente externo solo recibe endpoints y proyecciones Portal; no puede seleccionar
   organización, capability interna, Membership ni rutas del workspace.

### 17. Retención, minimización y observabilidad

1. Communications conservará plantilla/version, propósito, contenido hash, decisión aplicada,
   estados, intentos y errores normalizados. Los cuerpos o variables sensibles solo se persistirán
   cifrados cuando una necesidad aprobada lo exija.
2. Portal conservará evidencia mínima de locator, captación, autenticación, sesión, grant y
   revocación. No copiará cuerpos documentales, agenda completa ni ledger financiero.
3. Los plazos de retención de mensajes, variables, challenges, sesiones expiradas, IP hashes,
   payloads/webhooks y recibos técnicos permanecen pendientes de política legal/producto. No habrá
   purga automática ni conservación presentada como plazo legal hasta aprobarlos.
4. La anonimización futura de People deberá preservar evidencia que tenga retención o legal hold y
   no convertirá un identificador pseudónimo en permiso de contacto.
5. Se medirán edad/profundidad del outbox, claims, leases vencidos, retries, fallos terminales,
   latencia por adaptador, bounces/complaints y webhooks inválidos sin PII.

### 18. Migración y compatibilidad

1. P14 se introducirá con migraciones aditivas. No se fabricarán formularios publicados,
   principals, grants, challenges, sesiones, preferencias, consentimientos, mensajes, entregas,
   intentos o webhooks históricos.
2. Personas y `EventRequest` existentes permanecerán sin acceso Portal hasta enrolamiento y grant
   explícitos.
3. Ausencia de preferencia significa «sin preferencia registrada», no permiso. Ausencia de
   `ConsentEvent` no se transforma en consentimiento.
4. Los enlaces, sesiones, challenges y aceptaciones P9 existentes continúan sin conversión.
5. Agenda, documentos y saldo históricos se consultarán en sus autoridades después de autorizar el
   grant; Portal no hará backfill de copias.
6. Identity conserva sin migración sus mensajes globales actuales.
7. La arquitectura aceptada no cambia P13, no presume deployment/cutover y no autoriza módulos,
   modelos, migraciones, endpoints, frontend, workers, dependencias ni configuración P14 hasta una
   aprobación posterior.

### 19. Pagos electrónicos fuera del P14 base

1. P14 solo consulta proyecciones de Receivables.
2. No se incorpora pasarela, custodia, tokenización de tarjetas, conciliación automática ni inicio
   de cobro electrónico.
3. Una futura pasarela requiere decisión de producto y ADR separado sobre proveedor, seguridad,
   conciliación y autoridad. Ningún evento de pasarela sustituirá el comando autorizado que crea un
   pago en Receivables.

## Aspectos provisionales

- Los nombres físicos de principals, locators, formularios, grants, sessions, preferences, intents,
  messages, outbox, attempts y provider events podrán ajustarse durante implementación si conservan
  las autoridades e invariantes de este ADR.
- El nombre del scope externo restringido y de los DTO de puertos podrá normalizarse antes de ser
  API estable. No podrá aceptar un tenant elegido libremente por el cliente ni exponer el helper del
  GUC.
- Los códigos concretos de estado y error podrán refinarse si mantienen la separación entre
  intención, mensaje, intento y evento de proveedor.

## Asuntos diferidos

- TTL exactos de locators, challenges, sesiones idle/absolutas, leases y ventanas de replay.
- Plazos jurídicos y operativos de retención, legal hold, anonimización y purga.
- Base jurídica por propósito/canal, textos de consentimiento, efecto legal de unsubscribe y
  comunicaciones obligatorias.
- Selección de proveedor de correo, WhatsApp y antiabuso; región, residencia, soporte, costes,
  cuotas y salida.
- Matriz final de capabilities P14 por los cinco perfiles y política de conciliación humana de
  principals fusionados.
- Datos exactos de Operations aptos para cliente; hasta aprobarlos no se exponen.
- Transporte unificado futuro para mensajes globales de Identity y tenant-aware de Communications.
- Broker o cola externos, sujetos a evidencia de que PostgreSQL dejó de ser suficiente.
- Pasarela de pago electrónico, fuera del P14 base.

## Validación pendiente

Antes de implementar o cerrar P14 se deberá demostrar, como mínimo:

- locators opacos, organizaciones suspendidas, formularios revocados y cruces negativos con dos
  tenants antes y después de RLS;
- prohibición arquitectónica de ORM/imports cruzados y materialización completa dentro del scope;
- captación atómica, idempotencia, deduplicación, colisiones de contactos y rollback completo;
- People como única autoridad de consentimiento y semántica conservadora de preferencias tras
  merge;
- principal, sesión y grants separados, múltiples `EventRequest`, cambio de contacto, merge,
  expiración, rotación, revocación y recuperación anti-enumeración;
- integración con Documents solo por puertos, continuidad P9 y aceptación Portal sin reutilizar
  P9 como autenticación general;
- outbox/worker con doble claim, lease vencido, crash antes/después del proveedor, retries, orden,
  obsolescencia, fallo terminal, outage y ausencia de `BYPASSRLS`;
- webhooks falsos, alterados, replayed, duplicados y fuera de orden;
- proyecciones minimizadas de Scheduling, Receivables, Documents, Commercial y, si se aprueba,
  Operations;
- CRM sin cuerpos ni estado técnico e Identity sin dependencia tenant-aware;
- privilegios efectivos, `ENABLE` + `FORCE RLS`, ORM, bulk y SQL directo con `claridez_app`;
- migración desde P13 final sin backfills ficticios, OpenAPI, frontend público/Portal/workspace,
  accesibilidad y gates oficiales aplicables.

## Alternativas consideradas

### Un solo módulo técnico P14

Se rechaza porque mezclaría identidad/sesión externa con entrega, proveedores, retries y webhooks.
Dos módulos técnicos conservan un único dominio funcional con autoridades acotadas.

### Usar `identity.User` o Membership para clientes

Se rechaza. Identity es global y Membership concede acceso al workspace; ninguna representa una
identidad externa limitada a grants por `EventRequest`.

### Anclar Portal solo a `root_reservation_id`

Se rechaza porque el acceso puede existir antes de confirmar una reserva. La solicitud comercial es
estable antes y después de la raíz temporal.

### Aceptar un `organization_id` anónimo

Se rechaza porque un identificador aportado por cliente no es autorización y permitiría elegir el
GUC tenant. El locator opaco resuelto y revalidado por servidor es obligatorio.

### Convertir P9 en autenticación general

Se rechaza. Sus grants, sesiones, locators y challenges están ligados a propósito, versión y
artefacto documentales. Portal usa estado propio y consume Documents mediante puertos.

### Convertir `DocumentJob` en cola transversal

Se rechaza. Mezclaría autoridad documental con comunicaciones y produciría un catálogo de jobs
omnipotente. P14 adopta otro ledger tipado que reutiliza propiedades, no tablas P9.

### Instalar Redis, Celery o una plataforma omnicanal

Se rechaza para el inicio. PostgreSQL ya es dependencia operada y satisface el volumen conocido;
otra plataforma requiere evidencia posterior.

### Inferir consentimiento desde preferencia o proveedor

Se rechaza. People conserva consentimiento; preferencias y señales de transporte no crean base
jurídica ni permiso implícito.

### Migrar correo global de Identity a Communications

Se rechaza en P14. Un usuario global no tiene un tenant único y no se fabricará una organización
para transportarlo.

## Consecuencias

### Positivas

- P14 obtiene límites explícitos sin convertir CRM, Commercial, Identity o Documents en módulos
  omnipotentes.
- La captación pública puede entrar a RLS sin confiar en un tenant aportado por cliente.
- La sesión externa y la autorización por evento quedan separadas y revocables.
- Los hechos de negocio y la intención de envío son atómicos, mientras el proveedor permanece fuera
  de la transacción.
- P9 conserva autoridad y compatibilidad; el nuevo worker parte de propiedades ya probadas.
- El modelo permite cambiar proveedor sin cambiar verdad de negocio.

### Costes y riesgos

- Se añaden dos módulos, puertos, dos tipos de scope externo/interno y más pruebas de integración.
- At-least-once exige idempotencia y conciliación; no existe promesa exactly-once.
- Los locators globales mínimos requieren disciplina para no acumular PII o estado funcional.
- Merge, contacto cambiado y múltiples grants aumentan el coste de autorización y auditoría.
- La implementación no puede cerrar política de retención, base jurídica o proveedor mediante
  decisiones técnicas implícitas.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [ADR 0004 — Diferir infraestructura asíncrona](0004-defer-asynchronous-infrastructure.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0010 — Identidad local y sesiones](0010-local-identity-and-server-sessions.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0015 — People, CRM y autoridad comercial](0015-people-crm-boundaries-and-commercial-authority.md)
- [ADR 0016 — Scheduling e integridad temporal](0016-scheduling-ownership-and-temporal-integrity.md)
- [ADR 0017 — Dominio contractual y evidencia](0017-contractual-domain-and-documentary-evidence.md)
- [ADR 0018 — Plataforma de archivos y procesamiento documental](0018-file-platform-and-document-processing.md)
- [ADR 0019 — Receivables e integridad financiera](0019-receivables-authority-and-financial-movement-integrity.md)
- [ADR 0022 — Operación avanzada P13](0022-advanced-operations-plans-and-execution-integrity.md)
- Código vigente de `claridez.documents`, incluidos `models.py`, `external_access.py`, `jobs.py` y
  `documents_worker.py`, inspeccionado antes de aceptar este ADR.
- Puertos vigentes de Organizations, People, Commercial, Documents, Scheduling, Receivables y
  Operations, inspeccionados antes de aceptar este ADR.

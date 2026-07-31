# ADR 0011 — Organizaciones, membresías y autorización

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez necesita representar organizaciones locales, vincular usuarios mediante membresías y
autorizar cada operación desde el backend. Un usuario puede pertenecer a varias organizaciones, de
modo que ni un identificador enviado por el cliente ni una preferencia guardada en sesión pueden
otorgar acceso por sí solos.

La Iteración 4 todavía no define módulos funcionales. La autorización inicial debe cubrir la
infraestructura organizacional sin convertirse silenciosamente en el contrato de permisos de los
módulos comerciales, operativos o financieros futuros.

## Decisiones aceptadas

### Entidades locales

Se aprueban las entidades productivas `Organization`, `Membership` y `OrganizationSettings`:

- `Organization` representa el límite organizacional y la fila que se bloqueará al proteger
  invariantes concurrentes de sus membresías.
- `Membership` vincula un usuario local con una organización, un rol provisional y un estado de
  membresía. La combinación usuario-organización será única en PostgreSQL.
- `OrganizationSettings` pertenece obligatoriamente a una organización y será la primera entidad
  privada productiva protegida por RLS. Contendrá inicialmente la moneda y la zona horaria de la
  organización, con USD y `America/Guayaquil` como valores iniciales configurables. Su
  implementación y el RLS productivo pertenecen a 4.5, no a 4.2.

Los ciclos de vida, campos y transiciones no enumerados aquí no quedan autorizados por inferencia.
Las entidades se implementarán dentro del monolito modular y no constituyen un servicio separado.

### Ciclos de vida cerrados en 4.2

`Organization` usa UUIDv4, nombre visible, slug ASCII canónico y globalmente único, estado y marcas
`created_at`/`updated_at`. Sus únicos estados son `active` y `suspended`. Se crea siempre activa y
puede suspenderse o reactivarse mediante transición explícita. El slug usa
`django.utils.text.slugify`, admite como máximo 63 caracteres, no se trunca, no recibe sufijos
automáticos y permanece inmutable en las rutas soportadas. `country_code` queda diferido.

`Membership` usa UUIDv4, usuario, organización, rol, estado, `joined_at`, `suspended_at`,
`revoked_at`, `created_at` y `updated_at`. Los identificadores técnicos de los roles provisionales
son `owner`, `administrator`, `commercial`, `operations` y `finance`, con correspondencia exacta a
los nombres aprobados en español. Sus únicos estados son `active`, `suspended` y `revoked`.

La combinación usuario-organización identifica una relación persistente única, no un historial
completo de eventos. `joined_at` conserva la primera incorporación. Una membresía revocada puede
volver explícitamente a `active` si el usuario está activo; esa transición limpia `revoked_at` y
`suspended_at` sin crear otra fila. La auditoría detallada de ciclos repetidos queda diferida.

No existe borrado físico normal. Las FK a usuario y organización usan `PROTECT` y el rol
`claridez_app` no recibe `DELETE` sobre estas dos tablas globales de control.

### Contexto y autorización backend-first

Toda operación protegida deberá:

1. autenticar la sesión y comprobar el estado y la versión de seguridad del usuario;
2. tratar el identificador solicitado y `last_organization_id` como datos no confiables;
3. entrar por `authorized_tenant_scope` de ADR 0009;
4. validar dentro del scope la organización, la membresía activa y la capacidad requerida;
5. completar validaciones, consultas privadas y materialización de la respuesta antes de cerrar el
   scope.

El frontend podrá ocultar acciones para mejorar la experiencia, pero no será una barrera de
autorización. Capacidades desconocidas, roles no reconocidos, membresías inactivas o ausencia de
contexto se denegarán por defecto. No habrá jerarquía implícita entre roles: los servicios exigirán
capacidades concretas.

Cambiar `last_organization_id` solo cambiará una preferencia de sesión después de validar una
membresía activa. No renovará la expiración absoluta de ocho horas definida en ADR 0010.

### Matriz provisional de capacidades

La matriz aceptada para la infraestructura inicial es:

| Capacidad | `propietario` | `administrador` | `comercial` | `operaciones` | `finanzas` |
|---|:---:|:---:|:---:|:---:|:---:|
| `organization:access` | Sí | Sí | Sí | Sí | Sí |
| `organization_settings:read` | Sí | Sí | Sí | Sí | Sí |
| `organization_settings:update` | Sí | Sí | No | No | No |
| `membership:read` | Sí | Sí | No | No | No |
| `membership:manage_non_owner` | Sí | Sí | No | No | No |
| `membership:manage_owner` | Sí | No | No | No | No |
| `membership:revoke_sessions` | Sí | Sí, para membresías no propietarias | No | No | No |

Todas las capacidades requieren además usuario, organización y membresía activos. Administrar una
membresía no propietaria no permite promoverla a `propietario`, modificar una membresía
propietaria ni evadir las protecciones del último propietario.

No existe la capacidad «transferir propiedad»: Claridez no tiene un propietario principal ni un
acto de transferencia. Puede haber varios propietarios activos con igual rol. La capacidad
`membership:manage_owner` permite administrar ese conjunto, siempre sujeta a la invariante del
último propietario.

Esta matriz es provisional y se limita a identidad, configuración y membresías de la Iteración 4.
No concede accesos a módulos futuros ni constituye su contrato definitivo. Los propósitos generales
de `comercial`, `operaciones` y `finanzas` permanecen aprobados, pero cada módulo futuro deberá
definir y aprobar capacidades explícitas antes de implementarlas.

### Protección del último propietario

Cualquier operación que pueda desactivar, revocar, eliminar o cambiar el rol de una membresía
`propietario` deberá usar un único servicio de dominio transaccional. Ese servicio deberá:

1. abrir `transaction.atomic()`;
2. bloquear la fila de `Organization` mediante `SELECT ... FOR UPDATE` antes de contar o modificar
   propietarios;
3. bloquear después la `Membership` afectada para evitar actualizaciones perdidas;
4. volver a consultar dentro de la transacción las membresías propietarias activas;
5. rechazar la operación si dejaría cero propietarios activos;
6. aplicar el cambio y cualquier revocación de sesiones como una sola unidad coherente.

Todas las mutaciones de membresías siguen el orden `Organization → Membership` y reutilizan el
mismo servicio, aunque la membresía no sea propietaria. Operaciones sobre una misma organización
se serializan; organizaciones distintas conservan concurrencia independiente.

Vistas, serializers, comandos y futuras tareas no podrán cambiar directamente rol o estado de una
membresía. La protección se probará con intentos concurrentes sobre una organización con uno y con
varios propietarios. No se asume un orden, precedencia ni propietario principal.

La revocación de una membresía o de sus sesiones será efectiva desde la siguiente operación
protegida, que vuelve a comprobar sesión y membresía. No se intentará cancelar una transacción que
ya comenzó después de superar esos controles.

### Django Admin

Django Admin permanecerá deshabilitado durante esta iteración y en producción. No se expondrán sus
URLs ni se lo usará para eludir servicios de autorización o invariantes transaccionales. Esta es una
decisión del alcance actual, no una prohibición permanente: una iteración futura podrá evaluarlo
mediante una decisión explícita y controles equivalentes.

## Aspectos provisionales

- Los cinco roles y las capacidades de infraestructura de la matriz son provisionales.
- Los nombres técnicos de las capacidades podrán normalizarse antes de constituir API pública si
  se conserva una correspondencia exacta y probada con esta matriz.
- El ciclo de vida detallado de una organización y una membresía se limitará a los estados mínimos
  que apruebe la especificación de 4.2.

## Asuntos diferidos

- Invitaciones y registro público.
- Roles personalizados, capacidades por plan y contrato de autorización de módulos futuros.
- Proveedor OIDC.
- Acceso transversal de soporte y su auditoría reforzada.
- Administración visual de organizaciones y membresías.
- Una reevaluación futura de Django Admin.
- Capacidades, permisos DRF y autorización del actor, que pertenecen a 4.4.
- `OrganizationSettings`, `authorized_tenant_scope` y RLS productivo, que pertenecen a 4.5.
- Auditoría detallada de múltiples ciclos de una membresía.

## Validación de 4.2

La migración inicial de organizaciones deberá demostrar:

- estados y transiciones mínimos de `Organization` y `Membership`, sin inventar ciclos de vida de
  negocio;
- restricciones de unicidad, pertenencia organizacional e integridad relacional en PostgreSQL;
- concurrencia de promoción, degradación, suspensión y revocación de propietarios;
- reactivación de una relación revocada sin duplicar la fila ni cambiar `joined_at`;
- rollback después de adquirir el bloqueo y ausencia de bloqueos globales entre organizaciones;
- bootstrap local transaccional, idempotente por organización y protegido con advisory lock;
- propiedad por el migrador, DML limitado para la aplicación y ausencia de RLS.

Las acciones privilegiadas de esta matriz no podrán usarse productivamente sin MFA, salvo que el
propietario registre de forma explícita un riesgo temporal aceptado según ADR 0010.

## Alternativas consideradas

### Un único propietario principal

Se rechaza en esta etapa. Añadiría una precedencia y un flujo de transferencia que no existen en el
modelo aprobado.

### Comprobaciones de rol solo en vistas o frontend

Se rechazan. Duplicarían reglas, permitirían bypasses desde otros puntos de entrada y no protegerían
invariantes concurrentes.

### Cambio directo de membresías con una validación previa

Se rechaza para cambios de propietarios. Sin bloqueo de la organización, dos transacciones podrían
observar propietarios distintos y dejar la organización sin ninguno.

### Django Admin como administración inicial

No se adopta en esta iteración ni en producción. No garantiza por sí solo los scopes tenant-aware,
las capacidades ni el servicio transaccional aprobado.

## Consecuencias

- Las organizaciones y membresías son locales y no dependen de un proveedor de identidad.
- La autorización queda centralizada en servicios backend-first y deniega por defecto.
- Varias personas pueden compartir el rol `propietario` sin crear un concepto de propiedad
  principal.
- `claridez.organizations` contiene en 4.2 únicamente `Organization` y `Membership` como tablas
  globales de control.
- `OrganizationSettings` será el primer caso productivo para demostrar RLS, aislamiento negativo y
  materialización dentro del scope.
- No se implementan todavía invitaciones, soporte transversal, administración visual ni módulos
  funcionales.
- Aceptar este ADR no autoriza modelos, migraciones, endpoints ni el resto de la Iteración 4.

## Evidencia

- [ADR 0003 — Fundamentos multiempresa](0003-multitenancy-foundations.md)
- [ADR 0009 — Estrategia de aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0010 — Identidad local y sesiones de servidor](0010-local-identity-and-server-sessions.md)
- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)

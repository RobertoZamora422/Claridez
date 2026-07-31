# ADR 0010 — Identidad local y sesiones de servidor

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez necesita una identidad inicial que no dependa de un proveedor externo y que permita
autenticación, revocación y autorización backend-first. El modelo de usuario intercambiable debe
existir en la primera migración de su aplicación porque sustituirlo después de crear tablas
dependientes tendría un costo alto.

La identidad de una persona dentro de Claridez y las credenciales de un proveedor OIDC son
conceptos distintos. Esta decisión define el usuario local productivo de 4.1 y la invalidación de
sus sesiones; no autoriza endpoints de autenticación ni entidades organizacionales.

## Decisiones aceptadas

### Identidad local desacoplada

- Claridez tendrá autenticación propia con Django y sesiones de servidor.
- La entidad local de usuario será permanente y no dependerá de un proveedor OIDC.
- Un proveedor OIDC futuro se vinculará mediante una entidad `ExternalIdentity` separada. No se
  reutilizarán campos del usuario local para guardar identificadores o tokens del proveedor.
- No habrá registro público, invitaciones ni proveedor OIDC en esta iteración.
- La autenticación y la autorización se denegarán por defecto ante estados o reglas no definidos.

### Modelo de usuario definitivo

La decisión para `identity/0001_initial.py` es definitiva: `claridez.identity.User` heredará de
`AbstractUser`.

- `id` será un UUIDv4 y la clave primaria.
- `username`, `first_name`, `last_name` y `date_joined` se eliminarán del modelo heredado.
- `display_name` sustituirá los nombres heredados y podrá comenzar vacío mientras no exista un
  flujo aprobado que lo exija.
- `email` será `USERNAME_FIELD` y `REQUIRED_FIELDS` será una lista vacía.
- Un manager personalizado creará usuarios y superusuarios con el correo canónico y una pareja
  coherente de `status` e `is_active`.
- El usuario será global: no tendrá `organization_id` ni referencia tenant.

La única representación de fechas será `created_at` para creación y `updated_at` para última
actualización. Se conserva `last_login` porque tiene una semántica técnica distinta. La contraseña
seguirá siendo administrada por Django.

Los campos productivos aprobados son exclusivamente:

- `id`, `email`, `display_name` y `status`;
- `email_verified_at` y `security_version`;
- `is_active`, `is_staff`, `is_superuser` y `last_login`;
- `created_at`, `updated_at` y `password`;
- las relaciones técnicas heredadas `groups` y `user_permissions`.

No se añadirán en 4.1 teléfonos, nombres separados, organización activa, datos de recuperación,
tokens, preferencias de sesión ni campos tenant.

### Correo canónico

Una única función pura compartida por manager y modelo definirá el correo canónico:

1. eliminar espacios exteriores;
2. convertir la dirección completa a minúsculas;
3. rechazar el resultado vacío.

No se delegará esta regla en `BaseUserManager.normalize_email()`, porque ese método solo garantiza
la normalización del dominio. `email` será no nulo y único en PostgreSQL. Una restricción `CHECK`
exigirá que el valor almacenado sea no vacío e idéntico a `lower(trim(email))`; de este modo ni SQL
directo ni operaciones que omitan el modelo podrán persistir otra representación.

Las validaciones Django ofrecerán errores útiles, pero no sustituirán la unicidad ni la
representación canónica garantizadas por PostgreSQL.

### Estado e `is_active`

`status` será el estado de dominio y `is_active` su proyección técnica compatible con Django:

| `status` | `is_active` |
|---|:---:|
| `pending_verification` | `false` |
| `active` | `true` |
| `suspended` | `false` |

Una restricción `CHECK` rechazará cualquier combinación distinta. El manager y el único método de
transición incluido en 4.1 actualizarán ambos valores juntos. No se utilizarán signals ni dos
flujos de sincronización.

`email_verified_at` será nulo hasta que un flujo futuro registre la verificación. 4.1 no infiere
una transición automática ni añade restricciones temporales no aprobadas entre ese campo y
`status`.

`security_version` será un entero positivo con valor inicial explícito `1`. PostgreSQL rechazará
valores menores que uno.

### Hash de autenticación de sesión

`security_version` y el identificador inmutable del usuario formarán parte del valor protegido por
el HMAC de autenticación de sesión, junto con el hash de contraseña administrado por Django. La
implementación sobrescribirá el punto interno `_get_session_auth_hash(secret=None)` para que los
métodos públicos de Django sigan usando automáticamente `SECRET_KEY` y
`SECRET_KEY_FALLBACKS`.

Como consecuencias:

- dos usuarios con la misma contraseña no compartirán un hash de sesión equivalente;
- incrementar `security_version` invalidará sesiones emitidas con la versión anterior;
- cambiar la contraseña conservará el comportamiento de invalidación de Django;
- un usuario suspendido será rechazado por el backend de autenticación y en la siguiente carga de
  una sesión existente;
- el valor expuesto será el HMAC y no la contraseña, su hash almacenado ni `security_version`.

Una suspensión o revocación de sesión será efectiva desde la siguiente operación protegida. No se
intentará cancelar una transacción que ya superó esos controles y está en ejecución.

### Permisos técnicos de Django

`is_staff`, `is_superuser`, `groups` y `user_permissions` se conservan solo para compatibilidad
técnica con Django. No representan roles organizacionales, no originan capacidades del producto,
no sustituyen `Membership` y no autorizan endpoints administrativos.

Django Admin permanecerá sin aplicación instalada y sin URL durante esta iteración y en
producción. Esta decisión no es una prohibición permanente.

## Aspectos provisionales

Ninguno para el modelo inicial. Sus campos, base, estados, correo canónico y hash de sesión quedan
cerrados antes de generar `identity/0001_initial.py`.

## Asuntos diferidos

Para 4.2:

- organizaciones, membresías, roles de producto y autorización tenant.

Para 4.3:

- expiración absoluta de sesión de ocho horas y ausencia de «recordarme»;
- endpoints de login, logout, recuperación y verificación;
- cookies, CSRF y rotación de la sesión durante autenticación;
- evaluación e incorporación condicional de `django-axes`;
- entrega real de correo.

También permanecen diferidos el proveedor OIDC, `ExternalIdentity`, registro público, invitaciones
y MFA. La entrega de correo será obligatoria antes de incorporar usuarios externos. MFA deberá
resolverse antes del uso productivo de acciones privilegiadas o registrarse como riesgo temporal
aceptado.

## Validación pendiente

4.1 deberá demostrar antes de finalizar:

- que la migración inicial nace del modelo final y no deja cambios pendientes;
- correo canónico, unicidad y coherencia estado/`is_active` en PostgreSQL;
- UUIDv4, manager, contraseña utilizable e inutilizable y campos heredados eliminados;
- cambio de hash por contraseña y `security_version`, aislamiento entre usuarios y ausencia de
  exposición directa;
- invalidación de una sesión anterior y rechazo de un usuario suspendido;
- funcionamiento de `SECRET_KEY_FALLBACKS`;
- migración desde cero, propiedad por el migrador, reversión y nueva migración en una base
  PostgreSQL desechable.

La expiración absoluta, `django-axes`, cookies y endpoints no son bloqueadores de 4.1 porque
pertenecen expresamente a 4.3.

## Alternativas consideradas

### `AbstractBaseUser`

Se descarta para el modelo inicial. `AbstractUser` permite eliminar los campos no deseados y
conservar integración probada con hashes, permisos y backends de Django sin mantener una
implementación completa innecesaria.

### OIDC como única identidad desde el inicio

Se rechaza. Acoplaría el identificador local y el ciclo de vida del usuario a un proveedor todavía
no seleccionado.

### Tokens de acceso administrados por el frontend

No se eligen para el inicio. Las sesiones Django reducen la superficie de almacenamiento de tokens
en el navegador y mantienen el control inicial en el backend.

### Signals para sincronizar `status` e `is_active`

Se rechazan. Ocultarían una invariante central y no protegerían escrituras directas en PostgreSQL.

## Consecuencias

- `AUTH_USER_MODEL = "identity.User"` deberá estar configurado antes de cualquier migración
  dependiente.
- La aplicación `claridez.identity` será la única aplicación productiva creada en 4.1.
- Las migraciones estándar de Django conservarán su grafo natural; no se impondrá un orden manual.
- El usuario global no prueba ni introduce aislamiento tenant o RLS.
- No se añade todavía `django-axes`, correo, MFA, endpoints ni frontend.
- Aceptar e implementar este ADR en 4.1 no autoriza 4.2 ni fases posteriores.

## Evidencia

- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)
- [ADR 0003 — Fundamentos multiempresa](0003-multitenancy-foundations.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)

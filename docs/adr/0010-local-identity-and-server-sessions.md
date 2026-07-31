# ADR 0010 — Identidad local y sesiones de servidor

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez necesita una identidad inicial que no dependa de un proveedor externo y que permita
autenticación, revocación y autorización backend-first. La decisión debe preceder a la primera
migración de identidad porque sustituir el modelo de usuario de Django después de crear tablas
productivas tendría un costo alto.

La identidad de una persona dentro de Claridez y las credenciales de un proveedor OIDC son
conceptos distintos. Las sesiones deben tener un límite absoluto y deben invalidarse cuando cambie
el estado de seguridad, incluso si el navegador conserva una cookie anterior.

## Decisiones aceptadas

### Identidad local desacoplada

- Claridez tendrá autenticación propia con Django y sesiones de servidor.
- La entidad local de usuario será permanente y no dependerá de un proveedor OIDC.
- Un proveedor OIDC futuro se vinculará mediante una entidad `ExternalIdentity` separada. No se
  reutilizarán campos del usuario local para guardar identificadores o tokens del proveedor.
- No habrá registro público, invitaciones ni proveedor OIDC en esta iteración.
- La autenticación y la autorización se denegarán por defecto ante estados o reglas no definidos.

### Decisión obligatoria del modelo de usuario

No se podrá crear `identity/0001_initial.py` hasta completar y registrar en este ADR la elección
del modelo de usuario y comprobarla con una migración desechable.

La opción preferida es heredar de `AbstractUser`, eliminar `username`, usar correo como
`USERNAME_FIELD` y adaptar formularios, admin técnico no expuesto y configuración de Django. Solo
una razón técnica concreta, reproducible y documentada permitirá elegir `AbstractBaseUser`.

Si se mantiene `AbstractBaseUser`, antes de la migración inicial deberán quedar definidos y
probados en conjunto:

- manager y métodos de creación de usuario y superusuario;
- semántica y persistencia de `is_active`, `is_staff` e `is_superuser`;
- backend de autenticación y política de identificación por correo;
- integración con permisos técnicos de Django;
- comportamiento de usuarios con contraseña inutilizable;
- formularios y comandos técnicos mínimos necesarios, sin habilitar Django Admin.

En cualquiera de las dos opciones, `AUTH_USER_MODEL` deberá existir desde la primera migración que
lo necesite. No se crearán primero tablas contra `auth.User` para sustituirlas después.

### Correo canónico e invariantes del usuario

El correo completo se normalizará a minúsculas antes de validar y persistir; no solo se
normalizará el dominio. La representación canónica será la única almacenada. PostgreSQL deberá
proteger tanto `email = lower(email)` como la unicidad de la forma canónica mediante restricciones
compatibles con el modelo elegido. Las validaciones Django ofrecerán mensajes útiles, pero no
sustituirán esas garantías frente a concurrencia.

`status` e `is_active` expresarán una sola decisión de autenticabilidad. Como mínimo se impondrán
estas invariantes:

| `status` | `is_active` | Invariantes temporales |
|---|---:|---|
| `pending_verification` | `false` | `email_verified_at`, `suspended_at` y `revoked_at` son nulos |
| `active` | `true` | `email_verified_at` existe; `suspended_at` y `revoked_at` son nulos |
| `suspended` | `false` | `email_verified_at` y `suspended_at` existen; `revoked_at` es nulo |
| `revoked` | `false` | `revoked_at` existe; verificación o suspensión previas pueden conservarse como hechos históricos |

Si un usuario revocado conserva `suspended_at`, ese instante no podrá ser posterior a
`revoked_at`. Las transiciones deberán actualizar estado, booleano y timestamps de forma atómica y
las restricciones PostgreSQL rechazarán combinaciones imposibles. Un usuario suspendido o revocado
no podrá autenticarse mediante el backend de Django ni conservar acceso por una sesión previa.

El nombre exacto de los valores podrá revisarse antes de la primera migración, pero no podrá
debilitar estas invariantes ni crear dos fuentes de verdad sobre autenticabilidad.

### Sesiones e invalidación

- Cada autenticación correcta iniciará una sesión con expiración absoluta de ocho horas. No habrá
  opción «recordarme».
- La sesión guardará un instante de inicio y una expiración absoluta inmutables, o un mecanismo
  equivalente probado en cada petición. Tanto la cookie como el registro de servidor quedarán
  limitados por ese mismo instante absoluto.
- Guardar o cambiar `last_organization_id` no recalculará ni extenderá la expiración. Ninguna
  modificación ordinaria de la sesión producirá expiración deslizante.
- `last_organization_id` será solo una preferencia de contexto. Cada operación protegida volverá a
  validar organización, membresía activa y capacidad; nunca será prueba de autorización.
- `security_version` formará parte de `get_session_auth_hash()` o de un mecanismo equivalente
  comprobado en cada petición protegida. Incrementarlo invalidará todas las sesiones emitidas con
  versiones anteriores.
- Cambios de contraseña, suspensión, revocación y demás eventos globales de seguridad deberán
  incrementar `security_version` dentro de la misma transacción. No se conservará la sesión actual
  mediante una actualización de hash cuando el objetivo sea revocar todas las sesiones.

Una suspensión o revocación será efectiva desde la siguiente operación protegida que vuelva a
comprobar la sesión, el usuario o la membresía. No se intentará cancelar una transacción que ya
superó esos controles y está en ejecución.

### Endurecimiento de intentos de acceso

`django-axes` queda aprobado condicionalmente, pero no se incorporará hasta verificar su versión,
compatibilidad con las versiones fijadas de Django y Python, mantenimiento y auditoría de
dependencias. Su incorporación requerirá antes una política escrita y pruebas que definan de forma
explícita:

- qué IP se considera confiable y cómo se obtiene;
- que la clave de correo usa la misma normalización canónica completa;
- límites temporales por combinación de correo normalizado e IP;
- un límite adicional por IP ante rotación de correos;
- expiración automática de bloqueos y contadores;
- comportamiento detrás de proxies y lista exacta de proxies confiables;
- respuestas genéricas que no permitan enumerar cuentas.

No se permitirá un bloqueo global permanente o fácilmente provocable basado únicamente en el
correo. Los valores numéricos y ventanas deberán aprobarse antes de agregar la dependencia; este
ADR no los inventa.

## Aspectos provisionales

- Los nombres de los estados podrán ajustarse antes de `identity/0001_initial.py` si se conservan
  las mismas garantías.
- La implementación exacta de la expiración absoluta y del hash de sesión deberá elegirse mediante
  una prueba contra el backend de sesiones adoptado.

## Asuntos diferidos

- Invitaciones y registro público.
- Proveedor OIDC y la entidad productiva `ExternalIdentity`.
- Entrega real de correo. No bloquea esta iteración, pero será obligatoria antes de incorporar
  usuarios externos.
- MFA. No bloquea esta iteración; deberá resolverse antes del uso productivo de acciones
  privilegiadas o registrarse explícitamente como riesgo temporal aceptado por el propietario.

## Validación pendiente

Antes de `identity/0001_initial.py`:

- decidir y documentar por completo `AbstractUser` sin `username` o la excepción basada en
  `AbstractBaseUser`;
- probar autenticación por correo canónico, contraseñas inutilizables y rechazo de todos los
  estados no activos;
- comprobar restricciones PostgreSQL de minúsculas, unicidad y estados bajo concurrencia;
- probar que `security_version` invalida sesiones anteriores en la petición siguiente;
- probar ocho horas absolutas aunque cambie repetidamente `last_organization_id`;
- definir el tratamiento de sesiones anónimas y rotación de identificador al autenticar.

La evaluación de `django-axes`, la política concreta de intentos y su auditoría se realizarán solo
antes de decidir su incorporación; no forman parte de 4.0.

## Alternativas consideradas

### OIDC como única identidad desde el inicio

Se rechaza. Acoplaría el identificador local y el ciclo de vida del usuario a un proveedor todavía
no seleccionado.

### Tokens de acceso administrados por el frontend

No se eligen para el inicio. Las sesiones Django reducen la superficie de almacenamiento de tokens
en el navegador y mantienen el control inicial en el backend.

### Sesión deslizante o «recordarme»

Se rechaza para esta etapa. La ventana aceptada es absoluta y no se renueva por actividad.

### Bloqueo solo por correo

Se rechaza por riesgo de denegación de servicio dirigida contra una cuenta.

## Consecuencias

- El modelo de usuario debe quedar bien definido antes de la primera migración; esta es una puerta
  de entrada para 4.1, no una decisión que pueda corregirse silenciosamente después.
- La aplicación deberá comprobar estado y versión de seguridad en cada operación protegida.
- La identidad local podrá vincularse a uno o varios proveedores futuros sin cambiar su clave
  primaria ni su ciclo de vida.
- No se añade todavía `django-axes`, correo, MFA ni un proveedor externo.
- Aceptar este ADR no autoriza implementar el resto de la Iteración 4.

## Evidencia

- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)
- [ADR 0003 — Fundamentos multiempresa](0003-multitenancy-foundations.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
